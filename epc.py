"""
epc.py — EPC floor area lookup via UK Government EPC Open Data API

Fetches the most recent domestic EPC certificate for a property by address + postcode,
returning the surveyor-measured total floor area. This is more reliable than
agent-reported sqft which often includes basements, outbuildings, and lower-ground floors.

API: https://epc.opendatacommunities.org/api/v1/domestic/search
Auth: HTTP Basic (email + API key — free registration at epc.opendatacommunities.org)
Results cached in epc_cache.json for 90 days (EPCs rarely change).

Usage:
    from epc import enrich_epc, save_epc_cache
    enrich_epc(listing)   # adds listing["epc_sqft"], listing["epc_sqm"]
    save_epc_cache()
"""

import base64
import json
import os
import re
import urllib.request
import urllib.error
import urllib.parse
from datetime import datetime
from pathlib import Path
from typing import Optional

from config import EPC_CACHE_FILE, EPC_CACHE_MAX_AGE_DAYS

_EPC_API_BASE = "https://epc.opendatacommunities.org/api/v1/domestic/search"
_SQM_TO_SQFT = 10.7639

_cache: dict = {}
_cache_dirty = False
_CACHE_PATH = Path(EPC_CACHE_FILE)


def _load_cache() -> dict:
    global _cache
    if _cache:
        return _cache
    if _CACHE_PATH.exists():
        try:
            _cache = json.loads(_CACHE_PATH.read_text())
        except Exception:
            _cache = {}
    return _cache


def _save_cache() -> None:
    global _cache_dirty
    if _cache_dirty:
        _CACHE_PATH.write_text(json.dumps(_cache, indent=2, ensure_ascii=True))
        _cache_dirty = False


def save_epc_cache() -> None:
    """Call after all EPC enrichment is done."""
    _save_cache()


def _auth_header() -> Optional[str]:
    email = os.environ.get("EPC_API_EMAIL", "")
    key = os.environ.get("EPC_API_KEY", "")
    if not email or not key:
        return None
    token = base64.standard_b64encode(f"{email}:{key}".encode()).decode()
    return f"Basic {token}"


def _extract_address_parts(address: str) -> tuple[str, str]:
    """Return (street_with_number, outcode) from a full address string."""
    addr = address.replace("\n", ", ")

    # Extract outcode (e.g. N1, E8, N16)
    oc_match = re.search(r"\b([EN][1-9]\d?)\b", addr.upper())
    outcode = oc_match.group(1) if oc_match else ""

    # First line is typically "123 Street Name"
    lines = [l.strip() for l in addr.split(",") if l.strip()]
    street_line = lines[0] if lines else addr

    # Strip "Flat/Unit/Apt" prefix if present
    street_line = re.sub(
        r"^(?:Flat|Unit|Apt)\.?\s*\w+\s*,?\s*", "",
        street_line, flags=re.IGNORECASE
    ).strip()

    return street_line, outcode


def _query_epc(address_line: str, outcode: str) -> list[dict]:
    """Query EPC API and return rows, or [] on failure."""
    auth = _auth_header()
    if not auth:
        return []

    params = urllib.parse.urlencode({
        "address": address_line,
        "postcode": outcode,
        "size": 5,
    })
    url = f"{_EPC_API_BASE}?{params}"

    req = urllib.request.Request(url, headers={
        "Authorization": auth,
        "Accept": "application/json",
    })

    try:
        with urllib.request.urlopen(req, timeout=20) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        return data.get("rows", [])
    except urllib.error.HTTPError as e:
        if e.code == 401:
            print("    EPC API: authentication failed — check EPC_API_EMAIL / EPC_API_KEY")
        else:
            print(f"    EPC API error {e.code} for '{address_line}'")
        return []
    except Exception as e:
        print(f"    EPC API failed for '{address_line}': {e}")
        return []


def _pick_best_row(rows: list[dict]) -> Optional[dict]:
    """Return the most recent EPC certificate row that has a floor area."""
    candidates = [r for r in rows if r.get("total-floor-area")]
    if not candidates:
        return None
    # Sort by inspection-date descending; fall back to any if date missing
    def _date_key(r):
        try:
            return datetime.fromisoformat(r.get("inspection-date", "1900-01-01"))
        except ValueError:
            return datetime.min
    candidates.sort(key=_date_key, reverse=True)
    return candidates[0]


def enrich_epc(listing: dict) -> dict:
    """
    Look up EPC floor area for a listing. Adds:
      listing["epc_sqft"]          — surveyor-measured floor area in sqft (int)
      listing["epc_sqm"]           — same in m²
      listing["epc_date"]          — inspection date string
      listing["sqft_discrepancy"]  — True if OTM sqft > EPC sqft by >15%
    """
    if not _auth_header():
        return listing

    cache = _load_cache()
    global _cache_dirty

    address_line, outcode = _extract_address_parts(listing.get("address", ""))
    if not address_line or not outcode:
        return listing

    cache_key = f"{address_line.lower()}|{outcode.lower()}"

    # Check cache
    if cache_key in cache:
        entry = cache[cache_key]
        try:
            age = (datetime.now() - datetime.fromisoformat(entry.get("date", ""))).days
            if age <= EPC_CACHE_MAX_AGE_DAYS:
                _apply_cache_entry(listing, entry)
                return listing
        except (ValueError, TypeError):
            pass

    # Fetch from API
    rows = _query_epc(address_line, outcode)
    best = _pick_best_row(rows)

    if best:
        sqm = float(best["total-floor-area"])
        sqft = round(sqm * _SQM_TO_SQFT)
        epc_date = best.get("inspection-date", "")
        cache_entry = {
            "epc_sqft": sqft,
            "epc_sqm": round(sqm, 1),
            "epc_date": epc_date,
            "date": datetime.now().isoformat(),
        }
    else:
        # Cache the miss so we don't hammer the API on every run
        cache_entry = {"epc_sqft": None, "epc_sqm": None, "epc_date": None,
                       "date": datetime.now().isoformat()}

    cache[cache_key] = cache_entry
    _cache_dirty = True

    _apply_cache_entry(listing, cache_entry)
    return listing


def _apply_cache_entry(listing: dict, entry: dict) -> None:
    """Write cached EPC values onto the listing dict."""
    epc_sqft = entry.get("epc_sqft")
    if not epc_sqft:
        return

    listing["epc_sqft"] = epc_sqft
    listing["epc_sqm"] = entry.get("epc_sqm")
    listing["epc_date"] = entry.get("epc_date", "")

    # Flag discrepancy when OTM sqft is >15% larger than EPC (agent inflation)
    otm_sqft = listing.get("sqft")
    if otm_sqft and otm_sqft > epc_sqft * 1.15:
        listing["sqft_discrepancy"] = True

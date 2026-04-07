"""
land_registry.py — Street-level ppsf comps from Land Registry Price Paid Data

Fetches recent (3-5 year rolling) residential sales for a given street
from the Land Registry SPARQL endpoint, estimates sqft from property type,
and computes an average ppsf.

Results are cached in street_comp_cache.json (refreshed if older than 30 days).

Usage:
    from land_registry import enrich_street_comp
    enrich_street_comp(listing)  # adds listing["street_ppsf"]
"""

import json
import re
import ssl
import time
import urllib.request
import urllib.error
import urllib.parse
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional

try:
    import certifi
    _SSL_CTX = ssl.create_default_context(cafile=certifi.where())
except ImportError:
    _SSL_CTX = ssl.create_default_context()

BASE_DIR = Path(__file__).parent
CACHE_FILE = BASE_DIR / "street_comp_cache.json"
CACHE_MAX_AGE_DAYS = 30
REQUEST_DELAY = 1.0

_last_request: dict[str, float] = {}
_cache: dict = {}
_cache_dirty = False


def _load_cache() -> dict:
    global _cache
    if _cache:
        return _cache
    if CACHE_FILE.exists():
        try:
            _cache = json.loads(CACHE_FILE.read_text())
        except Exception:
            _cache = {}
    return _cache


def _save_cache() -> None:
    global _cache_dirty
    if _cache_dirty:
        CACHE_FILE.write_text(json.dumps(_cache, indent=2))
        _cache_dirty = False


def _rate_limit(domain: str, delay: float = REQUEST_DELAY) -> None:
    last = _last_request.get(domain, 0)
    wait = delay - (time.time() - last)
    if wait > 0:
        time.sleep(wait)
    _last_request[domain] = time.time()


def _extract_street_and_postcode(address: str) -> tuple[str, str]:
    addr = address.replace("\n", ", ")
    oc_match = re.search(r"\b([EN][1-9]\d?)\b", addr.upper())
    oc = oc_match.group(1) if oc_match else ""

    lines = [l.strip() for l in addr.split(",") if l.strip()]
    street_candidate = lines[0] if lines else addr

    street_candidate = re.sub(r"^\d+[a-zA-Z]?\s+", "", street_candidate).strip()
    street_candidate = re.sub(
        r"^(?:Flat|Unit|Apt)\.?\s*\w+\s*,?\s*", "",
        street_candidate, flags=re.IGNORECASE
    ).strip()

    if len(street_candidate.split()) < 2:
        if len(lines) > 1:
            street_candidate = lines[1].strip()
            street_candidate = re.sub(r"^\d+[a-zA-Z]?\s+", "", street_candidate).strip()

    return street_candidate, oc


def _query_land_registry(street: str, postcode_district: str,
                         years: int = 5) -> list[dict]:
    """Query Land Registry SPARQL for recent sales on a street.

    Filters on lrcommon:postcode using STRSTARTS (e.g. "N1 "),
    NOT on lrcommon:district (which contains local authority name).
    """
    cutoff = (datetime.now() - timedelta(days=years * 365)).strftime("%Y-%m-%d")

    street_lower = street.lower().replace("'", "\\'")
    pc_prefix = postcode_district.upper() + " "

    sparql = f"""
PREFIX lrppi: <http://landregistry.data.gov.uk/def/ppi/>
PREFIX lrcommon: <http://landregistry.data.gov.uk/def/common/>
PREFIX xsd: <http://www.w3.org/2001/XMLSchema#>

SELECT ?price ?date ?typeUri ?postcode WHERE {{
  ?trans lrppi:pricePaid ?price ;
         lrppi:transactionDate ?date ;
         lrppi:propertyType ?typeUri ;
         lrppi:propertyAddress ?addr .
  ?addr lrcommon:street ?street ;
        lrcommon:postcode ?postcode .
  FILTER(LCASE(STR(?street)) = "{street_lower}")
  FILTER(STRSTARTS(STR(?postcode), "{pc_prefix}"))
  FILTER(?date >= "{cutoff}"^^xsd:date)
}}
ORDER BY DESC(?date)
LIMIT 100
"""

    url = "https://landregistry.data.gov.uk/landregistry/query"
    params = urllib.parse.urlencode({"query": sparql, "output": "json"})
    full_url = f"{url}?{params}"

    headers = {
        "Accept": "application/sparql-results+json",
        "User-Agent": "PropertyMonitor/3.4 (personal use)",
    }

    for attempt in range(3):
        _rate_limit("landregistry.data.gov.uk", delay=1.0 + attempt * 1.5)
        req = urllib.request.Request(full_url, headers=headers)
        try:
            with urllib.request.urlopen(req, timeout=20, context=_SSL_CTX) as resp:
                data = json.loads(resp.read().decode("utf-8"))
            bindings = data.get("results", {}).get("bindings", [])
            results = []
            for b in bindings:
                try:
                    price = int(float(b["price"]["value"]))
                    date = b["date"]["value"]
                    type_uri = b.get("typeUri", {}).get("value", "")
                    prop_type = type_uri.rsplit("/", 1)[-1] if "/" in type_uri else "other"
                    postcode = b.get("postcode", {}).get("value", "")
                    results.append({
                        "price": price, "date": date,
                        "type": prop_type, "postcode": postcode
                    })
                except (KeyError, ValueError):
                    pass
            return results
        except urllib.error.HTTPError as e:
            if e.code == 429 and attempt < 2:
                wait = 5 * (attempt + 1)
                print(f"    429 rate limit, waiting {wait}s (attempt {attempt+1}/3)")
                time.sleep(wait)
                continue
            print(f"    Land Registry SPARQL failed for '{street}': HTTP {e.code}")
            return []
        except Exception as e:
            print(f"    Land Registry SPARQL failed for '{street}': {e}")
            return []
    return []  # all retries exhausted


def _compute_street_ppsf(sales: list[dict], sqft_estimates: dict) -> Optional[int]:
    ppsf_values = []
    for i, sale in enumerate(sales):
        sqft = sqft_estimates.get(i)
        if sqft and sqft > 0 and sale["price"] > 0:
            ppsf = sale["price"] / sqft
            if 300 < ppsf < 3000:
                ppsf_values.append(ppsf)

    if len(ppsf_values) < 2:
        return None

    ppsf_values.sort()
    n = len(ppsf_values)
    trim = max(1, n // 10)
    trimmed = ppsf_values[trim:-trim] if n > 4 else ppsf_values
    return round(sum(trimmed) / len(trimmed))


def _estimate_sqft(prop_type: str, beds: int = 3) -> float:
    terraced = {3: 1050, 4: 1300, 5: 1550}
    semi = {3: 1100, 4: 1400, 5: 1700}
    detached = {3: 1200, 4: 1600, 5: 2000}

    t = prop_type.lower()
    if "terraced" in t:
        return terraced.get(beds, 1200)
    elif "semi" in t:
        return semi.get(beds, 1300)
    elif "detached" in t and "semi" not in t:
        return detached.get(beds, 1600)
    return 1200


def get_street_ppsf(listing: dict) -> Optional[int]:
    cache = _load_cache()
    address = listing.get("address", "")
    street, outcode = _extract_street_and_postcode(address)
    if not street or not outcode:
        return None

    cache_key = f"{street.lower()}|{outcode.lower()}"

    if cache_key in cache:
        entry = cache[cache_key]
        cached_date = entry.get("date", "")
        try:
            age = (datetime.now() - datetime.fromisoformat(cached_date)).days
            if age <= CACHE_MAX_AGE_DAYS:
                return entry.get("ppsf")
        except ValueError:
            pass

    sales = _query_land_registry(street, outcode)
    global _cache_dirty

    if not sales:
        cache[cache_key] = {"ppsf": None, "date": datetime.now().isoformat(),
                             "sales_count": 0}
        _cache_dirty = True
        return None

    house_sales = [s for s in sales if "flat" not in s.get("type", "").lower()]
    if not house_sales:
        house_sales = sales

    sqft_estimates = {}
    for i, sale in enumerate(house_sales):
        sqft_estimates[i] = _estimate_sqft(sale.get("type", "terraced"), beds=3)

    ppsf = _compute_street_ppsf(house_sales, sqft_estimates)

    cache[cache_key] = {
        "ppsf": ppsf,
        "date": datetime.now().isoformat(),
        "sales_count": len(house_sales),
        "street": street,
        "outcode": outcode,
    }
    _cache_dirty = True
    return ppsf


def enrich_street_comp(listing: dict) -> dict:
    try:
        ppsf = get_street_ppsf(listing)
        listing["street_ppsf"] = ppsf
    except Exception as e:
        print(f"    Street comp failed for {listing.get('address','')[:40]}: {e}")
        listing["street_ppsf"] = None
    return listing


def enrich_all_street_comps(listings: list[dict], quiet: bool = False) -> None:
    if not quiet:
        print(f"\nPhase: Street comp (Land Registry) for {len(listings)} listings...")

    street_results: dict[str, Optional[int]] = {}

    for i, listing in enumerate(listings):
        addr = listing.get("address", "").replace("\n", ", ")[:40]
        street, outcode = _extract_street_and_postcode(listing.get("address", ""))
        cache_key = f"{street.lower()}|{outcode.lower()}" if street and outcode else ""

        if cache_key and cache_key in street_results:
            listing["street_ppsf"] = street_results[cache_key]
            if not quiet:
                print(f"  [{i+1}/{len(listings)}] {addr} (deduped)")
            continue

        if not quiet:
            print(f"  [{i+1}/{len(listings)}] {addr}")
        enrich_street_comp(listing)

        if cache_key:
            street_results[cache_key] = listing.get("street_ppsf")

    _save_cache()

    found = sum(1 for l in listings if l.get("street_ppsf"))
    if not quiet:
        print(f"  Street comp: {found}/{len(listings)} with data")

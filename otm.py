# otm.py — OnTheMarket scraper
#
# Search results: get listing IDs, addresses, prices, beds, lat/lng, features.
# Detail pages: get sq ft, tenure, full description, floorplans.

import json
import re
import urllib.parse
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional
from fetch import get
from config import OTM_LOCATIONS, MIN_BEDROOMS, MAX_PRICE, MIN_PRICE, REQUEST_DELAY, DETAIL_CACHE_FILE, DETAIL_CACHE_MAX_AGE_DAYS

# Detail page cache — avoids re-fetching sqft/description for known listings
_detail_cache: dict = {}
_detail_cache_dirty = False
_DETAIL_CACHE_PATH = Path(DETAIL_CACHE_FILE)

def _load_detail_cache() -> dict:
    global _detail_cache
    if _detail_cache:
        return _detail_cache
    if _DETAIL_CACHE_PATH.exists():
        try:
            _detail_cache = json.loads(_DETAIL_CACHE_PATH.read_text())
        except Exception:
            _detail_cache = {}
    return _detail_cache

def _save_detail_cache() -> None:
    global _detail_cache_dirty
    if _detail_cache_dirty:
        _DETAIL_CACHE_PATH.write_text(json.dumps(_detail_cache, indent=2, ensure_ascii=True))
        _detail_cache_dirty = False


def _parse_price(s: str) -> int:
    if not s:
        return 0
    clean = s.replace("£", "").replace(",", "").strip()
    try:
        if "m" in clean.lower():
            return int(float(clean.lower().replace("m", "")) * 1_000_000)
        return int(clean)
    except (ValueError, TypeError):
        return 0


MAX_PAGES_PER_LOCATION = 5


def _parse_page(html: str, seen_ids: set) -> list[dict]:
    listings = []
    for script in re.findall(r'<script[^>]*>(.*?)</script>', html, re.DOTALL):
        if len(script) < 5000 or 'initialReduxState' not in script:
            continue
        jm = re.search(r'(\{.*\})', script, re.DOTALL)
        if not jm:
            continue
        try:
            data = json.loads(jm.group(1))
        except json.JSONDecodeError:
            continue

        items = (data.get("props", {})
                 .get("initialReduxState", {})
                 .get("results", {})
                 .get("list", []))

        for item in items:
            lid = str(item.get("id", ""))
            if not lid or lid in seen_ids:
                continue
            seen_ids.add(lid)

            features_raw = item.get("features", [])
            features = []
            for f in features_raw:
                if isinstance(f, str):
                    features.append(f)
                elif isinstance(f, dict):
                    features.append(f.get("feature", ""))

            tenure = ""
            for f in features:
                fl = f.lower()
                if "freehold" in fl:
                    tenure = "freehold"
                elif "leasehold" in fl:
                    tenure = "leasehold"

            loc = item.get("location", {})
            images = item.get("images", [])
            img_url = ""
            if images and isinstance(images[0], dict):
                img_url = images[0].get("default", "")

            listing = {
                "id": lid,
                "address": item.get("address", ""),
                "price": _parse_price(item.get("price", "") or item.get("short-price", "")),
                "price_display": item.get("short-price", ""),
                "bedrooms": int(item.get("bedrooms", 0) or 0),
                "bathrooms": int(item.get("bathrooms", 0) or 0),
                "property_type": item.get("humanised-property-type", ""),
                "features": features,
                "tenure": tenure,
                "lat": float(loc.get("lat", 0) or 0),
                "lng": float(loc.get("lon", loc.get("lng", 0)) or 0),
                "url": f"https://www.onthemarket.com/details/{lid}/",
                "agent": (item.get("agent", {}) or {}).get("name", ""),
                "image_url": img_url,
                "days_label": item.get("days-since-added-reduced", ""),
                "sqft": None,
                "sqm": None,
                "description": "",
                "floorplan_url": "",
            }
            listings.append(listing)

    return listings


def search() -> list[dict]:
    all_listings = []
    seen_ids = set()

    for location in OTM_LOCATIONS:
        base_params = {
            "min-bedrooms": str(MIN_BEDROOMS),
            "max-price": str(MAX_PRICE),
            "min-price": str(MIN_PRICE),
        }

        for page in range(MAX_PAGES_PER_LOCATION):
            params = {**base_params}
            if page > 0:
                params["page"] = str(page + 1)
            qs = urllib.parse.urlencode(params)
            url = f"https://www.onthemarket.com/for-sale/houses/{location}/?{qs}"

            html = get(url)
            if not html:
                break

            before = len(seen_ids)
            page_listings = _parse_page(html, seen_ids)
            all_listings.extend(page_listings)

            if len(seen_ids) == before:
                break

            print(f"    [{location}] page {page + 1}: {len(page_listings)} listings")

    print(f"  [OTM] {len(all_listings)} listings total from search")
    return all_listings


_DETAIL_FIELDS = ("sqft", "sqm", "description", "floorplan_url", "features", "tenure")

def enrich_detail(listing: dict) -> dict:
    cache = _load_detail_cache()
    lid = listing["id"]
    global _detail_cache_dirty

    # Check cache
    if lid in cache:
        entry = cache[lid]
        cached_date = entry.get("_cached", "")
        try:
            age = (datetime.now() - datetime.fromisoformat(cached_date)).days
            if age <= DETAIL_CACHE_MAX_AGE_DAYS:
                for k in _DETAIL_FIELDS:
                    if k in entry and k != "features":
                        listing[k] = entry[k]
                    elif k == "features" and k in entry:
                        for f in entry[k]:
                            if f not in listing["features"]:
                                listing["features"].append(f)
                return listing
        except (ValueError, TypeError):
            pass

    url = listing["url"]
    html = get(url, delay=REQUEST_DELAY)
    if not html:
        return listing

    for script in re.findall(r'<script[^>]*>(.*?)</script>', html, re.DOTALL):
        if len(script) < 5000 or 'initialReduxState' not in script:
            continue
        jm = re.search(r'(\{.*\})', script, re.DOTALL)
        if not jm:
            continue
        try:
            data = json.loads(jm.group(1))
        except json.JSONDecodeError:
            continue

        prop = (data.get("props", {})
                .get("initialReduxState", {})
                .get("property", {}))
        if not prop:
            continue

        sqft = prop.get("minimumAreaSqFt")
        if sqft:
            listing["sqft"] = int(sqft)
            listing["sqm"] = prop.get("minimumAreaSqM")

        desc = prop.get("description", "")
        if isinstance(desc, str):
            listing["description"] = desc

        fps = prop.get("floorplans", [])
        if fps and isinstance(fps[0], dict):
            listing["floorplan_url"] = fps[0].get("largeUrl", fps[0].get("original", ""))

        detail_features = prop.get("features", [])
        if detail_features:
            for f in detail_features:
                feat_str = f.get("feature", "") if isinstance(f, dict) else str(f)
                if feat_str and feat_str not in listing["features"]:
                    listing["features"].append(feat_str)

        if not listing["tenure"]:
            for ki in prop.get("keyInfo", []):
                if isinstance(ki, dict) and ki.get("title", "").lower() == "tenure":
                    desc_text = ki.get("description", "").lower()
                    if "freehold" in desc_text:
                        listing["tenure"] = "freehold"
                    elif "leasehold" in desc_text:
                        listing["tenure"] = "leasehold"

        break

    if not listing["sqft"]:
        m = re.findall(r'([\d,]+)\s*(?:sq\.?\s*ft|sqft)', html, re.IGNORECASE)
        if m:
            from collections import Counter
            counts = Counter(int(x.replace(",", "")) for x in m)
            listing["sqft"] = counts.most_common(1)[0][0]

    # Only cache if we extracted something useful — don't cache empty results
    # (e.g. OTM redirect pages) which would block retries for 7 days.
    if listing.get("sqft") or listing.get("description") or listing.get("floorplan_url"):
        cache[lid] = {k: listing.get(k) for k in _DETAIL_FIELDS}
        cache[lid]["_cached"] = datetime.now().isoformat()
        _detail_cache_dirty = True

    return listing


def prune_detail_cache(max_age_days: int = DETAIL_CACHE_MAX_AGE_DAYS) -> int:
    """Remove cache entries older than max_age_days. Returns count removed."""
    cache = _load_detail_cache()
    global _detail_cache_dirty
    cutoff = datetime.now()
    to_delete = []
    for lid, entry in cache.items():
        cached_date = entry.get("_cached", "")
        try:
            age = (cutoff - datetime.fromisoformat(cached_date)).days
            if age > max_age_days:
                to_delete.append(lid)
        except (ValueError, TypeError):
            to_delete.append(lid)  # malformed entry — remove it
    for lid in to_delete:
        del cache[lid]
    if to_delete:
        _detail_cache_dirty = True
    return len(to_delete)


def save_detail_cache() -> None:
    """Call after all detail enrichment is done."""
    _save_detail_cache()

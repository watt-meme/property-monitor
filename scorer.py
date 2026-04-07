# scorer.py — Weighted scoring system v3.4
#
# Produces a 0-100 score based on buyer preferences.
# Hard filters (leasehold, keywords, flat types) return score = -1 (excluded).
# Traffic roads apply penalty (not hard exclude).
# v3.4: Layout dedup by concept group, AI kitchen penalty, dead code cleanup.

import re
from config import (
    VFM_MAX, VFM_NO_SQFT,
    BEDS_ABOVE_GROUND_SCORE,
    PERIOD_SCORE, PERIOD_DEFAULT, PERIOD_MODERN,
    STYLE_BONUS, STYLE_PENALTY,
    GARDEN_KEYWORDS,
    LOCATION_SCORE, LOCATION_ZONES, LOCATION_FALLBACK,
    LAYOUT_NEGATIVE,
    TRAFFIC_ROAD_PENALTIES, EXCLUDE_KEYWORDS,
    POSTWAR_STYLE_PENALTIES, POSTWAR_STREET_SUFFIXES, POSTWAR_STREET_SUFFIX_PENALTY,
    AREA_BENCHMARKS,
    CONDITION_HEAVY_RENO_KEYWORDS, CONDITION_NEEDS_WORK_KEYWORDS,
    CONDITION_GOOD_KEYWORDS,
    CONDITION_PENALTY_PRICE_THRESHOLD,
    CONDITION_HEAVY_RENO_PENALTY, CONDITION_NEEDS_WORK_PENALTY,
    CONDITION_GOOD_BONUS,
    FORCE_EXCLUDE, FORCE_ALLOW, SCORE_CAP,
)


def _outcode(address: str) -> str:
    m = re.search(r"\b([EN]\d{1,2})\b", address.upper())
    return m.group(1) if m else ""


def _normalise_address(address: str) -> str:
    """Normalise address for dedup. Strip whitespace, commas, 'London', postcode suffixes."""
    a = address.lower().strip()
    for suffix in [", london", ", greater london", "\nlondon"]:
        a = a.replace(suffix, "")
    a = re.sub(r"\b[ens]w?\d{1,2}\s*\d[a-z]{2}\b", "", a)  # strip full postcode
    a = re.sub(r"\s+", " ", a).strip(", \n")
    return a


def _get_location(lat: float, lng: float, address: str) -> tuple[str, str]:
    """Returns (area_label, quality). quality in premium/good/acceptable/fringe/unknown."""
    if lat and lng:
        for (s, n, w, e), label, quality in LOCATION_ZONES:
            if s <= lat <= n and w <= lng <= e:
                return label, quality

    oc = _outcode(address)
    if oc in LOCATION_FALLBACK:
        return LOCATION_FALLBACK[oc]

    return "", "unknown"


def _detect_period(text: str) -> str:
    """Detect property period from combined text. Returns period key or ''."""
    t = text.lower()

    # Check for modern indicators first (broad set)
    for kw in [
        "new build", "newly built", "contemporary home", "modern house",
        "purpose built", "modern townhouse", "modern terrace",
        "newly constructed", "brand new", "just completed",
        "new development", "show home", "plot ",
        "built by", "developed by",
        # Additional modern signals (v3.2)
        "new homes", "new home", "newly developed",
        "built in 20",  # "built in 2018" etc.
        "completed in 20",
        "high specification new", "bespoke new",
        "architect designed",  # not exclusively modern but worth flagging
        "open plan kitchen",  # often modern but keep as weak signal only
    ]:
        # 'open plan kitchen' alone is not sufficient
        if kw == "open plan kitchen":
            continue  # don't use as a period signal
        if kw in t:
            return "modern"

    # Georgian (strongest signal)
    if any(kw in t for kw in ["georgian", "regency"]):
        return "georgian"

    # Grade II
    if "grade ii listed" in t or "grade 2 listed" in t:
        return "grade ii listed"
    if "grade ii" in t or "grade 2" in t:
        return "grade ii"

    # Early Victorian (pre-1860, often stucco fronted, closer to Georgian in style)
    if "early victorian" in t:
        return "early victorian"

    # Stucco-fronted Victorian (more Georgian in character)
    if "victorian" in t and ("stucco" in t):
        return "victorian_stucco"

    # Victorian
    if "late victorian" in t:
        return "late victorian"
    if "victorian" in t:
        return "victorian"

    # Edwardian
    if "edwardian" in t:
        return "edwardian"

    # Generic period
    if "period" in t and any(kw in t for kw in [
        "period home", "period house", "period property",
        "period features", "period conversion", "period terrace"
    ]):
        return "period"

    return ""


def _count_above_ground_beds(listing: dict) -> int:
    """Estimate above-ground bedrooms from total beds and basement indicators."""
    total_beds = listing.get("bedrooms", 0)
    combined = (
        " ".join(listing.get("features", [])).lower() + " " +
        listing.get("description", "").lower()
    )

    basement_beds = 0
    # Count explicit basement/LG bedroom mentions
    for pattern in [
        r"(\d)\s*(?:bed(?:room)?s?\s+(?:in|on)\s+(?:the\s+)?(?:basement|lower ground))",
        r"(?:basement|lower ground)\s+(?:floor\s+)?(?:has|with|offers?)\s+(\d)\s*bed",
        r"(\d)\s*(?:bed(?:room)?s?)\s+(?:on|in)\s+(?:the\s+)?(?:lower|basement)",
    ]:
        m = re.search(pattern, combined)
        if m:
            basement_beds = max(basement_beds, int(m.group(1)))

    # Heuristic: if "bedroom" and "lower ground"/"basement" mentioned together
    if basement_beds == 0:
        bed_near_lg = any(kw in combined for kw in [
            "lower ground bedroom", "basement bedroom",
            "bedroom on lower", "bedroom in basement",
            "bedroom on the lower", "bedroom in the basement",
            "lower ground floor bedroom",
            "two bedrooms on the lower", "two bedrooms in the basement",
        ])
        if bed_near_lg:
            if any(kw in combined for kw in [
                "two bedrooms on the lower", "two bedrooms in the basement",
                "2 bedrooms on the lower", "2 bedrooms in the basement",
                "two bed lower ground", "2 bed lower ground",
            ]):
                basement_beds = 2
            else:
                basement_beds = 1

    above_ground = max(0, total_beds - basement_beds)
    return above_ground


def _detect_condition(combined: str, price: int) -> tuple[str, int]:
    """Detect condition and return (label, score_modifier)."""
    for kw in CONDITION_GOOD_KEYWORDS:
        if kw in combined:
            return "good", CONDITION_GOOD_BONUS

    for kw in CONDITION_HEAVY_RENO_KEYWORDS:
        if kw in combined:
            if price >= CONDITION_PENALTY_PRICE_THRESHOLD:
                return "heavy_reno", CONDITION_HEAVY_RENO_PENALTY
            else:
                return "heavy_reno", CONDITION_HEAVY_RENO_PENALTY // 2

    for kw in CONDITION_NEEDS_WORK_KEYWORDS:
        if kw in combined:
            if price >= CONDITION_PENALTY_PRICE_THRESHOLD:
                return "needs_work", CONDITION_NEEDS_WORK_PENALTY
            else:
                return "needs_work", 0
    return "unknown", 0


def score_property(listing: dict) -> dict:
    """Score a listing. Returns listing with score, breakdown, excluded, area_label."""
    address = listing.get("address", "")
    address_lower = address.lower()
    features_text = " ".join(listing.get("features", []))
    description = listing.get("description", "")
    prop_type = listing.get("property_type", "")
    combined = f"{address_lower} {features_text.lower()} {description.lower()} {prop_type.lower()}"

    breakdown = {}
    excluded = False
    exclude_reason = ""

    # ===== HARD FILTERS =====

    for pattern, reason in FORCE_EXCLUDE.items():
        if pattern in address_lower:
            excluded = True
            exclude_reason = reason
            break

    force_allowed = False
    if not excluded:
        for pattern in FORCE_ALLOW:
            if pattern in address_lower:
                force_allowed = True
                break

    if not excluded and not force_allowed:
        if listing.get("tenure") == "leasehold":
            excluded = True
            exclude_reason = "Leasehold"

    if not excluded and not force_allowed:
        for road, penalty in TRAFFIC_ROAD_PENALTIES.items():
            if road in address_lower:
                listing["traffic_road"] = road
                listing["traffic_road_penalty"] = penalty
                break

    if not excluded and not force_allowed:
        for kw in EXCLUDE_KEYWORDS:
            if kw in combined:
                excluded = True
                exclude_reason = f"Excluded: {kw}"
                break

    if not excluded and not force_allowed:
        type_lower = prop_type.lower()
        if any(t in type_lower for t in ["flat", "maisonette", "apartment"]):
            excluded = True
            exclude_reason = f"Property type: {prop_type}"

    if excluded:
        listing["score"] = -1
        listing["score_breakdown"] = {"excluded": exclude_reason}
        listing["excluded"] = True
        listing["exclude_reason"] = exclude_reason
        listing["area_label"], _ = _get_location(
            listing.get("lat", 0), listing.get("lng", 0), address)
        return listing

    # ===== VFM (0-25) =====
    sqft = listing.get("sqft")
    price = listing.get("price", 0)
    ppsf = None

    if sqft and sqft > 0 and price > 0:
        ppsf = round(price / sqft)
        listing["ppsf"] = ppsf

        oc = _outcode(address)
        bench = AREA_BENCHMARKS.get(oc)
        if bench:
            floor_val = bench["floor"]
            ceiling_val = bench["ceiling"]
            if ppsf <= floor_val:
                vfm = VFM_MAX
            elif ppsf >= ceiling_val:
                vfm = 0
            else:
                vfm = round(VFM_MAX * (ceiling_val - ppsf) / (ceiling_val - floor_val))
        else:
            vfm = VFM_NO_SQFT
    else:
        vfm = VFM_NO_SQFT

    breakdown["vfm"] = vfm

    # ===== BEDROOMS (0-20) =====
    above_ground = _count_above_ground_beds(listing)
    total_beds = listing.get("bedrooms", 0)
    beds_score = BEDS_ABOVE_GROUND_SCORE.get(above_ground, 0)

    if above_ground == total_beds:
        beds_score = BEDS_ABOVE_GROUND_SCORE.get(total_beds, 0)

    listing["above_ground_beds"] = above_ground
    breakdown["beds"] = beds_score

    # ===== PERIOD (0-20) =====
    period_key = _detect_period(combined)
    if period_key == "modern":
        period_score = PERIOD_MODERN
    elif period_key:
        period_score = PERIOD_SCORE.get(period_key, PERIOD_DEFAULT)
    else:
        # No period detected: could be genuinely modern or just unspecified.
        # Apply postwar check: if postwar signals present, treat as modern (0 pts).
        _postwar_signals = any(kw in combined for kw in POSTWAR_STYLE_PENALTIES)
        period_score = PERIOD_MODERN if _postwar_signals else PERIOD_DEFAULT
    breakdown["period"] = period_score
    listing["period"] = period_key or "unknown"

    # Style modifiers
    style_mod = 0
    for kw, pts in STYLE_BONUS.items():
        if kw in combined:
            style_mod += pts
    for kw, pts in STYLE_PENALTY.items():
        if kw in combined:
            style_mod += pts
    style_mod = max(-5, min(5, style_mod))
    if style_mod != 0:
        breakdown["style"] = style_mod

    # ===== GARDEN (0-10) =====
    garden_score = 0
    for kw, pts in sorted(GARDEN_KEYWORDS.items(), key=lambda x: -x[1]):
        if kw in combined:
            garden_score = max(garden_score, pts)
    breakdown["garden"] = garden_score

    # ===== LOCATION (0-20) =====
    area_label, quality = _get_location(
        listing.get("lat", 0), listing.get("lng", 0), address)
    loc_score = LOCATION_SCORE.get(quality, 0)
    breakdown["location"] = loc_score
    listing["area_label"] = area_label
    listing["location_quality"] = quality

    # ===== LAYOUT (+10 to -20) =====
    # Group by concept to avoid double-counting synonyms
    _LAYOUT_POS_GROUPS = {
        "double_front": {"double fronted": 5, "double-fronted": 5},
        "through_reception": {"through reception": 4, "through lounge": 4, "through sitting": 4},
        "double_reception": {"double reception": 3},
        "ceilings": {"high ceilings": 3, "tall ceilings": 3, "ceiling height": 3},
        "period_features": {"period features": 3, "original features": 3},
        "fireplaces": {"fireplaces": 2, "fireplace": 2, "marble fireplace": 3},
        "cornicing": {"cornicing": 2},
        "sash_windows": {"sash windows": 2},
        "shutters": {"shutters": 2},
        "cellar": {"cellar": 2, "wine cellar": 2},
        "bay_window": {"bay window": 2},
        "floors": {"original floorboards": 2, "wooden floors": 1},
        "panelled_doors": {"panelled doors": 1},
        "dado_rail": {"dado rail": 1},
    }
    layout_score = 0
    layout_notes = []
    for group_name, keywords in _LAYOUT_POS_GROUPS.items():
        best_pts = 0
        best_kw = ""
        for kw, pts in keywords.items():
            if kw in combined and pts > best_pts:
                best_pts = pts
                best_kw = kw
        if best_pts > 0:
            layout_score += best_pts
            layout_notes.append(f"+{best_pts} {best_kw}")
    for kw, pts in LAYOUT_NEGATIVE.items():
        if kw in combined:
            layout_score += pts
            layout_notes.append(f"{pts} {kw}")
    layout_score = max(-20, min(10, layout_score))
    breakdown["layout"] = layout_score
    if layout_notes:
        listing["layout_notes"] = layout_notes

    # ===== CONDITION (bonus +5 to penalty -12) =====
    condition_label, condition_mod = _detect_condition(combined, price)
    listing["condition"] = condition_label
    if condition_mod != 0:
        breakdown["condition"] = condition_mod

    # ===== AI LAYOUT PENALTY (from floorplan analysis) =====
    ai_penalty = 0
    fp_ai = listing.get("floorplan_ai", {})
    if fp_ai and isinstance(fp_ai, dict):
        kitchen_mod = fp_ai.get("kitchen_mod_difficulty", "")
        if kitchen_mod == "hard":
            ai_penalty -= 8  # kitchen on different floor
        elif kitchen_mod == "moderate":
            ai_penalty -= 3
        if fp_ai.get("main_bed_adequate") is False:
            ai_penalty -= 5
        circ = fp_ai.get("circulation_pct", 0)
        if isinstance(circ, (int, float)) and circ > 25:
            ai_penalty -= 3
    if ai_penalty:
        breakdown["ai_layout"] = ai_penalty

    # ===== TRAFFIC ROAD PENALTY =====
    traffic_penalty = listing.get("traffic_road_penalty", 0)
    if traffic_penalty:
        breakdown["traffic"] = traffic_penalty

    # ===== POST-WAR STYLE PENALTIES =====
    # Only apply if no period keywords detected (don't double-penalise genuine period homes)
    postwar_penalty = 0
    postwar_flags = []
    if period_key not in ("georgian", "regency", "grade ii listed", "grade ii",
                          "early victorian", "victorian_stucco", "victorian",
                          "late victorian", "edwardian"):
        for kw, pts in POSTWAR_STYLE_PENALTIES.items():
            if kw in combined:
                postwar_penalty += pts
                postwar_flags.append(kw)
        # Street name suffix check (address only, not combined)
        addr_lower_stripped = address_lower.split(",")[0]  # just the street part
        for suffix in POSTWAR_STREET_SUFFIXES:
            if addr_lower_stripped.endswith(suffix):
                postwar_penalty += POSTWAR_STREET_SUFFIX_PENALTY
                postwar_flags.append(f"street suffix '{suffix.strip()}'")
                break
    if postwar_penalty:
        breakdown["postwar"] = postwar_penalty
        listing["postwar_flags"] = postwar_flags

    # ===== TOTAL =====
    total = (vfm + beds_score + period_score + style_mod +
             garden_score + loc_score + layout_score + condition_mod +
             ai_penalty + traffic_penalty + postwar_penalty)
    total = max(0, min(100, total))

    # --- Apply SCORE_CAP overrides ---
    for pattern, cap in SCORE_CAP.items():
        if pattern in address_lower:
            if total > cap:
                total = cap
                breakdown["_capped"] = f"Score capped at {cap} for {pattern}"
            break

    listing["score"] = total
    listing["score_breakdown"] = breakdown
    listing["excluded"] = False

    return listing


def dedup_listings(listings: list[dict]) -> list[dict]:
    """Remove duplicate listings (same property listed by multiple agents)."""
    seen_addresses = {}
    deduped = []

    for listing in listings:
        norm_addr = _normalise_address(listing.get("address", ""))
        if not norm_addr:
            deduped.append(listing)
            continue

        if norm_addr in seen_addresses:
            existing = seen_addresses[norm_addr]
            existing_sqft = existing.get("sqft") or 0
            new_sqft = listing.get("sqft") or 0
            if new_sqft > existing_sqft:
                deduped = [l for l in deduped if _normalise_address(l.get("address", "")) != norm_addr]
                deduped.append(listing)
                seen_addresses[norm_addr] = listing
        else:
            seen_addresses[norm_addr] = listing
            deduped.append(listing)

    return deduped


def score_all(listings: list[dict]) -> tuple[list[dict], list[dict]]:
    """Score all listings, return (scored, excluded) sorted by score desc."""
    listings = dedup_listings(listings)

    scored = []
    excluded = []

    for listing in listings:
        result = score_property(listing)
        if result["excluded"]:
            excluded.append(result)
        else:
            scored.append(result)

    scored.sort(key=lambda x: x["score"], reverse=True)
    return scored, excluded

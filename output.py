# output.py — Generate scored output HTML v4.1
#
# Architecture: Python builds data + injects into template.html.
# No f-string HTML/JS. Edit template.html and app.js directly.
#
# Files:
#   template.html  — HTML + CSS structure, __PLACEHOLDER__ tokens
#   app.js         — all JavaScript, plain text, no escaping
#   output.py      — this file: data prep + token replacement

import os
import re
import json
import urllib.parse
from datetime import datetime
from config import ALERTS_DIR

_DIR = os.path.dirname(os.path.abspath(__file__))


def _ensure_dir():
    os.makedirs(ALERTS_DIR, exist_ok=True)


# -- Colour helpers -----------------------------------------------------------

def _score_colour(score: int) -> str:
    if score >= 70: return "#c9a84c"
    elif score >= 50: return "#5b8dd9"
    elif score >= 30: return "#e08c40"
    return "#5a5652"


def _ppsf_colour(ppsf: int) -> str:
    if ppsf > 1100: return "#e05252"
    elif ppsf > 950: return "#e08c40"
    elif ppsf > 850: return "#c9a84c"
    return "#4caf82"


def _period_label(period: str) -> str:
    return period.replace("_", " ").title() if period and period != "unknown" else ""


def _period_colour(period: str) -> str:
    return {
        "georgian": "#5c3d8f", "regency": "#5c3d8f",
        "grade ii listed": "#5c3d8f", "grade ii": "#6b4aa0",
        "early victorian": "#3a4a8a", "victorian_stucco": "#3a4a8a",
        "victorian": "#2a5a7a", "late victorian": "#2a5a7a",
        "edwardian": "#1a6060", "period": "#3a4a5a",
        "modern": "#2a2a2a",
    }.get(period, "#2a2a2a")


def _compact_address(address: str) -> str:
    addr = address
    for suffix in [", London", ", Greater London", "\nLondon"]:
        addr = addr.replace(suffix, "")
    return addr.replace("\n", ", ").strip(", ")


def _rightmove_url(address: str) -> str:
    clean = _compact_address(address)
    return f"https://www.rightmove.co.uk/house-prices/{urllib.parse.quote(clean)}.html"


def _parse_days_number(days_label: str) -> int:
    if not days_label: return 999
    dl = days_label.lower()
    if "today" in dl: return 0
    if "yesterday" in dl: return 1
    m = re.search(r"(\d+)\s*day", dl)
    if m: return int(m.group(1))
    m = re.search(r"(\d+)\s*week", dl)
    if m: return int(m.group(1)) * 7
    m = re.search(r"(\d+)\s*month", dl)
    if m: return int(m.group(1)) * 30
    return 999


# -- Opportunity score --------------------------------------------------------

def _opportunity_score(listing: dict) -> int:
    """Composite score: fit x days_factor x price_factor. Capped 100."""
    fit = listing.get("score", 0)
    if fit <= 0:
        return 0
    ph      = listing.get("price_history_meta", {})
    days    = _parse_days_number(listing.get("days_label", ""))
    reduced = ph.get("is_reduced", False)
    days_factor  = 1.0 + min(0.15, (days - 21) * 0.005) if not reduced and days >= 21 else 1.0
    ppsf         = listing.get("ppsf", 0)
    street_ppsf  = listing.get("street_ppsf", 0)
    price_factor = max(0.85, min(1.20, street_ppsf / ppsf)) if ppsf and street_ppsf else 1.0
    return min(100, round(fit * days_factor * price_factor))


# -- Breakdown tooltip --------------------------------------------------------

def _build_breakdown_tooltip(listing: dict) -> str:
    breakdown = listing.get("score_breakdown", {})
    labels = {
        "vfm":       ("VFM",         "£/sqft value vs area benchmark"),
        "beds":      ("Bedrooms",    "above-ground bedrooms"),
        "period":    ("Period",      "architectural era"),
        "style":     ("Style",       "style bonus/penalty"),
        "garden":    ("Garden",      "outdoor space quality"),
        "location":  ("Location",    "micro-zone quality"),
        "layout":    ("Layout",      "period features & proportions"),
        "condition": ("Condition",   "presentation / renovation need"),
        "ai_layout": ("AI layout",   "floorplan AI penalty"),
        "traffic":   ("Traffic road", "road noise penalty"),
        "postwar":   ("Post-war",    "style penalty"),
    }
    parts = []
    for key, val in breakdown.items():
        if key.startswith("_") or not isinstance(val, (int, float)) or val == 0:
            continue
        label, desc = labels.get(key, (key.title(), ""))
        sign = "+" if val > 0 else ""
        parts.append(f"{label}: {sign}{val} ({desc})")
    return " | ".join(parts)


# -- AI prose -----------------------------------------------------------------

def _build_ai_prose(listing: dict) -> dict:
    """Return {prose, headline_sev, flags} for the AI assessment block."""
    fp_ai = listing.get("floorplan_ai", {})
    if not fp_ai or not fp_ai.get("summary"):
        return {}

    parts    = []
    flags    = []
    sev_rank = {"good": 0, "info": 1, "warn": 2}
    verdict  = fp_ai.get("verdict", "")
    worst    = {"strong": "good", "good": "good", "mixed": "info", "weak": "warn"}.get(verdict, "info")

    def add_flag(text, sev):
        nonlocal worst
        flags.append({"text": text, "sev": sev})
        if sev_rank[sev] > sev_rank[worst]:
            worst = sev

    above      = fp_ai.get("total_above_ground_beds")
    total_beds = listing.get("bedrooms", 0)
    concerns   = fp_ai.get("room_concerns", []) or []
    main_ok    = fp_ai.get("main_bed_adequate", True)

    if above is not None:
        bed_issues = len(concerns) + (0 if main_ok else 1)
        if above < total_beds:
            add_flag(f"{above} above-ground ({total_beds - above} in basement)", "warn")
        elif bed_issues > 0:
            add_flag(f"{above} beds (quality issues)", "info")
        else:
            add_flag(f"{above} good above-ground beds", "good")
        bed_sentences = []
        if not main_ok:
            bed_sentences.append("main bedroom appears undersized")
        for c in concerns[:3]:
            bed_sentences.append(c)
        if bed_sentences:
            parts.append("Bedroom note: " + "; ".join(bed_sentences) + ".")

    summary = fp_ai.get("summary", "").strip()
    if summary:
        parts.insert(0, summary)

    garden_map = {
        "none":       ("No garden",     "warn"),
        "patio_only": ("Patio only",    "warn"),
        "small":      ("Small garden",  "info"),
        "medium":     ("Medium garden", "good"),
        "large":      ("Large garden",  "good"),
    }
    garden_ai = fp_ai.get("garden_assessment", "")
    if garden_ai in garden_map:
        add_flag(*garden_map[garden_ai])

    kitchen_mod = fp_ai.get("kitchen_mod_difficulty", "")
    kitchen_adj = fp_ai.get("kitchen_adjacent_reception", True)
    if kitchen_mod == "hard":
        add_flag("Kitchen on different floor", "warn")
    elif kitchen_mod == "moderate":
        add_flag("Kitchen: structural move needed", "info")
    elif kitchen_adj:
        add_flag("Kitchen opens to reception", "good")

    circ = fp_ai.get("circulation_pct", 0)
    if isinstance(circ, (int, float)) and circ > 22:
        add_flag(f"{circ}% circulation", "info")
        parts.append(f"High circulation waste ({circ}% of floorplate on hallways/stairs).")

    if fp_ai.get("extension_potential"):
        add_flag("Extension potential", "good")
    if fp_ai.get("through_reception"):
        add_flag("Through reception", "good")

    return {"prose": " ".join(parts), "headline_sev": worst, "flags": flags}


# -- Listing -> JSON dict -----------------------------------------------------

def _listing_to_json(listing: dict) -> dict:
    addr         = _compact_address(listing.get("address", ""))
    breakdown    = listing.get("score_breakdown", {})
    above_ground = listing.get("above_ground_beds", listing.get("bedrooms", 0))
    beds         = listing.get("bedrooms", 0)
    ph           = listing.get("price_history_meta", {})
    ppsf         = listing.get("ppsf", 0)
    sqft         = listing.get("sqft", 0)
    score        = listing.get("score", 0)

    beds_display = f"{beds} bed"
    if above_ground < beds:
        beds_display = f"{above_ground}+{beds - above_ground}lg bed"

    breakdown_str = " | ".join(
        f"{k.upper()[:1]}:{v}" for k, v in breakdown.items()
        if k not in ("_capped",) and isinstance(v, (int, float)) and v != 0
    )

    return {
        "id":                listing.get("id", ""),
        "lat":               listing.get("lat", 0),
        "lng":               listing.get("lng", 0),
        "score":             score,
        "score_colour":      _score_colour(score),
        "address":           addr,
        "price":             listing.get("price_display", ""),
        "price_num":         listing.get("price", 0),
        "ppsf":              ppsf,
        "ppsf_colour":       _ppsf_colour(ppsf) if ppsf else "#9e9e9e",
        "sqft":              sqft,
        "beds":              beds,
        "beds_display":      beds_display,
        "period":            listing.get("period", "unknown"),
        "period_label":      _period_label(listing.get("period", "")),
        "period_colour":     _period_colour(listing.get("period", "")),
        "quality":           listing.get("location_quality", ""),
        "area":              listing.get("area_label", ""),
        "condition":         listing.get("condition", ""),
        "tenure":            listing.get("tenure", ""),
        "agent":             listing.get("agent", ""),
        "days_label":        listing.get("days_label", ""),
        "days_num":          _parse_days_number(listing.get("days_label", "")),
        "url":               listing.get("url", ""),
        "rm_url":            _rightmove_url(listing.get("address", "")),
        "image_url":         listing.get("image_url", ""),
        "is_reduced":        ph.get("is_reduced", False),
        "reduction_pct":     ph.get("total_reduction_pct", 0) if ph.get("is_reduced") else 0,
        "original_price":    ph.get("original_price", 0),
        "street_ppsf":       listing.get("street_ppsf", 0),
        "traffic_road":      listing.get("traffic_road", ""),
        "traffic_penalty":   listing.get("traffic_road_penalty", 0),
        "breakdown":         breakdown_str,
        "breakdown_tooltip": _build_breakdown_tooltip(listing),
        "ai":                _build_ai_prose(listing),
        "opp_score":         _opportunity_score(listing),
        "stale_unmotivated": (
            _parse_days_number(listing.get("days_label", "")) >= 21
            and not ph.get("is_reduced", False)
        ),
    }


# -- Sidebar HTML helpers -----------------------------------------------------

def _cb_group(items, name, label_fn=None):
    parts = []
    for item in items:
        label = (label_fn(item) if label_fn else item.replace("_", " ").title()) or "Unknown"
        parts.append(
            f'<label class="cb-label"><input type="checkbox" class="filter-cb" '
            f'data-filter="{name}" value="{item}" checked> {label}</label>'
        )
    return "".join(parts)


# -- Main generate function ---------------------------------------------------

def generate_html(scored: list[dict], excluded: list[dict], state: dict = None) -> str:
    now   = datetime.now().strftime("%A %d %B %Y, %H:%M")
    count = len(scored)

    if count == 0:
        return (
            '<!DOCTYPE html><html><head><meta charset="utf-8">'
            '<title>Property Monitor</title>'
            '<style>body{font-family:-apple-system,sans-serif;max-width:960px;margin:40px auto;padding:0 20px}</style>'
            '</head><body>'
            '<h2 style="font-size:18px;font-weight:600;">Property Monitor</h2>'
            f'<p style="color:#888;font-size:13px;">{now}</p>'
            f'<p>No matching listings. {len(excluded)} excluded.</p>'
            '</body></html>'
        )

    listings_json = json.dumps([_listing_to_json(l) for l in scored], ensure_ascii=True)

    periods    = sorted(set(l.get("period", "unknown") for l in scored))
    qualities  = sorted(set(l.get("location_quality", "") for l in scored))
    areas      = sorted(set(l.get("area_label", "") for l in scored if l.get("area_label")))
    bed_counts = sorted(set(l.get("bedrooms", 0) for l in scored))
    max_days   = min(max((_parse_days_number(l.get("days_label", "")) for l in scored), default=365), 365)

    reduced_count = sum(1 for l in scored if l.get("price_history_meta", {}).get("is_reduced"))
    traffic_count = sum(1 for l in scored if l.get("traffic_road"))
    ppsf_list     = [l["ppsf"] for l in scored if l.get("ppsf")]
    avg_ppsf      = round(sum(ppsf_list) / len(ppsf_list)) if ppsf_list else 0
    avg_score     = round(sum(l["score"] for l in scored) / len(scored)) if scored else 0

    stats_bar = (
        f'<span class="stat">{count} results</span>'
        f'<span class="stat-sep">\u00b7</span>'
        f'<span class="stat">avg score {avg_score}</span>'
        f'<span class="stat-sep">\u00b7</span>'
        f'<span class="stat">avg \u00a3{avg_ppsf:,}/sqft</span>'
        + (f'<span class="stat-sep">\u00b7</span><span class="stat stat-reduced">{reduced_count} reduced</span>' if reduced_count else "")
        + (f'<span class="stat-sep">\u00b7</span><span class="stat stat-traffic">{traffic_count} on traffic road</span>' if traffic_count else "")
        + f'<span class="stat-sep">\u00b7</span><span class="stat">{len(excluded)} excluded</span>'
    )

    excl_items = "".join(
        f'<div class="excl-item">'
        f'<span class="excl-reason">{e.get("exclude_reason", "?")}</span>'
        f'<a href="{e.get("url", "#")}" target="_blank" class="excl-addr">'
        f'{_compact_address(e.get("address", ""))}</a>'
        f'</div>'
        for e in excluded
    )

    cb_beds      = _cb_group([str(b) for b in bed_counts], "beds")
    cb_periods   = _cb_group(periods, "period", _period_label)
    cb_qualities = _cb_group(qualities, "quality", lambda x: x.title())
    area_options = "".join(f'<option value="{a}">{a}</option>' for a in areas)

    template_path = os.path.join(_DIR, "template.html")
    appjs_path    = os.path.join(_DIR, "app.js")

    with open(template_path, encoding="utf-8") as f:
        html = f.read()
    with open(appjs_path, encoding="utf-8") as f:
        app_js = f.read()

    replacements = {
        "__NOW__":          now,
        "__COUNT__":        str(count),
        "__MAX_DAYS__":     str(max_days),
        "__STATS_BAR__":    stats_bar,
        "__EXCL_ITEMS__":   excl_items,
        "__EXCL_COUNT__":   str(len(excluded)),
        "__CB_BEDS__":      cb_beds,
        "__CB_PERIODS__":   cb_periods,
        "__CB_QUALITIES__": cb_qualities,
        "__AREA_OPTIONS__": area_options,
        "__LISTINGS_JSON__":listings_json,
        "__APP_JS__":       app_js,
    }
    for token, value in replacements.items():
        html = html.replace(token, value)

    return html


# -- Write output -------------------------------------------------------------

def write_output(html: str) -> tuple[str, str]:
    _ensure_dir()
    ts          = datetime.now().strftime("%Y-%m-%d_%H%M")
    alert_path  = os.path.join(ALERTS_DIR, f"alert_{ts}.html")
    latest_path = os.path.join(ALERTS_DIR, "latest.html")
    for path in [alert_path, latest_path]:
        with open(path, "w", encoding="utf-8", errors="replace") as f:
            f.write(html)
    return alert_path, latest_path
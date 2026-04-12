# state.py — Track seen properties and price history

import json
import os
from datetime import datetime
from config import STATE_FILE


def load_state() -> dict:
    if not os.path.exists(STATE_FILE):
        return {"seen_ids": {}, "last_run": None, "run_count": 0}
    try:
        with open(STATE_FILE, "r") as f:
            return json.load(f)
    except (json.JSONDecodeError, IOError):
        return {"seen_ids": {}, "last_run": None, "run_count": 0}


def save_state(state: dict) -> None:
    state["last_run"] = datetime.now().isoformat()
    state["run_count"] = state.get("run_count", 0) + 1
    tmp = STATE_FILE + ".tmp"
    with open(tmp, "w") as f:
        json.dump(state, f, indent=2)
    os.replace(tmp, STATE_FILE)  # atomic — no corrupt state on kill


def get_new_properties(listings: list[dict], state: dict) -> list[dict]:
    seen = set(state.get("seen_ids", {}).keys())
    return [l for l in listings if f"otm:{l.get('id', '')}" not in seen]


def mark_seen(listings: list[dict], state: dict) -> dict:
    """Record listings as seen. Update price history if price has changed."""
    seen = state.get("seen_ids", {})
    now = datetime.now().isoformat()

    for l in listings:
        key = f"otm:{l.get('id', '')}"
        current_price = l.get("price", 0)

        sqft = l.get("sqft") or 0
        epc_sqft = l.get("epc_sqft")
        effective_sqft = epc_sqft or sqft or 0
        ppsf = round(current_price / effective_sqft) if effective_sqft else None

        if key not in seen:
            seen[key] = {
                "address": l.get("address", ""),
                "price": current_price,
                "score": l.get("score", 0),
                "beds": l.get("bedrooms", 0),
                "sqft": sqft or None,
                "epc_sqft": epc_sqft,
                "ppsf": ppsf,
                "period": l.get("period", ""),
                "area_label": l.get("area_label", ""),
                "first_seen": now,
                "price_history": [{"date": now, "price": current_price}],
            }
        else:
            existing = seen[key]
            existing["score"] = l.get("score", 0)
            # Refresh enrichable fields each run so they stay current
            if l.get("bedrooms"):
                existing["beds"] = l.get("bedrooms", 0)
            if sqft:
                existing["sqft"] = sqft
                existing["ppsf"] = ppsf
            if epc_sqft:
                existing["epc_sqft"] = epc_sqft
                existing["ppsf"] = ppsf
            if l.get("period"):
                existing["period"] = l.get("period", "")
            if l.get("area_label"):
                existing["area_label"] = l.get("area_label", "")

            # Migrate legacy entries that have no price_history
            if "price_history" not in existing:
                existing["price_history"] = [
                    {"date": existing.get("first_seen", now), "price": existing.get("price", 0)}
                ]

            # Record price change if different from last known price
            last_known_price = existing["price"]
            if current_price != last_known_price:
                existing["price_history"].append({"date": now, "price": current_price})
                existing["price"] = current_price

    state["seen_ids"] = seen
    return state


def get_price_history(listing: dict, state: dict) -> dict:
    """
    Return price history metadata for a listing.

    Returns dict with:
        history: list of {date, price}
        reduction_count: number of price reductions
        total_reduction_pct: % drop from original asking price (negative = reduction)
        last_change_days: days since last price change (None if no change)
        original_price: first recorded price
        current_price: latest price in state
        is_reduced: bool
    """
    key = f"otm:{listing.get('id', '')}"
    seen = state.get("seen_ids", {})

    if key not in seen:
        return {"history": [], "reduction_count": 0, "total_reduction_pct": 0,
                "last_change_days": None, "original_price": 0, "is_reduced": False}

    entry = seen[key]
    history = entry.get("price_history", [])

    if not history:
        return {"history": [], "reduction_count": 0, "total_reduction_pct": 0,
                "last_change_days": None, "original_price": entry.get("price", 0),
                "is_reduced": False}

    original_price = history[0]["price"]
    current_price = history[-1]["price"]

    # Count reductions (price drops only)
    reduction_count = sum(
        1 for i in range(1, len(history))
        if history[i]["price"] < history[i - 1]["price"]
    )

    total_reduction_pct = 0.0
    if original_price and original_price != current_price:
        total_reduction_pct = round((current_price - original_price) / original_price * 100, 1)

    # Days since last price change
    last_change_days = None
    if len(history) > 1:
        try:
            last_change_dt = datetime.fromisoformat(history[-1]["date"])
            last_change_days = (datetime.now() - last_change_dt).days
        except (ValueError, TypeError):
            pass

    return {
        "history": history,
        "reduction_count": reduction_count,
        "total_reduction_pct": total_reduction_pct,
        "last_change_days": last_change_days,
        "original_price": original_price,
        "current_price": current_price,
        "is_reduced": total_reduction_pct < 0,
    }

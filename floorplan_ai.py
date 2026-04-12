"""
floorplan_ai.py - Analyse floorplan images via Claude API (Sonnet)

v3.3 prompt: room proportions, circulation waste, kitchen modernisation
difficulty, garden size assessment, richer summary.

Results cached by floorplan URL. Set ANTHROPIC_API_KEY in ~/.property-monitor-env.
"""

import os
import base64
import urllib.request
import urllib.error
import json
from pathlib import Path
from typing import Optional


ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY", "")
MODEL = "claude-sonnet-4-6"

_FP_CACHE_FILE = Path(__file__).parent / "floorplan_cache.json"
_fp_cache: dict = {}
_fp_cache_dirty = False


def _load_fp_cache() -> dict:
    global _fp_cache
    if _fp_cache:
        return _fp_cache
    if _FP_CACHE_FILE.exists():
        try:
            _fp_cache = json.loads(_FP_CACHE_FILE.read_text())
        except Exception:
            _fp_cache = {}
    return _fp_cache


def _save_fp_cache() -> None:
    global _fp_cache_dirty
    if _fp_cache_dirty:
        _FP_CACHE_FILE.write_text(json.dumps(_fp_cache, indent=2, ensure_ascii=True))
        _fp_cache_dirty = False


SYSTEM_PROMPT = """You are analysing a UK residential property floorplan for a buyer seeking Georgian/Victorian terraced houses in North/East London.

Return ONLY a JSON object (no markdown, no prose, no commentary) with these exact keys:

{
  "bedrooms_by_floor": {
    "basement": <int>,
    "lower_ground": <int>,
    "ground": <int>,
    "first": <int>,
    "second": <int>,
    "third": <int>
  },
  "total_above_ground_beds": <int>,
  "basement_rooms": [<list of room labels in basement/lower ground, e.g. "bedroom", "utility", "gym", "kitchen">],

  "room_concerns": [<list of strings, each flagging a specific undersized or problematic room, e.g. "Bedroom 3 appears under 8ft wide", "Kitchen very narrow", "Reception room is L-shaped with poor proportions">],
  "main_bed_adequate": <true if main bedroom appears >= approx 12x12ft or 3.5x3.5m, false if clearly smaller>,

  "circulation_pct": <int estimate 5-30: what percentage of total floorplate is hallways, landings, stairs>,

  "kitchen_location": <"basement"|"lower_ground"|"ground"|"first"|"other">,
  "kitchen_mod_difficulty": <"easy"|"moderate"|"hard": "easy" = kitchen already adjacent to reception or open plan possible with minor wall removal; "moderate" = structural wall likely but same floor; "hard" = kitchen on different floor from main reception, would need full replanning>,
  "kitchen_adjacent_reception": <true/false>,

  "through_reception": <true/false>,
  "double_fronted": <true/false>,
  "extension_potential": <true/false: visible side return, rear extension space, or loft not yet converted>,

  "garden_assessment": <"large"|"medium"|"small"|"patio_only"|"none"|"unclear": "large" = 30ft+/10m+ deep; "medium" = 15-30ft; "small" = under 15ft; "patio_only" = hard surface area under ~10ft deep; "none" = no outdoor space visible; "unclear" = cannot determine from floorplan>,

  "verdict": <"strong"|"good"|"mixed"|"weak": overall layout verdict weighing positives against negatives. "strong" = few or no concerns, works well as-is; "good" = minor issues only, fixable; "mixed" = real tradeoffs a buyer must accept; "weak" = significant structural layout problems>,
  "summary": "<two sentences max, 40 words max. Start with the overall verdict on the layout — what works and what doesn't. Be specific and balanced, not just negative.>"
}

Rules:
- Count any room labelled Bed, Bedroom, Master, Dressing Room, Guest Room as a bedroom.
- If a floor is not shown, set its bedroom count to 0.
- For circulation_pct, estimate conservatively. A typical Victorian terrace is 15-20%.
- For garden_assessment, look at any rear garden/yard shown on the ground floor plan.
- Be specific in room_concerns. "Bedroom 3 appears narrow" is useful. "Layout is OK" is not.
- The summary must weigh positives against negatives. If the layout is fundamentally good with one flaw, say so.
- If dimensions are printed on the floorplan, use them. If not, estimate from proportions.
- BATHROOMS: Count all rooms labelled Bathroom, Shower Room, Ensuite, En-suite, En Suite, WC, Cloakroom, Family Bathroom, Jack and Jill as bathroom/WC provision. Do NOT state bathrooms are stranded or absent on a floor unless you have confirmed there is truly NO bathroom of any kind (including shower room or ensuite) on that floor. Never conflate "no bath" with "no bathroom".
"""


def _download_image(url: str) -> Optional[bytes]:
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/120.0.0.0 Safari/537.36"
        )
    }
    req = urllib.request.Request(url, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=20) as resp:
            return resp.read()
    except Exception as e:
        print(f"    Floorplan download failed: {e}")
        return None


def _detect_media_type(url: str, data: bytes) -> str:
    if data[:3] == b"\xff\xd8\xff":
        return "image/jpeg"
    if data[:4] == b"\x89PNG":
        return "image/png"
    if data[:4] == b"RIFF" and len(data) > 12 and data[8:12] == b"WEBP":
        return "image/webp"
    if data[:4] == b"GIF8":
        return "image/gif"
    url_lower = url.lower()
    if ".webp" in url_lower:
        return "image/webp"
    return "image/jpeg"


def _call_claude_api(image_data: bytes, media_type: str) -> Optional[dict]:
    if not ANTHROPIC_API_KEY:
        print("    ANTHROPIC_API_KEY not set")
        return None

    b64 = base64.standard_b64encode(image_data).decode("utf-8")

    payload = {
        "model": MODEL,
        "max_tokens": 800,
        "system": SYSTEM_PROMPT,
        "messages": [
            {
                "role": "user",
                "content": [
                    {
                        "type": "image",
                        "source": {
                            "type": "base64",
                            "media_type": media_type,
                            "data": b64,
                        }
                    },
                    {
                        "type": "text",
                        "text": "Analyse this floorplan and return the JSON."
                    }
                ]
            }
        ]
    }

    req_body = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        "https://api.anthropic.com/v1/messages",
        data=req_body,
        headers={
            "x-api-key": ANTHROPIC_API_KEY,
            "anthropic-version": "2023-06-01",
            "content-type": "application/json",
        },
        method="POST",
    )

    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            response_data = json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        error_body = e.read().decode("utf-8", errors="replace")
        print(f"    Claude API error {e.code}: {error_body[:200]}")
        return None
    except Exception as e:
        print(f"    Claude API call failed: {e}")
        return None

    try:
        text = response_data["content"][0]["text"].strip()
        if text.startswith("```"):
            text = text.split("```")[1]
            if text.startswith("json"):
                text = text[4:]
        return json.loads(text.strip())
    except (KeyError, IndexError, json.JSONDecodeError) as e:
        raw = response_data.get("content", [{}])[0].get("text", "")
        print(f"    Could not parse Claude response: {e}. Raw: {raw[:200]}")
        return None  # Don't cache — allow retry on next run


def analyse_floorplans(listings: list[dict], quiet: bool = False) -> None:
    if not ANTHROPIC_API_KEY:
        print("  ANTHROPIC_API_KEY not set. Set it to enable floorplan AI analysis.")
        return

    cache = _load_fp_cache()
    global _fp_cache, _fp_cache_dirty

    candidates = [l for l in listings if l.get("floorplan_url")]
    if not quiet:
        print(f"  {len(candidates)} listings have floorplan URLs")

    cached_count = 0
    api_count = 0

    for i, listing in enumerate(candidates):
        addr = listing.get("address", "").replace("\n", ", ")[:45]
        fp_url = listing["floorplan_url"]

        if fp_url in cache:
            listing["floorplan_ai"] = cache[fp_url]
            cached_count += 1
            if not quiet:
                print(f"  [{i+1}/{len(candidates)}] {addr} (cached)")
            continue

        if not quiet:
            print(f"  [{i+1}/{len(candidates)}] {addr}")

        image_data = _download_image(fp_url)
        if not image_data:
            listing["floorplan_ai"] = {"summary": "Floorplan download failed"}
            continue

        media_type = _detect_media_type(fp_url, image_data)
        result = _call_claude_api(image_data, media_type)

        if result:
            listing["floorplan_ai"] = result
            cache[fp_url] = result
            _fp_cache_dirty = True
            api_count += 1
            if not quiet:
                print(f"    -> {result.get('summary', 'no summary')[:80]}")
        else:
            listing["floorplan_ai"] = {"summary": "Analysis failed"}

    _save_fp_cache()
    if not quiet:
        print(f"  Floorplan AI: {cached_count} cached, {api_count} new API calls")

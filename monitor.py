#!/usr/bin/env python3
"""
property-monitor v3.2 — Scored property ranking

Single source (OTM). Weighted scoring. Detail page enrichment for sq ft.
Output: ranked table sorted by personalised fit score (0-100).
Interactive filters: beds, period, location quality, score threshold, area.

v3.2:
  - Price history tracking (snapshots per run, % reductions, days since change)
  - Additional sort buttons: price, sqft, recency
  - Bug fixes: Ardleigh Road new build period, Brett Close exclusion,
    Howard Road scoring
  - Land Registry £/sqft comp metric per street
  - Floorplan AI analysis via Claude API (optional)

Usage:
    python3 monitor.py              # New since last run
    python3 monitor.py --all        # All current matches
    python3 monitor.py --no-detail  # Skip detail page fetching (faster)
    python3 monitor.py --dry-run    # Don't update state
    python3 monitor.py --reset      # Clear seen properties
    python3 monitor.py --floorplan  # Enable floorplan AI analysis (costs API credits)
"""

import sys
import os
import argparse
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from otm import search, enrich_detail, save_detail_cache, prune_detail_cache
from scorer import score_all, score_property
from state import load_state, save_state, get_new_properties, mark_seen, get_price_history
from output import generate_html, write_output
from land_registry import enrich_all_street_comps


def main():
    parser = argparse.ArgumentParser(description="Property monitor v3.2")
    parser.add_argument("--all", action="store_true", help="Show all, not just new")
    parser.add_argument("--no-detail", action="store_true", help="Skip detail page fetching")
    parser.add_argument("--dry-run", action="store_true", help="Don't update state")
    parser.add_argument("--reset", action="store_true", help="Clear seen properties")
    parser.add_argument("--quiet", action="store_true")
    parser.add_argument("--floorplan", action="store_true",
                        help="Run floorplan AI analysis via Claude API (costs API credits)")
    parser.add_argument("--no-street-comp", action="store_true",
                        help="Skip Land Registry street comp enrichment")
    args = parser.parse_args()

    if not args.quiet:
        print(f"Property Monitor v3.2 — {datetime.now().strftime('%Y-%m-%d %H:%M')}")
        print("=" * 50)

    state = load_state()
    if args.reset:
        state = {"seen_ids": {}, "last_run": None, "run_count": 0}
        save_state(state)
        print("State reset.")
        if not args.all:
            return

    # Phase 1: Search
    if not args.quiet:
        print("\nPhase 1: Search OTM...")
    listings = search()

    # Guard: zero listings almost certainly means OTM blocked/changed/is down
    if not listings:
        print("WARNING: 0 listings returned from OTM. Possible block or outage. Aborting.")
        sys.exit(2)  # non-zero exit so GitHub Actions marks the step failed

    if len(listings) < 10:
        print(f"WARNING: Only {len(listings)} listings returned - possible partial block.")

    # Phase 2: Initial scoring (includes dedup)
    scored, excluded = score_all(listings)
    if not args.quiet:
        print(f"\nScored: {len(scored)} viable, {len(excluded)} excluded "
              f"(deduped from {len(listings)} raw)")

    # Phase 3: Detail pages
    if not args.no_detail and scored:
        if not args.quiet:
            print(f"\nPhase 2: Fetching {len(scored)} detail pages for sq ft...")
        for i, listing in enumerate(scored):
            if not args.quiet:
                addr = listing['address'].replace('\n', ', ')[:50]
                print(f"  [{i+1}/{len(scored)}] {addr}...")
            enrich_detail(listing)

        if not args.dry_run:
            save_detail_cache()

        # Re-score with enriched data
        for listing in scored:
            score_property(listing)
        scored.sort(key=lambda x: x["score"], reverse=True)

    # Phase 4: Attach price history metadata to each listing
    for listing in scored:
        listing["price_history_meta"] = get_price_history(listing, state)
    for listing in excluded:
        listing["price_history_meta"] = get_price_history(listing, state)

    # Save state NOW — before slow network phases that may timeout.
    # Street comps and floorplan AI can take 10-20 min; if the CI job times
    # out during them, state would otherwise be lost entirely.
    if not args.dry_run:
        mark_seen(scored, state)
        mark_seen(excluded, state)
        save_state(state)

    # Phase 4b: Street comp enrichment (Land Registry) — only for score >= 50
    if not args.no_street_comp:
        comp_candidates = [l for l in scored if l["score"] >= 50]
        if not args.quiet:
            print(f"\nPhase 4b: Street comp for {len(comp_candidates)}/{len(scored)} "
                  f"listings (score >= 50)")
        enrich_all_street_comps(comp_candidates, quiet=args.quiet)

    # Phase 5 (optional): Floorplan AI analysis — only for score >= 60
    if args.floorplan:
        fp_candidates = [l for l in scored if l["score"] >= 60
                         and l.get("floorplan_url")]
        if not args.quiet:
            print(f"\nPhase 5: Floorplan AI for {len(fp_candidates)}/{len(scored)} "
                  f"listings (score >= 50, has floorplan)")
        try:
            from floorplan_ai import analyse_floorplans
            analyse_floorplans(fp_candidates, quiet=args.quiet)

            # Post-AI: update bedroom scoring if AI detected discrepancy
            rescore_needed = False
            for listing in fp_candidates:
                fp = listing.get("floorplan_ai", {})
                ai_above = fp.get("total_above_ground_beds")
                if ai_above is not None and isinstance(ai_above, int):
                    current_above = listing.get("above_ground_beds", 0)
                    listing_beds = listing.get("bedrooms", 0)
                    # AI found fewer above-ground beds than we thought
                    if ai_above < current_above:
                        listing["above_ground_beds"] = ai_above
                        listing["ai_bed_warning"] = (
                            f"AI: {ai_above} above-ground beds "
                            f"(listing says {listing_beds})")
                        rescore_needed = True
                    # AI found basement beds we missed
                    basement_ai = fp.get("bedrooms_by_floor", {}).get("basement", 0)
                    lg_ai = fp.get("bedrooms_by_floor", {}).get("lower_ground", 0)
                    if (basement_ai + lg_ai) > 0 and current_above == listing_beds:
                        listing["above_ground_beds"] = ai_above
                        listing["ai_bed_warning"] = (
                            f"AI: {basement_ai + lg_ai} basement bed(s) detected")
                        rescore_needed = True

            # Always re-score after AI — kitchen penalties, circulation, bed adequacy
            for listing in fp_candidates:
                score_property(listing)
            scored.sort(key=lambda x: x["score"], reverse=True)
            if not args.quiet:
                print("  Re-scored after floorplan AI analysis")

        except ImportError:
            print("  floorplan_ai.py not found — skipping")

    if not args.quiet:
        print(f"\nTop 5:")
        for l in scored[:5]:
            ppsf = f"£{l['ppsf']}/sqft" if l.get("ppsf") else "no sqft"
            beds_display = f"{l.get('above_ground_beds', l.get('bedrooms', 0))}bed"
            if l.get('above_ground_beds', 0) < l.get('bedrooms', 0):
                beds_display += f"({l['bedrooms']}tot)"
            ph = l.get("price_history_meta", {})
            reduction_str = ""
            if ph.get("is_reduced"):
                reduction_str = f" ↓{ph['total_reduction_pct']}%"
            print(f"  {l['score']:3d}  {l.get('price_display',''):>8s}{reduction_str:<8s}  "
                  f"{ppsf:>12s}  {beds_display:>10s}  {l.get('period',''):12s}  "
                  f"{l.get('area_label',''):18s}  "
                  f"{l['address'].replace(chr(10), ', ')[:40]}")

    # Filter to new only (unless --all)
    if args.all:
        output_scored = scored
    else:
        output_scored = get_new_properties(scored, state)
        if not args.quiet:
            print(f"\nNew since last run: {len(output_scored)}")

    # Generate output
    html = generate_html(output_scored, excluded, state)
    alert_path, latest_path = write_output(html)

    if not args.quiet:
        print(f"\nOutput: {latest_path}")

    # Prune stale detail cache entries (skip in dry-run — no disk writes)
    if not args.dry_run:
        pruned = prune_detail_cache()
        if pruned and not args.quiet:
            print(f"  Pruned {pruned} stale entries from detail cache")

    # Open in browser (local only, not in CI)
    if output_scored and not args.quiet and sys.stdout.isatty() and os.environ.get("CI") != "true":
        try:
            import subprocess
            subprocess.run(["open", latest_path], check=False)
        except Exception:
            pass


if __name__ == "__main__":
    main()

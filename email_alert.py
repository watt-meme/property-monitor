#!/usr/bin/env python3
"""
email_alert.py — Send property monitor results by email

Usage:
    python3 email_alert.py              # Normal: new listings only
    python3 email_alert.py --test       # Test: send top 5 regardless of newness
    python3 email_alert.py --top 5      # Override how many to show

Configuration via ~/.property-monitor-env:
    PM_EMAIL_FROM, PM_EMAIL_TO, PM_SMTP_PASS
"""

import os
import sys
import json
import smtplib
import argparse
from email.message import EmailMessage
from datetime import datetime, timedelta
from pathlib import Path

EMAIL_FROM    = os.environ.get("PM_EMAIL_FROM", "")
EMAIL_TO      = os.environ.get("PM_EMAIL_TO",   "")
EMAIL_CC      = os.environ.get("PM_EMAIL_CC",   "")
SMTP_HOST     = os.environ.get("PM_SMTP_HOST",  "smtp.gmail.com")
SMTP_PORT     = int(os.environ.get("PM_SMTP_PORT", "587"))
SMTP_USER     = os.environ.get("PM_SMTP_USER",  EMAIL_FROM)
SMTP_PASS     = os.environ.get("PM_SMTP_PASS",  "")
TOP_N         = 5
DASHBOARD_URL = "https://watt-meme.github.io/property-monitor/"

ALLOWED_SUBJECT_PREFIX = "Property Monitor:"
MAX_BODY_SIZE = 500_000

BASE_DIR   = Path(__file__).parent
STATE_FILE = BASE_DIR / "state.json"
ALERTS_DIR = BASE_DIR / "alerts"
LATEST_HTML = ALERTS_DIR / "latest.html"


def _load_state() -> dict:
    if STATE_FILE.exists():
        try:
            return json.loads(STATE_FILE.read_text())
        except Exception:
            pass
    return {}


def _score_colour(score: int) -> str:
    if score >= 70: return "#2e7d32"
    if score >= 50: return "#1565c0"
    if score >= 30: return "#f57f17"
    return "#999"


def _reduction_badge(entry: dict) -> str:
    history = entry.get("price_history", [])
    if len(history) < 2:
        return ""
    original = history[0]["price"]
    current = history[-1]["price"]
    if original and current < original:
        pct = (current - original) / original * 100
        return (f' <span style="display:inline-block;background:#c62828;color:white;'
                f'font-size:10px;padding:1px 6px;border-radius:3px;">'
                f'&#8595;{abs(pct):.1f}%</span>')
    return ""


def _listing_row(entry: dict, font_size: int = 20, padding: str = "8px 10px",
                 extra_meta: str = "") -> str:
    addr = entry.get("address", "").replace("\n", ", ")
    price = entry.get("price", 0)
    price_str = f"&#163;{price:,}" if price else "?"
    score = entry.get("score", 0)
    col = _score_colour(score)
    reduction = _reduction_badge(entry)
    otm_id = entry.get("otm_id", "")
    url = f"https://www.onthemarket.com/details/{otm_id}/" if otm_id else "#"
    area = entry.get("area_label", "")
    meta_parts = []
    if area:
        meta_parts.append(area)
    if extra_meta:
        meta_parts.append(extra_meta)
    meta_html = f'<div style="font-size:11px;color:#888;">{" · ".join(meta_parts)}</div>' if meta_parts else ""
    return f"""
<tr style="border-bottom:1px solid #f0f0f0;">
  <td style="padding:{padding};text-align:center;font-size:{font_size}px;font-weight:700;color:{col};width:48px;">{score}</td>
  <td style="padding:{padding};">
    <div><a href="{url}" style="color:#1565c0;font-weight:600;text-decoration:none;">{addr}</a></div>
    <div style="margin-top:3px;font-size:13px;font-weight:700;color:#1a237e;">{price_str}{reduction}</div>
    {meta_html}
  </td>
</tr>"""


def _build_html_email(new_listings: list[dict], recent_reductions: list[dict],
                       recent_top_performers: list[dict],
                       all_count: int, run_count: int, is_test: bool = False) -> str:
    now = datetime.now().strftime("%A %d %B %Y, %H:%M")
    test_banner = ('<div style="background:#fff3e0;color:#e65100;padding:8px 12px;'
                   'border-radius:4px;font-size:12px;margin-bottom:12px;">'
                   '&#9888; TEST EMAIL</div>') if is_test else ""

    dashboard_button = (
        f'<div style="margin:12px 0 16px;">'
        f'<a href="{DASHBOARD_URL}" style="display:inline-block;background:#1a237e;color:white;'
        f'font-size:14px;font-weight:600;padding:10px 20px;border-radius:6px;text-decoration:none;">'
        f'Open Dashboard &#8594;</a>'
        f'</div>'
    )

    new_section = ""
    if new_listings:
        rows = "".join(_listing_row(e) for e in new_listings)
        n = len(new_listings)
        new_section = f"""
<h3 style="font-size:15px;color:#1a237e;margin:0 0 8px;">&#128293; {n} new listing{'s' if n != 1 else ''}</h3>
<table style="border-collapse:collapse;width:100%;">{rows}</table>"""
    else:
        new_section = '<p style="color:#888;font-size:13px;">No new listings since last run.</p>'

    top_performers_section = ""
    if recent_top_performers:
        rows = ""
        for entry in recent_top_performers:
            days_ago = entry.get("_days_ago", 0)
            age_label = "today" if days_ago == 0 else f"{days_ago}d ago"
            rows += _listing_row(entry, extra_meta=f"added {age_label}")
        top_performers_section = f"""
<div style="margin-top:16px;padding-top:12px;border-top:1px solid #eee;">
<h3 style="font-size:14px;color:#2e7d32;margin:0 0 8px;">&#11088; Top performers — last 14 days</h3>
<table style="border-collapse:collapse;width:100%;">{rows}</table>
</div>"""

    reduction_section = ""
    if recent_reductions:
        r_rows = ""
        for entry in recent_reductions[:5]:
            addr = entry.get("address", "").replace("\n", ", ")
            price = entry.get("price", 0)
            score = entry.get("score", 0)
            col = _score_colour(score)
            reduction = _reduction_badge(entry)
            otm_id = entry.get("otm_id", "")
            url = f"https://www.onthemarket.com/details/{otm_id}/" if otm_id else "#"
            r_rows += f"""
<tr style="border-bottom:1px solid #f0f0f0;">
  <td style="padding:6px 8px;text-align:center;font-size:16px;font-weight:700;color:{col};width:40px;">{score}</td>
  <td style="padding:6px 8px;font-size:12px;">
    <a href="{url}" style="color:#1565c0;text-decoration:none;">{addr}</a>
    <span style="margin-left:8px;">&#163;{price:,}{reduction}</span>
  </td>
</tr>"""
        reduction_section = f"""
<div style="margin-top:16px;padding-top:12px;border-top:1px solid #eee;">
<h3 style="font-size:14px;color:#c62828;margin:0 0 8px;">&#128200; Recent price reductions (score &#8805; 50)</h3>
<table style="border-collapse:collapse;width:100%;">{r_rows}</table>
</div>"""

    return f"""
<html><body style="font-family:-apple-system,sans-serif;max-width:640px;margin:auto;color:#333;padding:16px;">
{test_banner}
<h2 style="font-size:18px;color:#1a237e;margin:0;">Property Monitor</h2>
<p style="color:#666;font-size:12px;margin:4px 0 6px;">{now} &#183; {all_count} active &#183; run #{run_count}</p>
{dashboard_button}
{new_section}
{top_performers_section}
{reduction_section}
</body></html>"""


def send_email(subject: str, html_body: str, attach_html: Path = None) -> None:
    if not EMAIL_FROM or not EMAIL_TO or not SMTP_PASS:
        print("Email not configured. Set PM_EMAIL_FROM, PM_EMAIL_TO, PM_SMTP_PASS.")
        print("Subject would be:", subject)
        return

    if not subject.startswith(ALLOWED_SUBJECT_PREFIX):
        print(f"BLOCKED: Subject does not start with '{ALLOWED_SUBJECT_PREFIX}'")
        return

    recipient = EMAIL_TO.strip().lower()
    if not recipient or "@" not in recipient:
        print(f"BLOCKED: Invalid recipient '{EMAIL_TO}'")
        return

    if len(html_body) > MAX_BODY_SIZE:
        print(f"BLOCKED: Body size {len(html_body)} exceeds limit")
        return

    if any(c in EMAIL_TO for c in [",", ";", " "]):
        print(f"BLOCKED: Multiple recipients detected")
        return

    if recipient != EMAIL_FROM.strip().lower():
        print(f"BLOCKED: Recipient must match sender (self-send only)")
        return

    msg = EmailMessage()
    msg["Subject"] = subject
    msg["From"]    = EMAIL_FROM
    msg["To"]      = recipient
    if EMAIL_CC.strip():
        msg["Cc"] = EMAIL_CC.strip()
    msg.set_content("Property Monitor alert (HTML email).")
    msg.add_alternative(html_body, subtype="html")

    # Attach full dashboard HTML if available
    if attach_html and attach_html.exists():
        msg.add_attachment(
            attach_html.read_bytes(),
            maintype="text",
            subtype="html",
            filename="property-monitor.html",
        )
        print(f"  Attaching dashboard ({attach_html.stat().st_size // 1024}KB)")

    try:
        with smtplib.SMTP(SMTP_HOST, SMTP_PORT, timeout=30) as server:
            server.ehlo()
            server.starttls()
            server.login(SMTP_USER, SMTP_PASS)
            server.send_message(msg)
        print(f"Email sent to {recipient}")
    except Exception as e:
        print(f"Email failed: {e}", file=sys.stderr)
        sys.exit(1)


def _find_recent_reductions(all_entries: list[dict], last_run: str) -> list[dict]:
    """Return score>=50 entries where a price reduction was recorded since last_run."""
    reductions = []
    for entry in all_entries:
        if entry.get("score", 0) < 50:
            continue
        history = entry.get("price_history", [])
        if len(history) < 2:
            continue
        # Check whether the most recent price change is (a) a reduction and
        # (b) occurred after last_run
        last_change = history[-1]
        prev_price = history[-2]["price"]
        curr_price = last_change["price"]
        if curr_price >= prev_price:
            continue  # not a reduction
        if last_run:
            try:
                dt_change = datetime.fromisoformat(last_change["date"])
                dt_last = datetime.fromisoformat(last_run)
                if dt_change <= dt_last:
                    continue  # reduction predates this run
            except ValueError:
                pass
        reductions.append(entry)
    reductions.sort(key=lambda x: x.get("score", 0), reverse=True)
    return reductions


def _find_recent_top_performers(all_entries: list[dict], exclude_ids: set[str],
                                days: int = 14, min_score: int = 60,
                                max_show: int = 6) -> list[dict]:
    """Return high-scoring entries first seen within `days` days, excluding already-shown ids."""
    cutoff = datetime.now() - timedelta(days=days)
    results = []
    for entry in all_entries:
        if entry.get("otm_id", "") in exclude_ids:
            continue
        if entry.get("score", 0) < min_score:
            continue
        first_seen = entry.get("first_seen", "")
        if not first_seen:
            continue
        try:
            dt = datetime.fromisoformat(first_seen)
            if dt < cutoff:
                continue
            entry["_days_ago"] = (datetime.now() - dt).days
        except ValueError:
            continue
        results.append(entry)
    results.sort(key=lambda x: x.get("score", 0), reverse=True)
    return results[:max_show]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--top", type=int, default=TOP_N)
    parser.add_argument("--test", action="store_true",
                        help="Send test email with top listings regardless of newness")
    args = parser.parse_args()

    state = _load_state()
    seen = state.get("seen_ids", {})
    run_count = state.get("run_count", 0)
    last_run = state.get("last_run", "")

    all_entries = []
    for key, entry in seen.items():
        entry_copy = {**entry, "otm_id": key.replace("otm:", "")}
        all_entries.append(entry_copy)

    if args.test:
        all_entries.sort(key=lambda x: x.get("score", 0), reverse=True)
        test_listings = [e for e in all_entries if e.get("score", 0) >= 50][:args.top]
        test_ids = {e["otm_id"] for e in test_listings}

        reductions = _find_recent_reductions(all_entries, last_run)
        top_performers = _find_recent_top_performers(all_entries, test_ids)

        subject = f"Property Monitor: TEST - top {len(test_listings)} listings"
        html = _build_html_email(test_listings, reductions, top_performers,
                                 len(seen), run_count, is_test=True)
        send_email(subject, html)
        return

    new_entries = []
    for entry in all_entries:
        first_seen = entry.get("first_seen", "")
        if first_seen and last_run:
            try:
                dt_first = datetime.fromisoformat(first_seen)
                dt_last = datetime.fromisoformat(last_run)
                # New = first seen within 30 min either side of last_run
                # (CI: monitor writes state then email_alert runs; clocks match
                # but allow generous window for slow runs and timing skew)
                delta = (dt_first - dt_last).total_seconds()
                if -1800 < delta < 1800:
                    new_entries.append(entry)
            except ValueError:
                pass

    new_entries.sort(key=lambda x: x.get("score", 0), reverse=True)
    reductions = _find_recent_reductions(all_entries, last_run)
    new_ids = {e["otm_id"] for e in new_entries}
    top_performers = _find_recent_top_performers(all_entries, new_ids)

    n_new = len(new_entries)
    n_red = len(reductions)
    n_top = len(top_performers)

    # Skip email entirely if nothing to report
    if not n_new and not n_red and not n_top:
        print("No new listings, reductions, or top performers — email skipped.")
        return

    subject = (f"Property Monitor: {n_new} new listing{'s' if n_new != 1 else ''}"
               if n_new else "Property Monitor: price reductions")
    if n_new and n_red:
        subject = f"Property Monitor: {n_new} new + {n_red} reduction{'s' if n_red != 1 else ''}"

    html = _build_html_email(new_entries[:args.top], reductions, top_performers,
                             len(seen), run_count)
    send_email(subject, html)


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
# feedback_server.py — Lightweight local feedback server for Property Monitor.
#
# Receives POST /feedback from the HTML dashboard and appends to feedback.json.
# Runs on localhost:5001. Start manually or add to launchd alongside monitor.py.
#
# Usage:
#   python3 feedback_server.py           # runs until Ctrl-C
#   python3 feedback_server.py --port 5001
#
# feedback.json format: list of objects:
#   {id, action, reason, address, score, price, area, ts}
#
# Actions: shortlist | discard | undo_shortlist | undo_discard

import json
import os
import sys
from http.server import BaseHTTPRequestHandler, HTTPServer
from datetime import datetime

PORT = 5001
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
FEEDBACK_FILE = os.path.join(BASE_DIR, "feedback.json")


def _load() -> list:
    if not os.path.exists(FEEDBACK_FILE):
        return []
    with open(FEEDBACK_FILE, "r", encoding="utf-8") as f:
        try:
            return json.load(f)
        except json.JSONDecodeError:
            return []


def _save(data: list) -> None:
    with open(FEEDBACK_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)


def _summary(data: list) -> dict:
    counts = {}
    for entry in data:
        action = entry.get("action", "unknown")
        counts[action] = counts.get(action, 0) + 1
    return counts


class FeedbackHandler(BaseHTTPRequestHandler):

    def log_message(self, fmt, *args):
        # Suppress default access log; use our own
        pass

    def _cors_headers(self):
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")

    def do_OPTIONS(self):
        self.send_response(204)
        self._cors_headers()
        self.end_headers()

    def do_POST(self):
        if self.path != "/feedback":
            self.send_response(404)
            self.end_headers()
            return

        length = int(self.headers.get("Content-Length", 0))
        if length == 0:
            self.send_response(400)
            self.end_headers()
            return

        body = self.rfile.read(length)
        try:
            payload = json.loads(body)
        except json.JSONDecodeError:
            self.send_response(400)
            self.end_headers()
            return

        # Validate required fields
        required = {"id", "action"}
        if not required.issubset(payload.keys()):
            self.send_response(400)
            self.end_headers()
            return

        listing_id = payload["id"]
        action = payload["action"]
        reason = payload.get("reason")
        address = payload.get("address", "")
        ts = payload.get("ts", datetime.utcnow().isoformat())

        data = _load()

        if action.startswith("undo_"):
            # Remove the most recent matching entry
            target_action = action.replace("undo_", "")
            for i in reversed(range(len(data))):
                if data[i].get("id") == listing_id and data[i].get("action") == target_action:
                    data.pop(i)
                    break
        else:
            # Remove any prior entry for this listing (replace not accumulate)
            data = [e for e in data if e.get("id") != listing_id]
            data.append({
                "id": listing_id,
                "action": action,
                "reason": reason,
                "address": address,
                "score": payload.get("score"),
                "price": payload.get("price"),
                "area": payload.get("area"),
                "ts": ts,
            })

        _save(data)
        summary = _summary(data)
        print(f"[{datetime.now().strftime('%H:%M:%S')}] {action:20s} {address[:50]}"
              + (f" ({reason})" if reason else ""))

        self.send_response(200)
        self._cors_headers()
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(json.dumps({"ok": True, "summary": summary}).encode())

    def do_GET(self):
        if self.path == "/summary":
            data = _load()
            summary = _summary(data)
            shortlisted = [e for e in data if e.get("action") == "shortlist"]
            discarded = [e for e in data if e.get("action") == "discard"]
            payload = {
                "summary": summary,
                "shortlisted": shortlisted,
                "discarded": discarded,
                "total": len(data),
            }
            self.send_response(200)
            self._cors_headers()
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps(payload, indent=2).encode())
        elif self.path == "/health":
            self.send_response(200)
            self._cors_headers()
            self.end_headers()
            self.wfile.write(b"ok")
        else:
            self.send_response(404)
            self.end_headers()


def main():
    port = PORT
    for i, arg in enumerate(sys.argv[1:]):
        if arg == "--port" and i + 1 < len(sys.argv) - 1:
            port = int(sys.argv[i + 2])

    server = HTTPServer(("127.0.0.1", port), FeedbackHandler)
    data = _load()
    summary = _summary(data)
    print(f"Property Monitor feedback server on http://localhost:{port}")
    print(f"Feedback file: {FEEDBACK_FILE}")
    print(f"Existing entries: {len(data)} — {summary}")
    print("Waiting for events (Ctrl-C to stop)...")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nStopped.")


if __name__ == "__main__":
    main()

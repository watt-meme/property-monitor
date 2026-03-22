# fetch.py — Minimal HTTP fetching with rate limiting

import time
import urllib.request
import urllib.error
from typing import Optional
from config import REQUEST_DELAY

_last_request: dict[str, float] = {}

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "en-GB,en;q=0.9",
}


def get(url: str, accept: str = "text/html", delay: float = REQUEST_DELAY,
        timeout: int = 20) -> Optional[str]:
    from urllib.parse import urlparse
    domain = urlparse(url).netloc

    last = _last_request.get(domain, 0)
    wait = delay - (time.time() - last)
    if wait > 0:
        time.sleep(wait)
    _last_request[domain] = time.time()

    headers = {**HEADERS, "Accept": accept}
    req = urllib.request.Request(url, headers=headers)

    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.read().decode("utf-8", errors="replace")
    except urllib.error.HTTPError as e:
        print(f"    HTTP {e.code}: {url[:70]}")
        return None
    except Exception as e:
        print(f"    Error: {url[:70]} — {e}")
        return None

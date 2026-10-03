"""Best-effort content filtering for generated paper summaries."""

import sys
import time
from threading import Lock

import requests


FILTER_URL = "https://spam.dw-dengwei.workers.dev"
_cooldown_until = 0
_lock = Lock()


def is_sensitive(content: str) -> bool:
    """Return True only when the filtering service positively flags content.

    Filtering is intentionally fail-open: a rate limit or outage must not make
    an otherwise successful daily crawl publish an empty data set.
    """
    global _cooldown_until
    with _lock:
        if time.monotonic() < _cooldown_until:
            return False
    try:
        response = requests.post(FILTER_URL, json={"text": content}, timeout=5)
        if response.status_code == 200:
            return bool(response.json().get("sensitive", False))
        if response.status_code == 429:
            with _lock:
                _cooldown_until = time.monotonic() + 300
        print(
            f"Sensitive check unavailable (HTTP {response.status_code}); allowing content",
            file=sys.stderr,
        )
    except requests.RequestException as error:
        print(f"Sensitive check error; allowing content: {error}", file=sys.stderr)
    return False

"""
Tests that Gmail scans ride out transient refusals instead of failing.

A status scan makes hundreds of Gmail requests. Gmail sometimes refuses one --
403 rateLimitExceeded ("Units per minute per user"), 429, a 5xx, or a dropped
connection -- and the client library only retries those when asked to. These
tests pin that every scanner request is asked to.

Offline: Gmail is Google's own HttpMockSequence; nothing reaches the network.

Run: python test_gmail_retries.py   (or: pytest test_gmail_retries.py)
"""

import json
import random
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from googleapiclient.discovery import build
from googleapiclient.http import HttpMockSequence

from src import gmail

RATE_LIMITED = ({"status": "403"}, json.dumps({"error": {
    "code": 403,
    "message": "Quota exceeded for quota metric 'Total Query Cost' and limit "
               "'Units per minute per user' of service 'gmail.googleapis.com'",
    "errors": [{"reason": "rateLimitExceeded", "domain": "usageLimits"}],
}}))


def _gmail(*responses):
    return build("gmail", "v1", http=HttpMockSequence(list(responses)))


def _without_backoff_waits(fn):
    """Run fn with the library's random backoff set to zero, so tests don't sleep."""
    real = random.random
    random.random = lambda: 0.0
    try:
        return fn()
    finally:
        random.random = real


def test_a_rate_limited_request_is_retried_instead_of_failing_the_scan():
    svc = _gmail(RATE_LIMITED, RATE_LIMITED,
                 ({"status": "200"}, json.dumps({"messages": [{"id": "a"}, {"id": "b"}]})))
    stubs = _without_backoff_waits(lambda: gmail.list_message_stubs(svc, "from:sufs"))
    assert [s["id"] for s in stubs] == ["a", "b"]


def test_a_fetch_is_retried_too():
    svc = _gmail(RATE_LIMITED, ({"status": "200"}, json.dumps({"id": "a", "payload": {}})))
    msg = _without_backoff_waits(lambda: gmail.execute(
        svc.users().messages().get(userId="me", id="a", format="full")))
    assert msg["id"] == "a"


def test_retries_are_limited_so_a_real_outage_still_reports_an_error():
    svc = _gmail(*[RATE_LIMITED] * (gmail.RETRIES + 1))
    try:
        _without_backoff_waits(lambda: gmail.list_message_stubs(svc, "from:sufs"))
    except Exception as e:
        assert "rateLimitExceeded" in str(e) or "Quota exceeded" in str(e)
    else:
        raise AssertionError("expected the error once retries run out")


def test_no_scanner_makes_a_gmail_request_without_retries():
    """Every Gmail request in the scanners goes through gmail.execute."""
    src = Path(__file__).parent / "src"
    bare = [f"{name}:{n}" for name in ("gmail.py", "sufs_email_scanner.py", "amazon_scanner.py")
            for n, line in enumerate((src / name).read_text().splitlines(), 1)
            if ".execute()" in line]
    assert not bare, "Gmail requests without retries: " + ", ".join(bare)


if __name__ == "__main__":
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    for t in tests:
        t()
        print(f"  ok  {t.__name__}")
    print(f"OK — {len(tests)} tests passed; Gmail scans ride out rate limits and dropped connections.")

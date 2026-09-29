"""Gmail helpers shared by the Amazon and SUFS email scanners."""

# A scan makes hundreds of Gmail requests, and Gmail sometimes refuses one:
# 403 rateLimitExceeded ("Units per minute per user"), 429, a 5xx, or a dropped
# connection. The client library retries exactly those, with random waits that
# roughly double each time (up to 2, 4, 8... seconds) -- but only when asked; by
# default it tries once, so a single refusal used to end the whole scan. Six
# retries can wait about two minutes in all, long enough for a per-minute limit
# to reset; a real outage still surfaces as an error once they run out.
RETRIES = 6


def execute(request):
    """Run a Gmail API request, retrying transient refusals."""
    return request.execute(num_retries=RETRIES)


def list_message_stubs(service, query: str) -> list[dict]:
    """Every message stub matching a Gmail query, following all result pages.

    Gmail returns at most 500 stubs per page, newest first, so reading only the
    first page silently drops the oldest matches on any wide date range.
    """
    messages = []
    page_token = None
    while True:
        kwargs = {"userId": "me", "q": query, "maxResults": 500}
        if page_token:
            kwargs["pageToken"] = page_token
        resp = execute(service.users().messages().list(**kwargs))
        messages.extend(resp.get("messages", []))
        page_token = resp.get("nextPageToken")
        if not page_token:
            return messages

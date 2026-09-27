"""Gmail helpers shared by the Amazon and SUFS email scanners."""


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
        resp = service.users().messages().list(**kwargs).execute()
        messages.extend(resp.get("messages", []))
        page_token = resp.get("nextPageToken")
        if not page_token:
            return messages

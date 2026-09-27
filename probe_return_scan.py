"""
One-off test: scan Gmail for Amazon return/refund emails and see what we can extract.
"""

import base64
import json
import re
from pathlib import Path

from dotenv import load_dotenv
load_dotenv()

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build

TOKEN_FILE = "token.json"
SCOPES = ["https://www.googleapis.com/auth/gmail.readonly"]
ORDER_RE = re.compile(r"\b(\d{3}-\d{7}-\d{7})\b")

def get_service():
    creds = Credentials.from_authorized_user_file(TOKEN_FILE, SCOPES)
    if creds.expired and creds.refresh_token:
        creds.refresh(Request())
        Path(TOKEN_FILE).write_text(creds.to_json())
    return build("gmail", "v1", credentials=creds)

def decode_body(msg):
    def _extract(payload):
        mime = payload.get("mimeType", "")
        data = payload.get("body", {}).get("data", "")
        if mime == "text/plain" and data:
            return base64.urlsafe_b64decode(data + "==").decode("utf-8", errors="replace")
        if mime == "text/html" and data:
            html = base64.urlsafe_b64decode(data + "==").decode("utf-8", errors="replace")
            return re.sub(r"<[^>]+>", " ", html)
        for part in payload.get("parts", []):
            result = _extract(part)
            if result:
                return result
        return ""
    return _extract(msg.get("payload", {}))

def get_header(msg, name):
    headers = msg.get("payload", {}).get("headers", [])
    return next((h["value"] for h in headers if h["name"].lower() == name.lower()), "")

service = get_service()

# Try a few different queries to see what Amazon return emails look like
queries = [
    'from:amazon.com after:2025/07/01 subject:return',
    'from:amazon.com after:2025/07/01 subject:refund',
    'from:(auto-confirm@amazon.com) after:2025/07/01 return',
]

print("=" * 70)
found = {}  # order_number -> list of subjects

for query in queries:
    print(f"\nQuery: {query}")
    results = service.users().messages().list(userId="me", q=query, maxResults=50).execute()
    messages = results.get("messages", [])
    print(f"  → {len(messages)} message(s)")

    for ref in messages[:20]:  # sample first 20
        msg = service.users().messages().get(userId="me", id=ref["id"], format="full").execute()
        subject = get_header(msg, "Subject")
        sender = get_header(msg, "From")
        date = get_header(msg, "Date")
        body = decode_body(msg)
        full_text = f"{subject}\n{body}"

        order_numbers = ORDER_RE.findall(full_text)

        print(f"\n  Subject: {subject}")
        print(f"  From:    {sender}")
        print(f"  Date:    {date[:30]}")
        print(f"  Orders:  {order_numbers or '(none found)'}")

        # Print a snippet of the body to see structure
        snippet = " ".join(body.split())[:300]
        print(f"  Body:    {snippet}...")

        for on in order_numbers:
            found.setdefault(on, []).append(subject)

print("\n" + "=" * 70)
print(f"\nOrder numbers found across all return/refund emails: {len(found)}")
for on, subjects in list(found.items())[:20]:
    print(f"  {on}: {subjects[0][:60]}")

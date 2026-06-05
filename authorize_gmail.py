#!/usr/bin/env python3
"""
One-time Gmail OAuth authorization for the Amazon scanner.

If you already have token.json from the pickem app and it was authorized
with gmail.modify or gmail.readonly scope, you can just copy it here instead.

Otherwise run this script once:
    python authorize_gmail.py

It opens a browser window — sign in and approve access. Saves token.json.
"""
import os
from pathlib import Path

from google_auth_oauthlib.flow import InstalledAppFlow

SCOPES = ["https://www.googleapis.com/auth/gmail.readonly"]
OAUTH_CREDS_FILE = os.environ.get("GMAIL_OAUTH_CREDS_FILE", "gmail_oauth_credentials.json")
TOKEN_FILE = os.environ.get("GMAIL_TOKEN_FILE", "token.json")


def main():
    if not Path(OAUTH_CREDS_FILE).exists():
        print(f"ERROR: {OAUTH_CREDS_FILE} not found.")
        print()
        print("Option 1 (easiest): Copy gmail_oauth_credentials.json and token.json")
        print("  from the pickem app folder into this folder.")
        print()
        print("Option 2: Create new OAuth credentials:")
        print("  1. Go to console.cloud.google.com")
        print("  2. APIs & Services → Credentials → your OAuth 2.0 client")
        print("  3. Download JSON, rename to gmail_oauth_credentials.json, place here")
        print("  4. Re-run this script")
        return

    flow = InstalledAppFlow.from_client_secrets_file(OAUTH_CREDS_FILE, SCOPES)
    creds = flow.run_local_server(port=0)
    Path(TOKEN_FILE).write_text(creds.to_json())
    print(f"\nSuccess! {TOKEN_FILE} saved. Amazon scanner is ready.")


if __name__ == "__main__":
    main()

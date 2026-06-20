#!/usr/bin/env python3
"""
One-time Gmail OAuth authorization for the Amazon scanner.

If you already have token.json from the pickem app and it was authorized
with gmail.modify or gmail.readonly scope, you can just copy it here instead.

Otherwise run this script once:
    python authorize_gmail.py

It opens a browser window — sign in and approve access. Saves token.json.
"""
from pathlib import Path

from src.gmail_auth import OAUTH_CREDS_FILE, TOKEN_FILE, reauthorize


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

    email = reauthorize()
    suffix = f" ({email})" if email else ""
    print(f"\nSuccess! {TOKEN_FILE} saved{suffix}. Gmail scanners are ready.")


if __name__ == "__main__":
    main()

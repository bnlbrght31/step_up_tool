"""
Gmail OAuth helpers shared by the web app and the CLI.

- token_status(): report whether token.json is authorized / expired / missing
  (and silently refresh it if it's merely expired but still refreshable).
- reauthorize(): run the interactive browser OAuth flow and (re)write token.json.

Paths are relative to the working directory (the project folder), matching the
rest of the project (service_account.json, etc.).
"""

import os
from pathlib import Path

SCOPES = ["https://www.googleapis.com/auth/gmail.readonly"]
OAUTH_CREDS_FILE = os.environ.get("GMAIL_OAUTH_CREDS_FILE", "gmail_oauth_credentials.json")
TOKEN_FILE = os.environ.get("GMAIL_TOKEN_FILE", "token.json")


def _load_creds():
    from google.oauth2.credentials import Credentials
    if not Path(TOKEN_FILE).exists():
        return None
    return Credentials.from_authorized_user_file(TOKEN_FILE, SCOPES)


def _email(creds):
    """Best-effort: which Gmail account this token belongs to (None on any error)."""
    try:
        from googleapiclient.discovery import build
        svc = build("gmail", "v1", credentials=creds, cache_discovery=False)
        return svc.users().getProfile(userId="me").execute().get("emailAddress")
    except Exception:
        return None


def token_status() -> dict:
    """
    Return {"state": ..., "email": ..., "detail": ...}.

    state is one of:
      authorized — token.json is valid (refreshed in place if needed)
      expired    — token exists but is revoked/expired and cannot refresh
      missing    — no token.json yet (never authorized)
      no_creds   — gmail_oauth_credentials.json is missing (can't authorize)
      error      — token.json is present but unreadable
    """
    if not Path(OAUTH_CREDS_FILE).exists():
        return {"state": "no_creds", "detail": f"{OAUTH_CREDS_FILE} not found"}

    try:
        creds = _load_creds()
    except Exception as e:
        return {"state": "error", "detail": str(e)}

    if creds is None:
        return {"state": "missing", "detail": "No token.json yet — needs first authorization"}

    if creds.valid:
        return {"state": "authorized", "email": _email(creds)}

    if creds.expired and creds.refresh_token:
        from google.auth.transport.requests import Request
        try:
            creds.refresh(Request())
            Path(TOKEN_FILE).write_text(creds.to_json())
            return {"state": "authorized", "email": _email(creds)}
        except Exception as e:
            return {"state": "expired", "detail": str(e)}

    return {"state": "expired", "detail": "Token is invalid and cannot be refreshed"}


def reauthorize(timeout_seconds: int = 300) -> str | None:
    """
    Run the interactive OAuth flow (opens a browser), write token.json, and
    return the authorized email (best-effort). Raises FileNotFoundError if the
    OAuth client secrets file is missing.
    """
    from google_auth_oauthlib.flow import InstalledAppFlow
    if not Path(OAUTH_CREDS_FILE).exists():
        raise FileNotFoundError(f"{OAUTH_CREDS_FILE} not found")
    flow = InstalledAppFlow.from_client_secrets_file(OAUTH_CREDS_FILE, SCOPES)
    creds = flow.run_local_server(
        port=0,
        open_browser=True,
        timeout_seconds=timeout_seconds,
        success_message="Gmail authorized. You can close this tab and return to the SUFS app.",
    )
    Path(TOKEN_FILE).write_text(creds.to_json())
    return _email(creds)

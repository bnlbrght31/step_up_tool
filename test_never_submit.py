"""
Regression guard for the single most important safety rule of this project:
the agent fills the SUFS reimbursement form but NEVER submits it.

`fill_form`/`_fill_item` drive the user's real logged-in browser, so a stray
click on a Submit control would silently file a reimbursement. This static check
fails if browser_agent.py ever interacts with a Submit control, and verifies it
still hands the window back for manual review.

Run: python test_never_submit.py   (or: pytest test_never_submit.py)
"""

from pathlib import Path

SRC = Path(__file__).parent / "src" / "browser_agent.py"

# Tokens that contain "submit" but are NOT a submit action (e.g. the page URL path).
SAFE_TOKENS = ("submitreimbursement",)

# Markers that mean "this line clicks or targets an element".
INTERACTION = (
    ".click(", "dispatchevent", "mouseevent",
    "get_by_role", "get_by_text", "get_by_label", "locator(",
    'type="submit"', "type='submit'", "type=submit", "[type=submit]",
    "name=", ">submit<",
)


def _offenders() -> list[tuple[int, str]]:
    hits = []
    for n, raw in enumerate(SRC.read_text().splitlines(), 1):
        low = raw.lower()
        for tok in SAFE_TOKENS:
            low = low.replace(tok, "")
        if "submit" in low and any(m in low for m in INTERACTION):
            hits.append((n, raw.strip()))
    return hits


def test_fill_never_targets_submit():
    """No line in browser_agent.py may click or target a Submit control."""
    offenders = _offenders()
    assert not offenders, (
        "The 'never submit the form' invariant looks broken — browser_agent.py "
        f"appears to interact with a Submit control: {offenders}"
    )


def test_fill_hands_off_for_manual_review():
    """fill_form must end by surfacing the window for the user to submit manually."""
    assert "bring_to_front" in SRC.read_text(), (
        "fill_form must hand the window back for manual review (no auto-submit)."
    )


if __name__ == "__main__":
    test_fill_never_targets_submit()
    test_fill_hands_off_for_manual_review()
    print("OK — never-submit invariant holds; window is handed off for manual review.")

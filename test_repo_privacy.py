"""
Guards the public GitHub repo against personal purchase data.

Amazon order numbers identify real orders on the owner's account, so tracked
files may only use obviously fake ones of the form 111-0000NNN-0000NNN.

Run: python test_repo_privacy.py   (or: pytest test_repo_privacy.py)
"""

import re
import subprocess
from pathlib import Path

ROOT = Path(__file__).parent
ORDER_NUMBER = re.compile(r"\b\d{3}-\d{7}-\d{7}\b")
PLACEHOLDER = re.compile(r"111-0000\d{3}-0000\d{3}")


def _tracked_text_files():
    names = subprocess.run(["git", "ls-files"], cwd=ROOT, capture_output=True,
                           text=True, check=True).stdout.splitlines()
    for name in names:
        try:
            yield name, (ROOT / name).read_text()
        except (UnicodeDecodeError, FileNotFoundError):
            continue  # binary, or deleted in the working tree


def test_no_real_amazon_order_numbers_in_tracked_files():
    leaks = [f"{name}: {m}" for name, text in _tracked_text_files()
             for m in ORDER_NUMBER.findall(text) if not PLACEHOLDER.fullmatch(m)]
    assert not leaks, "real-looking order numbers:\n  " + "\n  ".join(leaks)


if __name__ == "__main__":
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    for t in tests:
        t()
        print(f"  ok  {t.__name__}")
    print(f"OK — {len(tests)} test passed; no personal order numbers in the repo.")

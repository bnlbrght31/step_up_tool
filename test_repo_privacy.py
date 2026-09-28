"""
Guards the public GitHub repo against personal data.

- Amazon order numbers identify real orders on the owner's account, so tracked
  files may only use obviously fake ones of the form 111-0000NNN-0000NNN.
- Absolute paths into a home folder (/Users/<name>/..., /home/<name>/...) reveal
  the owner's username and folder layout; code must locate files relative to
  itself or to the home folder instead.

Run: python test_repo_privacy.py   (or: pytest test_repo_privacy.py)
"""

import re
import subprocess
from pathlib import Path

ROOT = Path(__file__).parent
ORDER_NUMBER = re.compile(r"\b\d{3}-\d{7}-\d{7}\b")
PLACEHOLDER = re.compile(r"111-0000\d{3}-0000\d{3}")
# Built from parts so this file's own source never matches it.
HOME_PATH = re.compile(r"/(?:Users|home)/" + r"[A-Za-z0-9._-]+")


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


def test_no_home_folder_paths_in_tracked_files():
    leaks = [f"{name}:{n}: {line.strip()[:90]}"
             for name, text in _tracked_text_files()
             for n, line in enumerate(text.splitlines(), 1) if HOME_PATH.search(line)]
    assert not leaks, "absolute home-folder paths:\n  " + "\n  ".join(leaks)


if __name__ == "__main__":
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    for t in tests:
        t()
        print(f"  ok  {t.__name__}")
    print(f"OK — {len(tests)} tests passed; no personal order numbers or home paths in the repo.")

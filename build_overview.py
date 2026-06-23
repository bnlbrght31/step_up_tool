"""Rebuild the Overview dashboard tab from the current Line Items data.

    python build_overview.py
"""
from dotenv import load_dotenv

load_dotenv()

from src.overview import refresh_overview

if __name__ == "__main__":
    print(refresh_overview())

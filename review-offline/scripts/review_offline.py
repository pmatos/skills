#!/usr/bin/env python3
"""Entry point: prepare a changeset, validate the graph, serve the review page."""

import sys
from pathlib import Path

if sys.version_info < (3, 11):
    print("REVIEW-ERROR review-offline needs Python 3.11 or newer", flush=True)
    raise SystemExit(1)

sys.path.insert(0, str(Path(__file__).resolve().parent))

from review_offline.cli import main

if __name__ == "__main__":
    raise SystemExit(main())

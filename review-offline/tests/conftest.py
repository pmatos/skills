import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))


def pytest_configure(config):
    config.addinivalue_line(
        "markers", "smoke: runs the real host CLIs; needs REVIEW_OFFLINE_SMOKE=1"
    )

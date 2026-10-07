import shutil
import subprocess
from pathlib import Path

import pytest

CHECK = Path(__file__).parent / "js" / "layout.check.js"


@pytest.mark.skipif(shutil.which("node") is None, reason="node not installed")
def test_layout_invariants_on_fixtures():
    result = subprocess.run(["node", str(CHECK)], capture_output=True, text=True, check=False)
    assert result.returncode == 0, result.stderr

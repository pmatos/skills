import shutil
import subprocess

import pytest
from review_offline.assets import PAGE_DIR, SCRIPTS, build_shell


def test_shell_inlines_everything_and_no_review_data():
    shell = build_shell()
    assert "/*STYLE*/" not in shell and "/*SCRIPT*/" not in shell
    assert "htmPreact" in shell and "ro-viz" in shell
    assert "src=" not in shell and "<link" not in shell


@pytest.mark.skipif(shutil.which("node") is None, reason="node not installed")
@pytest.mark.parametrize("name", [s for s in SCRIPTS if not s.startswith("vendor/")])
def test_page_scripts_parse(name):
    result = subprocess.run(
        ["node", "--check", str(PAGE_DIR / name)], capture_output=True, text=True, check=False
    )
    assert result.returncode == 0, result.stderr


def test_no_unsafe_html_sinks_in_page_code():
    for name in SCRIPTS:
        if name.startswith("vendor/"):
            continue
        text = (PAGE_DIR / name).read_text(encoding="utf-8")
        assert "dangerouslySetInnerHTML" not in text, name
        assert "innerHTML" not in text, name
        assert "eval(" not in text, name

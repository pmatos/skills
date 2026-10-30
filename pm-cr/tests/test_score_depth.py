import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "score_depth.py"
GIT_ENV = {
    "GIT_AUTHOR_NAME": "t",
    "GIT_AUTHOR_EMAIL": "t@example.com",
    "GIT_COMMITTER_NAME": "t",
    "GIT_COMMITTER_EMAIL": "t@example.com",
    "GIT_CONFIG_GLOBAL": os.devnull,
    "GIT_CONFIG_NOSYSTEM": "1",
}


class Repo:
    def __init__(self, root):
        self.root = root
        self.git("init", "-q", "-b", "main")

    def git(self, *args):
        subprocess.run(
            ["git", *args],
            cwd=self.root,
            check=True,
            capture_output=True,
            env={**os.environ, **GIT_ENV},
        )

    def write(self, path, lines):
        full = self.root / path
        full.parent.mkdir(parents=True, exist_ok=True)
        full.write_text("".join(f"line {i}\n" for i in range(lines)))

    def commit(self, message="c"):
        self.git("add", "-A")
        self.git("commit", "-q", "-m", message)

    def score(self, *extra, base="main", cwd=None):
        result = subprocess.run(
            [sys.executable, "-I", str(SCRIPT), "--base", base, *extra],
            check=False,
            cwd=cwd or self.root,
            capture_output=True,
            text=True,
            env={**os.environ, **GIT_ENV},
        )
        assert result.returncode == 0, result.stderr
        return json.loads(result.stdout)


@pytest.fixture
def repo(tmp_path):
    r = Repo(tmp_path)
    r.write("src/app.py", 10)
    r.commit("base")
    r.git("switch", "-q", "-c", "feature")
    return r


@pytest.fixture
def tested_repo(repo):
    repo.write("tests/test_app.py", 5)
    repo.git("switch", "-q", "main")
    repo.commit("add tests")
    repo.git("switch", "-q", "feature")
    repo.git("merge", "-q", "main")
    return repo


def test_small_doc_change_is_low(repo):
    repo.write("docs/guide.md", 5)
    repo.commit()
    assert repo.score()["level"] == "low"


def test_mid_sized_change_with_tests_is_medium(tested_repo):
    tested_repo.write("src/feature.py", 80)
    tested_repo.write("tests/test_feature.py", 40)
    tested_repo.commit()
    out = tested_repo.score()
    assert out["level"] == "medium"
    assert out["signals"]["untested"] is False


def test_untested_code_raises_one_level(tested_repo):
    tested_repo.write("src/feature.py", 80)
    tested_repo.commit()
    out = tested_repo.score()
    assert out["size_level"] == "medium"
    assert out["signals"]["untested"] is True
    assert out["level"] == "high"


def test_untested_is_ignored_without_tests_in_base(repo):
    repo.write("src/feature.py", 80)
    repo.commit()
    out = repo.score()
    assert out["signals"]["base_has_tests"] is False
    assert out["level"] == "medium"


def test_untested_ignores_docs_and_config(tested_repo):
    tested_repo.write("docs/guide.md", 80)
    tested_repo.write("config/app.yaml", 20)
    tested_repo.commit()
    out = tested_repo.score()
    assert out["signals"]["untested"] is False
    assert out["level"] == "medium"


def test_size_alone_never_exceeds_high(repo):
    for i in range(30):
        repo.write(f"pkg{i % 5}/mod{i}.py", 50)
    repo.commit()
    assert repo.score()["level"] == "high"


def test_small_workflow_change_is_high(repo):
    repo.write(".github/workflows/ci.yml", 3)
    repo.commit()
    out = repo.score()
    assert out["size_level"] == "low"
    assert out["signals"]["high_stakes"][0]["pattern"] == ".github/workflows/*"
    assert out["level"] == "high"


def test_mid_sized_workflow_change_is_xhigh(repo):
    repo.write(".github/workflows/ci.yml", 100)
    repo.commit()
    assert repo.score()["level"] == "xhigh"


def test_lockfile_is_excluded_from_size_but_high_stakes(repo):
    repo.write("uv.lock", 5000)
    repo.commit()
    out = repo.score()
    assert out["signals"]["lines"] == 0
    assert out["signals"]["excluded"] == [{"path": "uv.lock", "reason": "lockfile"}]
    assert out["level"] == "high"


def test_instruction_file_edit_is_at_least_medium(repo):
    repo.write("CLAUDE.md", 3)
    repo.commit()
    out = repo.score()
    assert out["size_level"] == "low"
    assert out["level"] == "medium"


def test_review_md_paths_come_from_the_base(repo):
    repo.git("switch", "-q", "main")
    (repo.root / "REVIEW.md").write_text(
        "# Review\n\n## High-stakes paths\n\n- `src/auth/*`\n\n## Other\n\n- `src/x/*`\n"
    )
    repo.commit("review rules")
    repo.git("switch", "-q", "feature")
    repo.git("merge", "-q", "main")
    (repo.root / "REVIEW.md").write_text("# Review\n")
    repo.write("src/auth/login.py", 5)
    repo.commit()
    out = repo.score()
    assert out["signals"]["review_md_patterns"] == ["src/auth/*"]
    assert {"path": "src/auth/login.py", "pattern": "src/auth/*", "source": "REVIEW.md"} in out[
        "signals"
    ]["high_stakes"]
    assert out["level"] == "high"


def test_uncommitted_and_untracked_files_count(repo):
    repo.write("src/app.py", 15)
    repo.write("src/new.py", 40)
    out = repo.score()
    assert out["signals"]["files"] == 2
    assert out["signals"]["lines"] == 5 + 40


def test_path_target_narrows_the_scope(repo):
    repo.write("src/feature.py", 5)
    repo.write(".github/workflows/ci.yml", 3)
    repo.commit()
    out = repo.score("--path", ".", cwd=repo.root / "src")
    assert out["signals"]["files"] == 1
    assert out["signals"]["high_stakes"] == []


def test_pure_rename_counts_no_lines(repo):
    repo.git("mv", "src/app.py", "src/main.py")
    repo.commit()
    out = repo.score()
    assert out["signals"]["lines"] == 0
    assert out["level"] == "low"


def test_unknown_base_fails(repo):
    result = subprocess.run(
        [sys.executable, "-I", str(SCRIPT), "--base", "nope"],
        check=False,
        cwd=repo.root,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 1
    assert "score_depth:" in result.stderr

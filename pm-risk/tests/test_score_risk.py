import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "score_risk.py"
GIT_ENV = {
    "GIT_AUTHOR_NAME": "t",
    "GIT_AUTHOR_EMAIL": "t@example.com",
    "GIT_COMMITTER_NAME": "t",
    "GIT_COMMITTER_EMAIL": "t@example.com",
    "GIT_CONFIG_GLOBAL": os.devnull,
    "GIT_CONFIG_NOSYSTEM": "1",
}


def run(args, cwd):
    return subprocess.run(
        [sys.executable, "-I", str(SCRIPT), *args],
        check=False,
        cwd=cwd,
        capture_output=True,
        text=True,
        env={**os.environ, **GIT_ENV},
    )


class Repo:
    def __init__(self, root):
        self.root = root

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

    def on_main(self, fn):
        self.git("switch", "-q", "main")
        fn()
        self.commit("on main")
        self.git("switch", "-q", "feature")
        self.git("merge", "-q", "main")

    def score(self, *extra, base="main", cwd=None):
        result = run(["--base", base, *extra], cwd or self.root)
        assert result.returncode == 0, result.stderr
        return json.loads(result.stdout)


@pytest.fixture
def repo(tmp_path):
    r = Repo(tmp_path / "repo")
    r.root.mkdir()
    r.git("init", "-q", "-b", "main")
    r.write("src/app.py", 10)
    r.commit("base")
    r.git("switch", "-q", "-c", "feature")
    return r


@pytest.fixture
def tested_repo(repo):
    repo.on_main(lambda: repo.write("tests/test_app.py", 5))
    return repo


def test_small_doc_change_is_low(repo):
    repo.write("docs/guide.md", 5)
    repo.commit()
    assert repo.score()["risk"] == "low"


def test_mid_sized_change_with_tests_is_medium(tested_repo):
    tested_repo.write("src/feature.py", 80)
    tested_repo.write("tests/test_feature.py", 40)
    tested_repo.commit()
    out = tested_repo.score()
    assert out["risk"] == "medium"
    assert out["signals"]["untested"] is False


def test_untested_code_raises_one_level(tested_repo):
    tested_repo.write("src/feature.py", 80)
    tested_repo.commit()
    out = tested_repo.score()
    assert out["size_risk"] == "medium"
    assert out["signals"]["untested"] is True
    assert out["risk"] == "high"


def test_untested_is_ignored_without_tests_in_base(repo):
    repo.write("src/feature.py", 80)
    repo.commit()
    out = repo.score()
    assert out["signals"]["base_has_tests"] is False
    assert out["risk"] == "medium"


def test_spec_docs_are_not_tests(repo):
    repo.on_main(lambda: repo.write("docs/specs/design.md", 5))
    repo.write("src/feature.py", 30)
    repo.commit()
    out = repo.score()
    assert out["signals"]["base_has_tests"] is False
    assert out["signals"]["untested"] is False


def test_renamed_test_counts_as_a_test_change(tested_repo):
    tested_repo.write("src/app.py", 11)
    tested_repo.git("mv", "tests/test_app.py", "tests/test_app_renamed.py")
    tested_repo.commit()
    out = tested_repo.score()
    assert out["signals"]["test_files"] == 1
    assert out["signals"]["untested"] is False


def test_untested_ignores_docs_and_config(tested_repo):
    tested_repo.write("docs/guide.md", 80)
    tested_repo.write("config/app.yaml", 20)
    tested_repo.write(".editorconfig", 5)
    tested_repo.commit()
    out = tested_repo.score()
    assert out["signals"]["untested"] is False
    assert out["risk"] == "medium"


def test_extensionless_script_is_code(tested_repo):
    tested_repo.write("bin/deploy", 30)
    tested_repo.commit()
    out = tested_repo.score()
    assert out["signals"]["code_lines"] == 30
    assert out["signals"]["untested"] is True


def test_size_alone_never_exceeds_high(repo):
    for i in range(30):
        repo.write(f"pkg{i % 5}/mod{i}.py", 50)
    repo.commit()
    assert repo.score()["risk"] == "high"


def test_small_workflow_change_is_high(repo):
    repo.write(".github/workflows/ci.yml", 3)
    repo.commit()
    out = repo.score()
    assert out["size_risk"] == "low"
    assert out["signals"]["high_stakes"][0]["rule"] == ".github/workflows/*"
    assert out["risk"] == "high"


def test_mid_sized_workflow_change_is_critical(repo):
    repo.write(".github/workflows/ci.yml", 100)
    repo.commit()
    assert repo.score()["risk"] == "critical"


@pytest.mark.parametrize(
    "path",
    [
        "API.Dockerfile",
        "Dockerfile.prod",
        "services/billing/db/migrate/20260101_x.rb",
        ".github/dependabot.yml",
        "Pipfile",
    ],
)
def test_deploy_and_dependency_spellings_are_high_stakes(repo, path):
    repo.write(path, 3)
    repo.commit()
    assert repo.score()["risk"] == "high"


def test_lockfile_is_excluded_from_size_but_high_stakes(repo):
    repo.write("uv.lock", 5000)
    repo.commit()
    out = repo.score()
    assert out["signals"]["lines"] == 0
    assert out["signals"]["excluded"] == [{"path": "uv.lock", "reason": "lockfile"}]
    assert out["risk"] == "high"


def test_vendored_code_is_excluded_from_size_but_high_stakes(repo):
    repo.write("vendor/lib/big.php", 5000)
    repo.commit()
    out = repo.score()
    assert out["signals"]["lines"] == 0
    assert out["signals"]["high_stakes"][0]["rule"] == "third-party directory"
    assert out["risk"] == "high"


def test_generated_code_is_excluded_and_not_untested(tested_repo):
    tested_repo.write("src/api_pb2.py", 3000)
    tested_repo.commit()
    out = tested_repo.score()
    assert out["signals"]["lines"] == 0
    assert out["risk"] == "low"


def test_instruction_file_edit_is_at_least_medium(repo):
    repo.write("CLAUDE.md", 3)
    repo.commit()
    out = repo.score()
    assert out["size_risk"] == "low"
    assert out["risk"] == "medium"


def test_review_md_paths_come_from_the_base(repo):
    def rules():
        (repo.root / "REVIEW.md").write_text(
            "# Review\n\n## High-stakes paths\n\n"
            "- `src/auth/*` (see `docs/auth.md`)\n"
            "- `./billing/`\n\n"
            "```sh\n# not a heading\n```\n\n"
            "- `/payments/*`\n\n## Other\n\n- `src/x/*`\n"
        )

    repo.on_main(rules)
    (repo.root / "REVIEW.md").write_text("# Review\n")
    repo.write("src/auth/login.py", 5)
    repo.commit()
    out = repo.score()
    assert out["signals"]["review_md_patterns"] == ["src/auth/*", "billing/*", "payments/*"]
    hit = {"path": "src/auth/login.py", "rule": "src/auth/*", "source": "REVIEW.md"}
    assert hit in out["signals"]["high_stakes"]
    assert out["risk"] == "high"


def test_uncommitted_and_untracked_files_count(repo):
    repo.write("src/app.py", 15)
    repo.write("src/new.py", 40)
    out = repo.score()
    assert out["signals"]["files"] == 2
    assert out["signals"]["lines"] == 5 + 40


def test_head_scores_a_branch_without_checking_it_out(repo):
    repo.write(".github/workflows/ci.yml", 3)
    repo.commit()
    repo.git("switch", "-q", "main")
    repo.write("scratch.py", 500)
    out = repo.score("--head", "feature")
    assert out["signals"]["files"] == 1
    assert out["risk"] == "high"


def test_path_target_narrows_the_scope(repo):
    repo.write("src/feature.py", 5)
    repo.write(".github/workflows/ci.yml", 3)
    repo.commit()
    out = repo.score("--path", ".", cwd=repo.root / "src")
    assert out["signals"]["files"] == 1
    assert out["signals"]["high_stakes"] == []


def test_path_through_a_symlink_resolves(repo, tmp_path):
    alias = tmp_path / "alias"
    alias.symlink_to(repo.root)
    repo.write("src/feature.py", 5)
    repo.commit()
    out = repo.score("--path", str(alias / "src"))
    assert out["path"] == "src"
    assert out["signals"]["files"] == 1


def test_unreadable_untracked_file_does_not_crash(repo):
    repo.write("src/secret.py", 5)
    (repo.root / "src/secret.py").chmod(0)
    try:
        repo.score()
    finally:
        (repo.root / "src/secret.py").chmod(0o644)


def test_pure_rename_counts_no_lines(repo):
    repo.git("mv", "src/app.py", "src/main.py")
    repo.commit()
    out = repo.score()
    assert out["signals"]["lines"] == 0
    assert out["risk"] == "low"


def test_unknown_base_fails(repo):
    result = run(["--base", "nope"], repo.root)
    assert result.returncode == 1
    assert "score_risk:" in result.stderr

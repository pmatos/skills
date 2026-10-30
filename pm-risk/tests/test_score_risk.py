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
        return subprocess.run(
            ["git", *args],
            cwd=self.root,
            check=True,
            capture_output=True,
            text=True,
            env={**os.environ, **GIT_ENV},
        ).stdout

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


def test_small_doc_change_has_a_low_floor(repo):
    repo.write("docs/guide.md", 5)
    repo.commit()
    out = repo.score()
    assert out["floor"] == "low"
    assert out["signals"]["size"] == "low"


def test_size_is_a_fact_not_a_floor(repo):
    for i in range(30):
        repo.write(f"pkg{i % 5}/mod{i}.py", 50)
    repo.commit()
    out = repo.score()
    assert out["signals"]["size"] == "high"
    assert out["floor"] == "low"
    assert out["facts"][0].startswith("size high: 1500 lines in 30 files")


def test_untested_code_is_a_fact(tested_repo):
    tested_repo.write("src/feature.py", 80)
    tested_repo.commit()
    out = tested_repo.score()
    assert out["signals"]["untested"] is True
    assert "untested: 80 code lines changed and no test file changed" in out["facts"]
    assert out["floor"] == "low"


def test_untested_needs_tests_in_the_base(repo):
    repo.write("src/feature.py", 80)
    repo.commit()
    out = repo.score()
    assert out["signals"]["base_has_tests"] is False
    assert out["signals"]["untested"] is False


def test_spec_docs_are_not_tests(repo):
    repo.on_main(lambda: repo.write("docs/specs/design.md", 5))
    repo.write("src/feature.py", 30)
    repo.commit()
    assert repo.score()["signals"]["base_has_tests"] is False


@pytest.mark.parametrize("path", ["Tests/FooTests.swift", "src/FooTest.java", "app/tests.py"])
def test_other_test_layouts_are_tests(repo, path):
    repo.on_main(lambda: repo.write(path, 5))
    repo.write("src/feature.py", 30)
    repo.commit()
    assert repo.score()["signals"]["untested"] is True


def test_latest_is_not_a_test(repo):
    repo.on_main(lambda: repo.write("src/latest.py", 5))
    repo.write("src/feature.py", 30)
    repo.commit()
    assert repo.score()["signals"]["base_has_tests"] is False


def test_renamed_test_counts_as_a_test_change(tested_repo):
    tested_repo.write("src/app.py", 11)
    tested_repo.git("mv", "tests/test_app.py", "tests/test_app_renamed.py")
    tested_repo.commit()
    out = tested_repo.score()
    assert out["signals"]["test_files"] == 1
    assert out["signals"]["untested"] is False


def test_deleted_test_is_not_coverage(tested_repo):
    tested_repo.write("src/app.py", 15)
    tested_repo.git("rm", "-q", "tests/test_app.py")
    tested_repo.commit()
    out = tested_repo.score()
    assert out["signals"]["test_files"] == 0
    assert out["signals"]["untested"] is True


def test_tests_outside_a_path_target_count(tested_repo):
    tested_repo.write("src/new.py", 50)
    tested_repo.write("tests/test_new.py", 10)
    tested_repo.commit()
    out = tested_repo.score("--path", "src")
    assert out["signals"]["files"] == 1
    assert out["signals"]["untested"] is False


def test_docs_config_and_dotfiles_are_not_code(tested_repo):
    tested_repo.write("docs/guide.md", 80)
    tested_repo.write("config/app.yaml", 20)
    tested_repo.write(".editorconfig", 5)
    tested_repo.commit()
    assert tested_repo.score()["signals"]["code_lines"] == 0


@pytest.mark.parametrize(
    ("path", "code"),
    [
        ("src/authors.py", True),
        ("app/license_check.py", True),
        ("LICENSE", False),
        ("README.md", False),
        ("Dockerfile", False),
        ("go.mod", False),
        ("infra/main.tf", False),
    ],
)
def test_code_classification(tested_repo, path, code):
    tested_repo.write(path, 10)
    tested_repo.commit()
    assert (tested_repo.score()["signals"]["code_lines"] > 0) is code


def test_spec_documents_are_not_tests(tested_repo):
    tested_repo.write("src/feature.py", 30)
    tested_repo.write("api/openapi.spec.yaml", 30)
    tested_repo.commit()
    assert tested_repo.score()["signals"]["untested"] is True


def test_rspec_spec_dir_is_tests(repo):
    repo.on_main(lambda: repo.write("spec/spec_helper.rb", 5))
    repo.write("src/feature.py", 30)
    repo.commit()
    assert repo.score()["signals"]["untested"] is True


def test_vendored_tests_do_not_count_as_repo_tests(repo):
    repo.on_main(lambda: repo.write("vendor/lib/tests/test_lib.py", 5))
    repo.write("src/feature.py", 30)
    repo.commit()
    assert repo.score()["signals"]["base_has_tests"] is False


def test_a_lowercase_review_page_is_not_an_instruction_file(repo):
    repo.write("reviews/review.md", 3)
    repo.commit()
    assert repo.score()["floor"] == "low"


def test_extensionless_script_is_code(tested_repo):
    tested_repo.write("bin/deploy", 30)
    tested_repo.commit()
    assert tested_repo.score()["signals"]["code_lines"] == 30


def test_workflow_change_has_a_high_floor(repo):
    repo.write(".github/workflows/ci.yml", 3)
    repo.commit()
    out = repo.score()
    assert out["floor"] == "high"
    assert out["signals"]["high_stakes"][0]["rule"] == ".github/workflows/*"


@pytest.mark.parametrize(
    "path",
    [
        "API.Dockerfile",
        "Dockerfile.prod",
        "Containerfile",
        "services/billing/db/migrate/20260101_x.rb",
        ".github/dependabot.yml",
        ".github/scripts/release.sh",
        "action.yml",
        "Pipfile",
        "requirements/base.txt",
        "services/api/requirements/base.txt",
        ".npmrc",
        ".claude/settings.json",
        ".mcp.json",
        ".gitmodules",
        ".github/CODEOWNERS",
        ".husky/pre-commit",
    ],
)
def test_deploy_and_dependency_spellings_are_high_stakes(repo, path):
    repo.write(path, 3)
    repo.commit()
    assert repo.score()["floor"] == "high"


def test_manifests_under_tests_are_not_high_stakes(repo):
    repo.write("tests/fixtures/package.json", 3)
    repo.commit()
    assert repo.score()["floor"] == "low"


@pytest.mark.parametrize(
    "path", [".github/actions/test/action.yml", ".github/scripts/run_test.sh", "e2e/package.json"]
)
def test_automation_and_real_packages_are_never_fixtures(repo, path):
    repo.write(path, 3)
    repo.commit()
    out = repo.score()
    assert out["floor"] == "high"
    assert out["signals"]["test_files"] == 0


@pytest.mark.parametrize("path", ["vendor/x/tests/test_x.py", ".github/scripts/run_test.sh"])
def test_vendored_and_ci_files_are_not_test_changes(tested_repo, path):
    tested_repo.write("src/feature.py", 100)
    tested_repo.write(path, 5)
    tested_repo.commit()
    assert tested_repo.score()["signals"]["untested"] is True


def test_lockfile_is_excluded_from_size_but_high_stakes(repo):
    repo.write("uv.lock", 5000)
    repo.commit()
    out = repo.score()
    assert out["signals"]["lines"] == 0
    assert out["signals"]["excluded"] == [{"path": "uv.lock", "reason": "lockfile"}]
    assert out["floor"] == "high"


def test_vendored_code_is_excluded_from_size_but_high_stakes(repo):
    repo.write("vendor/lib/big.php", 5000)
    repo.commit()
    out = repo.score()
    assert out["signals"]["lines"] == 0
    assert out["signals"]["high_stakes"][0]["rule"] == "third-party directory"


def test_generated_code_is_excluded(repo):
    repo.write("src/api_pb2.py", 3000)
    repo.commit()
    out = repo.score()
    assert out["signals"]["lines"] == 0
    assert out["floor"] == "low"


def test_long_lists_are_capped(repo):
    for i in range(30):
        repo.write(f"vendor/lib{i}.php", 1)
    repo.commit()
    out = repo.score()
    assert len(out["signals"]["high_stakes"]) == 20
    assert out["signals"]["high_stakes_total"] == 30


def test_instruction_file_edit_has_a_medium_floor(repo):
    repo.write("CLAUDE.md", 3)
    repo.commit()
    assert repo.score()["floor"] == "medium"


def test_renaming_an_instruction_file_names_it(repo):
    repo.on_main(lambda: repo.write("CLAUDE.md", 3))
    (repo.root / "docs").mkdir(exist_ok=True)
    repo.git("mv", "CLAUDE.md", "docs/notes.md")
    repo.commit()
    out = repo.score()
    assert out["signals"]["instruction_files"] == ["CLAUDE.md"]
    assert out["floor_reason"] == "edits CLAUDE.md"


def test_review_md_paths_come_from_the_base(repo):
    def rules():
        (repo.root / "REVIEW.md").write_text(
            "# Review\n\n## High-stakes paths\n\n"
            "- `src/auth/*` (see `docs/auth.md`)\n"
            "- `./billing/`\n\n"
            "```sh\n# not a heading\n```\n\n"
            "- `/payments/*`\n"
            "- `**/secrets/**/*.py`\n\n## Other\n\n- `src/x/*`\n"
        )

    repo.on_main(rules)
    (repo.root / "REVIEW.md").write_text("# Review\n")
    repo.write("src/auth/login.py", 5)
    repo.commit()
    out = repo.score()
    assert out["signals"]["review_md_patterns"] == [
        "src/auth/*",
        "billing/*",
        "payments/*",
        "**/secrets/**/*.py",
    ]
    hit = {"path": "src/auth/login.py", "rule": "src/auth/*", "source": "REVIEW.md"}
    assert hit in out["signals"]["high_stakes"]
    assert out["floor"] == "high"


def test_review_md_takes_top_level_bullets_and_bare_directories(repo):
    repo.on_main(
        lambda: (repo.root / "REVIEW.md").write_text(
            "## High-stakes paths\n\n- `src/auth`\n  - owned by `security-team`\n"
        )
    )
    repo.write("src/auth/login.py", 3)
    repo.commit()
    out = repo.score()
    assert out["signals"]["review_md_patterns"] == ["src/auth"]
    assert out["signals"]["high_stakes"][0]["rule"] == "src/auth"


@pytest.mark.parametrize("path", ["billing/pay.py", "app/billing/pay.py"])
def test_a_bare_directory_name_matches_in_any_directory(repo, path):
    repo.on_main(
        lambda: (repo.root / "REVIEW.md").write_text("## High-stakes paths\n\n- `billing`\n")
    )
    repo.write(path, 3)
    repo.commit()
    assert repo.score()["floor"] == "high"


@pytest.mark.parametrize("path", ["secrets/key.py", "app/secrets/key.py", "secrets/a/b/key.py"])
def test_double_star_matches_zero_or_more_dirs(repo, path):
    repo.on_main(
        lambda: (repo.root / "REVIEW.md").write_text(
            "## High-stakes paths\n\n- `**/secrets/**/*.py`\n"
        )
    )
    repo.write(path, 3)
    repo.commit()
    assert repo.score()["floor"] == "high"


def test_uncommitted_and_untracked_files_count(repo):
    repo.write("src/app.py", 15)
    repo.write("src/new.py", 40)
    out = repo.score()
    assert out["signals"]["files"] == 2
    assert out["signals"]["lines"] == 5 + 40


def test_untracked_binary_counts_like_a_tracked_one(repo):
    (repo.root / "img.png").write_bytes(b"\x89PNG\0\0data")
    untracked = repo.score()["signals"]["files"]
    repo.git("add", "img.png")
    assert repo.score()["signals"]["files"] == untracked == 1


def test_unstaged_rename_scores_like_a_staged_one(repo):
    repo.write("src/big.py", 80)
    repo.commit()
    repo.git("switch", "-q", "-c", "moved")
    (repo.root / "src/big.py").rename(repo.root / "src/moved.py")
    before = repo.score(base="feature")["signals"]
    repo.git("add", "-A")
    after = repo.score(base="feature")["signals"]
    assert before["lines"] == after["lines"] == 0
    assert before["files"] == after["files"] == 0


def test_scoring_leaves_the_real_index_alone(repo):
    repo.write("src/new.py", 5)
    repo.score()
    assert repo.git("status", "--porcelain") == "?? src/new.py\n"


def test_scoring_writes_no_objects(repo):
    repo.write("src/new.py", 5000)
    repo.write("src/app.py", 20)
    before = repo.git("count-objects")
    repo.score()
    assert repo.git("count-objects") == before


def test_a_shared_clone_can_be_scored(repo, tmp_path):
    clone = Repo(tmp_path / "clone")
    repo.git("clone", "-q", "--shared", "-b", "main", str(repo.root), str(clone.root))
    clone.write("src/new.py", 7)
    assert clone.score()["signals"]["lines"] == 7


def test_head_scores_a_branch_without_checking_it_out(repo):
    repo.write(".github/workflows/ci.yml", 3)
    repo.commit()
    repo.git("switch", "-q", "main")
    repo.write("scratch.py", 500)
    out = repo.score("--head", "feature")
    assert out["signals"]["files"] == 1
    assert out["floor"] == "high"


def test_path_target_narrows_the_scope(repo):
    repo.write("src/feature.py", 5)
    repo.write(".github/workflows/ci.yml", 3)
    repo.commit()
    out = repo.score("--path", ".", cwd=repo.root / "src")
    assert out["signals"]["files"] == 1
    assert out["signals"]["high_stakes"] == []


def test_path_target_is_a_prefix_of_whole_names(repo):
    repo.write("src/feature.py", 5)
    repo.write("src2/other.py", 9)
    repo.commit()
    assert repo.score("--path", "src")["signals"]["lines"] == 5
    assert repo.score("--path", "src/feature.py")["signals"]["lines"] == 5


def test_a_symlink_path_names_itself(repo):
    repo.write("src/feature.py", 5)
    (repo.root / "link").symlink_to("src")
    repo.commit()
    assert repo.score("--path", str(repo.root / "link"))["path"] == "link"


def test_path_through_a_symlink_resolves(repo, tmp_path):
    alias = tmp_path / "alias"
    alias.symlink_to(repo.root)
    repo.write("src/feature.py", 5)
    repo.commit()
    out = repo.score("--path", str(alias / "src"))
    assert out["path"] == "src"


@pytest.mark.skipif(os.geteuid() == 0, reason="root can read any file")
def test_unreadable_untracked_file_is_skipped(repo):
    repo.write("src/secret.py", 5)
    (repo.root / "src/secret.py").chmod(0)
    try:
        out = repo.score()
        assert out["signals"]["files"] == 0
        assert any(fact.startswith("not counted:") for fact in out["facts"])
    finally:
        (repo.root / "src/secret.py").chmod(0o644)


def test_gitattributes_cannot_hide_lines(repo):
    (repo.root / ".gitattributes").write_text("*.py -diff\n")
    repo.write("src/big.py", 300)
    repo.commit()
    assert repo.score()["signals"]["lines"] >= 300


def test_binary_files_are_reported(repo):
    (repo.root / "lib.so").write_bytes(b"\0ELF" * 100)
    repo.commit()
    assert "binary: 1 files with no line counts" in repo.score()["facts"]


def test_excluded_lines_are_reported(repo):
    repo.write("dist/index.js", 5000)
    repo.commit()
    out = repo.score()
    assert out["signals"]["lines"] == 0
    assert any("5000 lines" in fact for fact in out["facts"])


def test_carriage_return_in_a_name_survives(repo):
    repo.write("src/x\ry.py", 30)
    out = repo.score()
    assert out["signals"]["files"] == 1
    assert out["signals"]["lines"] == 30


def test_pure_rename_counts_no_lines_or_files(repo):
    repo.git("mv", "src/app.py", "src/main.py")
    repo.commit()
    out = repo.score()
    assert out["signals"]["lines"] == 0
    assert out["signals"]["files"] == 0


def test_unknown_base_fails(repo):
    result = run(["--base", "nope"], repo.root)
    assert result.returncode == 1
    assert "score_risk:" in result.stderr


def test_missing_merge_base_says_why(repo):
    repo.git("switch", "-q", "--orphan", "other")
    repo.write("x.py", 1)
    repo.commit()
    result = run(["--base", "main"], repo.root)
    assert result.returncode == 1
    assert "no merge base" in result.stderr

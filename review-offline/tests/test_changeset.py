import json
import subprocess
from pathlib import Path

import pytest
from review_offline import changeset
from review_offline.changeset import (
    ChangesetError,
    cleanup_worktree,
    default_runner,
    parse_diff,
    resolve,
    slug_for,
)


def by_path(files):
    return {f["path"]: f for f in files}


def header(path, extra=""):
    return f"diff --git a/{path} b/{path}\n{extra}"


class TestParseDiff:
    def test_modified_with_two_hunks_and_line_numbers(self):
        text = (
            "diff --git a/src/a.py b/src/a.py\n"
            "index 111..222 100644\n"
            "--- a/src/a.py\n"
            "+++ b/src/a.py\n"
            "@@ -1,4 +1,5 @@ def f\n"
            " one\n"
            "-two\n"
            "+TWO\n"
            "+extra\n"
            " three\n"
            " four\n"
            "@@ -20,2 +21,2 @@ class C\n"
            " keep\n"
            "-old\n"
            "+new\n"
        )
        [f] = parse_diff(text)
        assert (f["path"], f["old_path"], f["status"]) == ("src/a.py", None, "modified")
        assert (f["additions"], f["deletions"]) == (3, 2)
        assert not f["binary"] and not f["collapsed"] and f["collapse_reason"] is None
        first, second = f["hunks"]
        assert first["header"] == "@@ -1,4 +1,5 @@ def f"
        assert (first["old_start"], first["new_start"]) == (1, 1)
        assert first["lines"] == [
            {"t": "ctx", "o": 1, "n": 1, "text": "one"},
            {"t": "del", "o": 2, "n": None, "text": "two"},
            {"t": "add", "o": None, "n": 2, "text": "TWO"},
            {"t": "add", "o": None, "n": 3, "text": "extra"},
            {"t": "ctx", "o": 3, "n": 4, "text": "three"},
            {"t": "ctx", "o": 4, "n": 5, "text": "four"},
        ]
        assert (second["old_start"], second["new_start"]) == (20, 21)
        assert second["lines"][1] == {"t": "del", "o": 21, "n": None, "text": "old"}
        assert second["lines"][2] == {"t": "add", "o": None, "n": 22, "text": "new"}

    def test_hunk_header_without_counts(self):
        text = header("a.txt", "--- a/a.txt\n+++ b/a.txt\n@@ -3 +3 @@\n-x\n+y\n")
        [f] = parse_diff(text)
        assert [line["t"] for line in f["hunks"][0]["lines"]] == ["del", "add"]
        assert f["hunks"][0]["lines"][0]["o"] == 3

    def test_added_file(self):
        text = header(
            "new.txt",
            "new file mode 100644\nindex 000..abc\n--- /dev/null\n+++ b/new.txt\n"
            "@@ -0,0 +1,2 @@\n+a\n+b\n",
        )
        [f] = parse_diff(text)
        assert (f["status"], f["path"], f["old_path"]) == ("added", "new.txt", None)
        assert (f["additions"], f["deletions"]) == (2, 0)
        assert f["hunks"][0]["old_start"] == 0

    def test_deleted_file(self):
        text = header(
            "gone.txt",
            "deleted file mode 100644\nindex abc..000\n--- a/gone.txt\n+++ /dev/null\n"
            "@@ -1,2 +0,0 @@\n-a\n-b\n",
        )
        [f] = parse_diff(text)
        assert (f["status"], f["path"], f["old_path"]) == ("deleted", "gone.txt", None)
        assert (f["additions"], f["deletions"]) == (0, 2)
        assert f["hunks"][0]["lines"][1] == {"t": "del", "o": 2, "n": None, "text": "b"}

    def test_empty_new_and_deleted_files_have_no_hunks(self):
        text = (
            "diff --git a/empty b/empty\nnew file mode 100644\nindex 000..e69\n"
            "diff --git a/zip b/zip\ndeleted file mode 100644\nindex e69..000\n"
        )
        empty, zipped = parse_diff(text)
        assert (empty["status"], empty["path"], empty["hunks"]) == ("added", "empty", [])
        assert (zipped["status"], zipped["path"], zipped["hunks"]) == ("deleted", "zip", [])

    def test_pure_rename_without_hunks(self):
        text = (
            "diff --git a/old.py b/new.py\nsimilarity index 100%\n"
            "rename from old.py\nrename to new.py\n"
        )
        [f] = parse_diff(text)
        assert (f["status"], f["path"], f["old_path"]) == ("renamed", "new.py", "old.py")
        assert f["hunks"] == [] and (f["additions"], f["deletions"]) == (0, 0)

    def test_rename_with_edit(self):
        text = (
            "diff --git a/old name.py b/new name.py\nsimilarity index 80%\n"
            "rename from old name.py\nrename to new name.py\nindex 1..2 100644\n"
            "--- a/old name.py\t\n+++ b/new name.py\t\n@@ -1 +1 @@\n-a\n+b\n"
        )
        [f] = parse_diff(text)
        assert (f["status"], f["path"], f["old_path"]) == ("renamed", "new name.py", "old name.py")
        assert (f["additions"], f["deletions"]) == (1, 1)

    def test_binary_file(self):
        text = (
            "diff --git a/img.png b/img.png\nindex 1..2 100644\n"
            "Binary files a/img.png and b/img.png differ\n"
            "diff --git a/new.bin b/new.bin\nnew file mode 100644\nindex 000..abc\n"
            "Binary files /dev/null and b/new.bin differ\n"
        )
        modified, added = parse_diff(text)
        assert modified["binary"] and modified["hunks"] == [] and modified["status"] == "modified"
        assert added["binary"] and added["status"] == "added" and added["path"] == "new.bin"

    def test_no_newline_marker_is_dropped_and_does_not_shift_numbers(self):
        text = header(
            "a.txt",
            "--- a/a.txt\n+++ b/a.txt\n@@ -1,2 +1,2 @@\n one\n-two\n"
            "\\ No newline at end of file\n+TWO\n\\ No newline at end of file\n"
            "diff --git a/b.txt b/b.txt\n--- a/b.txt\n+++ b/b.txt\n@@ -1 +1 @@\n-x\n+y\n",
        )
        a, b = parse_diff(text)
        assert [(ln["t"], ln["text"]) for ln in a["hunks"][0]["lines"]] == [
            ("ctx", "one"),
            ("del", "two"),
            ("add", "TWO"),
        ]
        assert b["path"] == "b.txt" and len(b["hunks"]) == 1

    def test_quoted_paths(self):
        text = (
            'diff --git "a/caf\\303\\251 \\"q\\".txt" "b/caf\\303\\251 \\"q\\".txt"\n'
            'index 1..2 100644\n--- "a/caf\\303\\251 \\"q\\".txt"\n'
            '+++ "b/caf\\303\\251 \\"q\\".txt"\n@@ -1 +1 @@\n-a\n+b\n'
        )
        [f] = parse_diff(text)
        assert f["path"] == 'café "q".txt'

    def test_quoted_rename_and_tab_name(self):
        text = (
            'diff --git a/plain.txt "b/tab\\there.txt"\nsimilarity index 100%\n'
            'rename from plain.txt\nrename to "tab\\there.txt"\n'
        )
        [f] = parse_diff(text)
        assert (f["old_path"], f["path"]) == ("plain.txt", "tab\there.txt")

    def test_unquoted_path_with_spaces_and_no_hunks(self):
        text = "diff --git a/my dir/a b.txt b/my dir/a b.txt\nold mode 100644\nnew mode 100755\n"
        [f] = parse_diff(text)
        assert (f["status"], f["path"]) == ("modified", "my dir/a b.txt")

    def test_removed_line_that_looks_like_a_file_header(self):
        text = header(
            "a.sql",
            "--- a/a.sql\n+++ b/a.sql\n@@ -1,2 +1,1 @@\n--- a comment\n-- keep\n"
            "diff --git a/b.txt b/b.txt\n--- a/b.txt\n+++ b/b.txt\n@@ -1 +1 @@\n-x\n+y\n",
        )
        a, b = parse_diff(text)
        assert a["hunks"][0]["lines"][0] == {"t": "del", "o": 1, "n": None, "text": "-- a comment"}
        assert a["hunks"][0]["lines"][1]["t"] == "del"
        assert b["path"] == "b.txt"

    def test_content_with_carriage_return_and_empty_context_line(self):
        text = header("a.txt", "--- a/a.txt\n+++ b/a.txt\n@@ -1,2 +1,2 @@\n-a\r\n+b\r\n \n")
        [f] = parse_diff(text)
        assert f["hunks"][0]["lines"][0]["text"] == "a\r"
        assert f["hunks"][0]["lines"][2] == {"t": "ctx", "o": 2, "n": 2, "text": ""}

    @pytest.mark.parametrize(
        ("path", "reason"),
        [
            ("package-lock.json", "lockfile"),
            ("web/yarn.lock", "lockfile"),
            ("pnpm-lock.yaml", "lockfile"),
            ("uv.lock", "lockfile"),
            ("Cargo.lock", "lockfile"),
            ("poetry.lock", "lockfile"),
            ("sub/go.sum", "lockfile"),
            ("static/app.min.js", "minified"),
            ("static/app.min.css", "minified"),
            ("static/app.js.map", "source map"),
            ("src/schema.generated.ts", "generated"),
            ("api/user_pb2.py", "generated"),
            ("dist/index.js", "vendored"),
            ("vendor/lib/a.go", "vendored"),
            ("web/node_modules/x/index.js", "vendored"),
        ],
    )
    def test_collapse_reasons_keep_hunks(self, path, reason):
        text = header(path, f"--- a/{path}\n+++ b/{path}\n@@ -1 +1 @@\n-a\n+b\n")
        [f] = parse_diff(text)
        assert (f["collapsed"], f["collapse_reason"]) == (True, reason)
        assert len(f["hunks"]) == 1 and (f["additions"], f["deletions"]) == (1, 1)

    @pytest.mark.parametrize(
        "path", ["src/main.py", "distribution/a.py", "lock.py", "docs/vendor.md"]
    )
    def test_normal_files_not_collapsed(self, path):
        [f] = parse_diff(header(path, f"--- a/{path}\n+++ b/{path}\n@@ -1 +1 @@\n-a\n+b\n"))
        assert f["collapsed"] is False and f["collapse_reason"] is None

    def test_empty_input(self):
        assert parse_diff("") == []


ENV_KEYS = {
    "GIT_AUTHOR_NAME": "T",
    "GIT_AUTHOR_EMAIL": "t@example.com",
    "GIT_COMMITTER_NAME": "T",
    "GIT_COMMITTER_EMAIL": "t@example.com",
    "GIT_CONFIG_GLOBAL": "/dev/null",
    "GIT_CONFIG_SYSTEM": "/dev/null",
}


@pytest.fixture(autouse=True)
def git_env(monkeypatch):
    for key, value in ENV_KEYS.items():
        monkeypatch.setenv(key, value)


def git(repo, *args):
    proc = subprocess.run(["git", *args], cwd=repo, capture_output=True, text=True, check=True)
    return proc.stdout.strip()


def write(repo, name, content):
    path = Path(repo) / name
    path.parent.mkdir(parents=True, exist_ok=True)
    if isinstance(content, bytes):
        path.write_bytes(content)
    else:
        path.write_text(content)


def commit(repo, message):
    git(repo, "add", "-A")
    git(repo, "commit", "-q", "-m", message)
    return git(repo, "rev-parse", "HEAD")


@pytest.fixture
def repo(tmp_path):
    root = tmp_path / "repo"
    root.mkdir()
    git(root, "init", "-q", "-b", "main")
    write(root, "src/a.py", "".join(f"line {i}\n" for i in range(1, 21)))
    write(root, "docs/old-name.md", "".join(f"doc {i}\n" for i in range(1, 11)))
    write(root, "uv.lock", "a\nb\n")
    write(root, "img.png", b"\x89PNG\x00\x01\x02")
    write(root, "keep.txt", "keep\n")
    commit(root, "base")
    return root


@pytest.fixture
def feature(repo):
    git(repo, "checkout", "-q", "-b", "feat/x")
    write(
        repo,
        "src/a.py",
        "".join(f"line {i}\n" for i in range(1, 21)).replace("line 5\n", "LINE 5\n"),
    )
    git(repo, "mv", "docs/old-name.md", "docs/new-name.md")
    write(repo, "uv.lock", "a\nb\nc\n")
    write(repo, "img.png", b"\x89PNG\x00\x01\x02\x03")
    write(repo, "added.txt", "hello\nworld")
    git(repo, "rm", "-q", "keep.txt")
    commit(repo, "feature work")
    git(repo, "checkout", "-q", "main")
    return repo


def index_state(repo):
    return (Path(repo) / ".git" / "index").read_bytes()


class TestResolveRev:
    def test_branch_name(self, feature, tmp_path):
        run_dir = tmp_path / "run"
        cs = resolve("feat/x", feature, run_dir)
        files = by_path(cs["files"])
        assert cs["slug"] == "feat-x" and cs["target"] == "feat/x"
        assert cs["title"] == "feature work"
        assert cs["base"] == {"sha": git(feature, "rev-parse", "main"), "ref": "main"}
        assert cs["head"] == {"sha": git(feature, "rev-parse", "feat/x"), "ref": "feat/x"}
        assert files["src/a.py"]["status"] == "modified"
        assert files["docs/new-name.md"]["status"] == "renamed"
        assert files["docs/new-name.md"]["old_path"] == "docs/old-name.md"
        assert files["added.txt"]["status"] == "added"
        assert files["keep.txt"]["status"] == "deleted"
        assert files["img.png"]["binary"] is True
        assert files["uv.lock"]["collapse_reason"] == "lockfile" and files["uv.lock"]["hunks"]
        assert cs["root"] == str(run_dir / "worktree")
        assert git(run_dir / "worktree", "rev-parse", "HEAD") == cs["head"]["sha"]
        assert git(run_dir / "worktree", "rev-parse", "--abbrev-ref", "HEAD") == "HEAD"

    def test_writes_run_dir_files(self, feature, tmp_path):
        run_dir = tmp_path / "run"
        cs = resolve("feat/x", feature, run_dir)
        assert json.loads((run_dir / "changeset.json").read_text()) == cs
        patch = (run_dir / "prefetch" / "diff.patch").read_text()
        assert patch.startswith("diff --git ") and "+LINE 5" in patch
        assert not (run_dir / "prefetch" / "pr.md").exists()

    def test_does_not_touch_checkout(self, feature, tmp_path):
        before = (index_state(feature), git(feature, "status", "--porcelain"))
        branches = git(feature, "branch", "-a")
        resolve("feat/x", feature, tmp_path / "run")
        assert (index_state(feature), git(feature, "status", "--porcelain")) == before
        assert git(feature, "branch", "-a") == branches
        assert git(feature, "rev-parse", "--abbrev-ref", "HEAD") == "main"

    def test_rerun_reuses_worktree(self, feature, tmp_path):
        run_dir = tmp_path / "run"
        resolve("feat/x", feature, run_dir)
        marker = run_dir / "worktree" / "marker"
        marker.write_text("x")
        resolve("feat/x", feature, run_dir)
        assert marker.exists()

    def test_head_checked_out_clean_uses_repo_root(self, feature, tmp_path):
        git(feature, "checkout", "-q", "feat/x")
        cs = resolve("HEAD", feature, tmp_path / "run")
        assert cs["root"] == str(feature) and cs["slug"] == "feat-x"
        assert cs["head"]["ref"] == "feat/x"
        assert not (tmp_path / "run" / "worktree").exists()

    def test_head_dirty_uses_worktree(self, feature, tmp_path):
        git(feature, "checkout", "-q", "feat/x")
        write(feature, "src/a.py", "dirty\n")
        cs = resolve("HEAD", feature, tmp_path / "run")
        assert cs["root"] == str(tmp_path / "run" / "worktree")
        assert "dirty" not in json.dumps(cs["files"])

    def test_default_branch_head_falls_back_to_last_commit(self, feature, tmp_path):
        git(feature, "merge", "-q", "--ff-only", "feat/x")
        cs = resolve("HEAD", feature, tmp_path / "run")
        assert cs["title"] == "feature work"
        assert cs["base"]["sha"] == git(feature, "rev-parse", "HEAD~1")
        assert "added.txt" in by_path(cs["files"])

    def test_tag_and_sha_slug(self, feature, tmp_path):
        git(feature, "tag", "v1", "feat/x")
        sha = git(feature, "rev-parse", "feat/x")
        assert resolve("v1", feature, tmp_path / "r1")["slug"] == f"head-{sha[:7]}"
        assert slug_for(sha, feature) == f"head-{sha[:7]}"

    def test_unknown_target(self, feature, tmp_path):
        with pytest.raises(ChangesetError, match="cannot resolve target 'nope'"):
            resolve("nope", feature, tmp_path / "run")


class TestResolveRange:
    def test_two_dots(self, feature, tmp_path):
        cs = resolve("main..feat/x", feature, tmp_path / "run")
        assert cs["base"]["sha"] == git(feature, "rev-parse", "main")
        assert cs["head"]["sha"] == git(feature, "rev-parse", "feat/x")
        assert cs["slug"].startswith("feat-x-range-")
        assert "added.txt" in by_path(cs["files"])

    def test_three_dots_use_merge_base(self, feature, tmp_path):
        base = git(feature, "rev-parse", "main")
        write(feature, "later.txt", "later\n")
        commit(feature, "main moves on")
        cs = resolve("main...feat/x", feature, tmp_path / "run")
        assert cs["base"]["sha"] == base
        assert "later.txt" not in by_path(cs["files"])

    def test_two_dots_see_main_changes(self, feature, tmp_path):
        write(feature, "later.txt", "later\n")
        commit(feature, "main moves on")
        files = by_path(resolve("main..feat/x", feature, tmp_path / "run")["files"])
        assert files["later.txt"]["status"] == "deleted"


class TestResolveWorkingTree:
    def test_staged_unstaged_and_untracked(self, feature, tmp_path):
        git(feature, "checkout", "-q", "-b", "wip", "feat/x")
        write(feature, "staged.txt", "staged\n")
        git(feature, "add", "staged.txt")
        write(feature, "src/a.py", "changed\n")
        write(feature, "untracked/new.txt", "fresh\nfile\n")
        write(feature, "untracked/blob.bin", b"\x00\x01\x02")
        write(feature, "ignored.log", "x\n")
        write(feature, ".gitignore", "*.log\n")
        before = (index_state(feature), git(feature, "status", "--porcelain"))
        cs = resolve(None, feature, tmp_path / "run")
        assert (index_state(feature), git(feature, "status", "--porcelain")) == before
        files = by_path(cs["files"])
        assert cs["slug"] == "wip" and cs["target"] == "working-tree"
        assert cs["root"] == str(feature)
        assert cs["base"]["sha"] == git(feature, "rev-parse", "main")
        assert files["staged.txt"]["status"] == "added"
        assert files["src/a.py"]["additions"] == 1
        assert files["added.txt"]["status"] == "added"
        assert files["untracked/new.txt"]["status"] == "added"
        assert files["untracked/new.txt"]["additions"] == 2
        assert files["untracked/blob.bin"]["binary"] is True
        assert "ignored.log" not in files
        assert not (tmp_path / "run" / "worktree").exists()

    def test_empty_when_clean_on_default_branch(self, repo, tmp_path):
        assert resolve("", repo, tmp_path / "run")["files"] == []

    def test_detached_head_slug(self, feature, tmp_path):
        sha = git(feature, "rev-parse", "feat/x")
        git(feature, "checkout", "-q", "--detach", "feat/x")
        assert resolve(None, feature, tmp_path / "run")["slug"] == f"head-{sha[:7]}"

    def test_path_restricted(self, repo, tmp_path):
        write(repo, "src/a.py", "changed\n")
        write(repo, "src/new.py", "new\n")
        write(repo, "docs/other.md", "other\n")
        write(repo, "keep.txt", "edited\n")
        cs = resolve("src", repo, tmp_path / "run")
        assert sorted(by_path(cs["files"])) == ["src/a.py", "src/new.py"]
        assert cs["root"] == str(repo) and cs["slug"].startswith("main-path-")
        cs = resolve(str(repo / "keep.txt"), repo, tmp_path / "run2")
        assert sorted(by_path(cs["files"])) == ["keep.txt"]

    def test_path_outside_repo(self, repo, tmp_path):
        outside = tmp_path / "outside.txt"
        outside.write_text("x")
        with pytest.raises(ChangesetError, match="outside the repository"):
            resolve(str(outside), repo, tmp_path / "run")

    def test_subdirectory_repo_argument(self, feature, tmp_path):
        cs = resolve("feat/x", feature / "src", tmp_path / "run")
        assert cs["head"]["ref"] == "feat/x"


class TestSlugs:
    def test_pr_forms(self, repo):
        for target in ("pr:7", "7", "#7", "https://github.com/o/r/pull/7", "pr:#7"):
            assert slug_for(target, repo) == "pr-7"

    def test_branch_slash_becomes_dash(self, feature):
        assert slug_for("feat/x", feature) == "feat-x"

    def test_unsafe_characters_are_neutralised(self, repo):
        git(repo, "branch", "we!rd#name")
        assert "/" not in slug_for("we!rd#name", repo) and " " not in slug_for("we!rd#name", repo)

    def test_remote_tracking_branch(self, feature):
        git(feature, "update-ref", "refs/remotes/origin/topic", "feat/x")
        assert slug_for("origin/topic", feature) == "origin-topic"


class FakeRunner:
    def __init__(self, repo, view, inline=None, inline_fails=False):
        self.repo, self.view, self.inline, self.inline_fails = repo, view, inline, inline_fails
        self.calls = []

    def __call__(self, argv, cwd):
        self.calls.append(list(argv))
        if argv[0] == "gh":
            if argv[1:3] == ["pr", "view"]:
                return subprocess.CompletedProcess(argv, 0, json.dumps(self.view), "")
            if argv[1] == "api":
                if self.inline_fails:
                    return subprocess.CompletedProcess(argv, 1, "", "HTTP 403")
                out = "".join(json.dumps(page) for page in self.inline or [])
                return subprocess.CompletedProcess(argv, 0, out, "")
            raise AssertionError(f"unexpected gh call {argv}")
        if "fetch" in argv:
            ref = next(a for a in argv if a.startswith("pull/"))
            assert ref == "pull/7/head"
            return default_runner(["git", "fetch", "-q", ".", "refs/heads/feat/x"], cwd)
        return default_runner(argv, cwd)


@pytest.fixture
def pr_view(feature):
    return {
        "number": 7,
        "title": "Add the thing",
        "body": "Body text\n\nWith detail.",
        "url": "https://github.com/o/r/pull/7",
        "baseRefName": "main",
        "baseRefOid": git(feature, "rev-parse", "main"),
        "headRefName": "feat/x",
        "headRefOid": git(feature, "rev-parse", "feat/x"),
        "comments": [{"author": {"login": "alice"}, "body": "Looks odd"}],
        "reviews": [
            {"author": {"login": "bob"}, "body": "Please fix", "state": "CHANGES_REQUESTED"},
            {"author": {"login": "carol"}, "body": "", "state": "COMMENTED"},
        ],
    }


class TestResolvePr:
    def test_pr_target(self, feature, tmp_path, pr_view):
        inline = [[{"user": {"login": "dave"}, "path": "src/a.py", "line": 5, "body": "why?"}]]
        runner = FakeRunner(feature, pr_view, inline)
        run_dir = tmp_path / "run"
        cs = resolve("pr:7", feature, run_dir, runner=runner)
        assert cs["target"] == "pr:7" and cs["slug"] == "pr-7"
        assert cs["title"] == "Add the thing"
        assert cs["base"] == {"sha": pr_view["baseRefOid"], "ref": "main"}
        assert cs["head"] == {"sha": pr_view["headRefOid"], "ref": "feat/x"}
        assert cs["root"] == str(run_dir / "worktree")
        assert "added.txt" in by_path(cs["files"])
        pr_md = (run_dir / "prefetch" / "pr.md").read_text()
        assert "# Add the thing" in pr_md and "With detail." in pr_md
        comments = (run_dir / "prefetch" / "pr-comments.md").read_text()
        assert "Review by bob (CHANGES_REQUESTED)" in comments and "Please fix" in comments
        assert "Comment by alice" in comments and "Looks odd" in comments
        assert "Inline comment by dave on src/a.py:5" in comments and "why?" in comments
        assert "carol" not in comments
        assert (run_dir / "prefetch" / "diff.patch").read_text().startswith("diff --git")

    def test_gh_is_read_only(self, feature, tmp_path, pr_view):
        runner = FakeRunner(feature, pr_view, [])
        resolve("https://github.com/o/r/pull/7", feature, tmp_path / "run", runner=runner)
        gh_calls = [c for c in runner.calls if c[0] == "gh"]
        assert [c[1:3] for c in gh_calls] == [["pr", "view"], ["api", "repos/o/r/pulls/7/comments"]]
        assert gh_calls[0][3] == "https://github.com/o/r/pull/7"
        subcommands = {c[2] for c in runner.calls if c[0] == "git"}
        assert subcommands <= {
            "rev-parse",
            "fetch",
            "cat-file",
            "merge-base",
            "diff",
            "status",
            "symbolic-ref",
            "worktree",
            "show-ref",
        }
        assert not any("-X" in c or "--method" in c for c in gh_calls)

    def test_bare_number_and_hash_forms(self, feature, tmp_path, pr_view):
        for i, target in enumerate(("7", "#7")):
            runner = FakeRunner(feature, pr_view, [])
            cs = resolve(target, feature, tmp_path / f"run{i}", runner=runner)
            assert cs["target"] == "pr:7"
            assert next(c for c in runner.calls if c[0] == "gh")[:4] == ["gh", "pr", "view", "7"]

    def test_inline_comment_failure_is_reported_not_fatal(self, feature, tmp_path, pr_view):
        runner = FakeRunner(feature, pr_view, inline_fails=True)
        run_dir = tmp_path / "run"
        resolve("pr:7", feature, run_dir, runner=runner)
        assert "could not be fetched" in (run_dir / "prefetch" / "pr-comments.md").read_text()

    def test_multi_page_inline_comments(self, feature, tmp_path, pr_view):
        pages = [
            [{"user": {"login": "u1"}, "path": "a", "body": "one"}],
            [{"user": {"login": "u2"}, "path": "b", "body": "two"}],
        ]
        run_dir = tmp_path / "run"
        resolve("pr:7", feature, run_dir, runner=FakeRunner(feature, pr_view, pages))
        text = (run_dir / "prefetch" / "pr-comments.md").read_text()
        assert "one" in text and "two" in text

    def test_head_mismatch_is_an_error(self, feature, tmp_path, pr_view):
        pr_view["headRefOid"] = "0" * 40
        with pytest.raises(ChangesetError, match="is origin the PR's repository"):
            resolve("pr:7", feature, tmp_path / "run", runner=FakeRunner(feature, pr_view))

    def test_gh_failure_names_command(self, feature, tmp_path):
        def runner(argv, cwd):
            if argv[0] == "gh":
                return subprocess.CompletedProcess(argv, 1, "", "no such pr")
            return default_runner(argv, cwd)

        with pytest.raises(ChangesetError, match=r"gh pr view 7.*no such pr"):
            resolve("pr:7", feature, tmp_path / "run", runner=runner)

    def test_checked_out_pr_head_uses_repo_root(self, feature, tmp_path, pr_view):
        git(feature, "checkout", "-q", "feat/x")
        cs = resolve("pr:7", feature, tmp_path / "run", runner=FakeRunner(feature, pr_view, []))
        assert cs["root"] == str(feature)


class TestRunner:
    def test_failure_names_command(self, tmp_path):
        with pytest.raises(
            ChangesetError, match=r"git .*rev-parse.*not a git repository|rev-parse"
        ):
            resolve(None, tmp_path, tmp_path / "run")

    def test_missing_executable(self, tmp_path):
        with pytest.raises(ChangesetError, match="command not found: definitely-not-a-binary"):
            default_runner(["definitely-not-a-binary"], tmp_path)

    def test_default_runner_preserves_carriage_returns(self, tmp_path):
        proc = default_runner(["printf", "a\\r\\nb\\rc"], tmp_path)
        assert proc.stdout == "a\r\nb\rc"


class TestCleanup:
    def test_cleanup_removes_worktree_and_is_idempotent(self, feature, tmp_path):
        run_dir = tmp_path / "run"
        resolve("feat/x", feature, run_dir)
        assert str(run_dir / "worktree") in git(feature, "worktree", "list")
        cleanup_worktree(feature, run_dir)
        assert not (run_dir / "worktree").exists()
        assert str(run_dir / "worktree") not in git(feature, "worktree", "list")
        cleanup_worktree(feature, run_dir)
        assert (run_dir / "changeset.json").exists()

    def test_cleanup_when_directory_already_deleted(self, feature, tmp_path):
        run_dir = tmp_path / "run"
        resolve("feat/x", feature, run_dir)
        import shutil

        shutil.rmtree(run_dir / "worktree")
        cleanup_worktree(feature, run_dir)
        assert str(run_dir / "worktree") not in git(feature, "worktree", "list")

    def test_cleanup_without_run_dir(self, feature, tmp_path):
        cleanup_worktree(feature, tmp_path / "never-created")


class TestSlugIdentity:
    def test_range_and_path_targets_do_not_share_a_slug_with_the_branch(self, feature, tmp_path):
        plain = slug_for(None, feature)
        ranged = slug_for("main..feat/x", feature)
        other = slug_for("main...feat/x", feature)
        assert ranged != other and ranged != plain
        write(feature, "src/a.py", "edit\n")
        assert slug_for("src", feature) != plain
        assert slug_for("src", feature) != slug_for("src/a.py", feature)


class ScriptedRunner:
    """Runs argv against a scripted table of results; each entry is a
    (returncode, stdout, stderr) tuple, or a list of tuples consumed in order."""

    def __init__(self, script):
        self.script = {
            key: (value if isinstance(value, list) else [value]) for key, value in script.items()
        }
        self.calls = []

    def __call__(self, argv, cwd):
        self.calls.append(list(argv))
        key = " ".join(argv[2:]) if argv[0] == "git" else " ".join(argv)
        for pattern, results in self.script.items():
            if pattern in key and results:
                if len(results) > 1:
                    return subprocess.CompletedProcess(argv, *results.pop(0))
                return subprocess.CompletedProcess(argv, *results[0])
        raise AssertionError(f"unexpected call {argv}")


class TestMergeBase:
    def test_shallow_clone_unshallows_and_retries(self):
        runner = ScriptedRunner(
            {
                "merge-base": [(1, "", ""), (0, "abc123\n", "")],
                "--is-shallow-repository": [(0, "true\n", ""), (0, "false\n", "")],
                "--unshallow": (0, "", ""),
            }
        )
        g = changeset._Git(runner, Path("/repo"))
        assert changeset._merge_base(g, "main", "HEAD") == "abc123"
        assert any("--unshallow" in c for c in runner.calls)

    def test_shallow_clone_that_cannot_unshallow_names_the_cause(self):
        runner = ScriptedRunner(
            {
                "merge-base": (1, "", ""),
                "--is-shallow-repository": (0, "true\n", ""),
                "--unshallow": (1, "", "fatal: no remote"),
            }
        )
        g = changeset._Git(runner, Path("/repo"))
        with pytest.raises(ChangesetError, match="shallow"):
            changeset._merge_base(g, "main", "HEAD")

    def test_full_clone_failure_does_not_mention_shallow(self):
        runner = ScriptedRunner(
            {
                "merge-base": (1, "", ""),
                "--is-shallow-repository": (0, "false\n", ""),
            }
        )
        g = changeset._Git(runner, Path("/repo"))
        with pytest.raises(ChangesetError, match="no merge base between 'main' and 'HEAD'") as exc:
            changeset._merge_base(g, "main", "HEAD")
        assert "shallow" not in str(exc.value)

import importlib.util
import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "scope.py"
GIT_ENV = {
    "GIT_AUTHOR_NAME": "t",
    "GIT_AUTHOR_EMAIL": "t@example.com",
    "GIT_COMMITTER_NAME": "t",
    "GIT_COMMITTER_EMAIL": "t@example.com",
    "GIT_CONFIG_GLOBAL": os.devnull,
    "GIT_CONFIG_NOSYSTEM": "1",
    # Any https URL a test does not map to a local bare repo fails fast here
    # instead of reaching the network. A repo's own, longer insteadOf wins.
    "GIT_CONFIG_COUNT": "1",
    "GIT_CONFIG_KEY_0": "url./nonexistent/.insteadOf",
    "GIT_CONFIG_VALUE_0": "https://",
}
GH_URL = "https://github.com/acme/widget.git"
GH_REPO = "https://github.com/acme/widget"
PR_URL = "https://github.com/acme/widget/pull/7"

FAKE_GH = """
import json
import sys
import time
from pathlib import Path

here = Path(__file__).resolve().parent
args = sys.argv[1:]
with open(here / "gh.log", "a") as log:
    log.write(json.dumps(args) + "\\n")
key = []
for arg in args:
    if arg.startswith("--"):
        break
    key.append(arg)
reply = json.loads((here / "gh.json").read_text()).get(" ".join(key))
if reply is None:
    reply = 'no pull requests found for branch "feature"'
if isinstance(reply, str):
    sys.stderr.write(reply + "\\n")
    sys.exit(1)
time.sleep(reply.pop("sleep", 0))
print(json.dumps(reply))
"""


def pr_reply(head, base="main", url=PR_URL, number=7):
    return {
        "url": url,
        "number": number,
        "baseRefName": base,
        "headRefOid": head,
        "title": "Add a widget",
        "body": "Because.",
        "state": "OPEN",
    }


class Repo:
    def __init__(self, world, root):
        self.world = world
        self.root = root

    def git(self, *args):
        result = subprocess.run(
            ["git", *args],
            cwd=self.root,
            check=True,
            capture_output=True,
            text=True,
            env=self.world.env,
        )
        return result.stdout.strip()

    def commit(self, name, text=None):
        full = self.root / name
        full.parent.mkdir(parents=True, exist_ok=True)
        full.write_text(text if text is not None else f"{name}\n")
        self.git("add", "-A")
        self.git("commit", "-q", "-m", name)
        return self.head()

    def head(self):
        return self.git("rev-parse", "HEAD")

    def rev(self, rev):
        return self.git("rev-parse", rev)

    def has(self, ref):
        return (
            subprocess.run(
                ["git", "show-ref", "--verify", "-q", ref],
                check=False,
                cwd=self.root,
                env=self.world.env,
            ).returncode
            == 0
        )

    def alias(self, url, bare):
        self.git("config", f"url.{bare}.insteadOf", url)

    def publish_as(self, url, bare, remote="origin"):
        self.git("remote", "set-url", remote, url)
        self.alias(url, bare)

    def shallow(self):
        return self.git("rev-parse", "--is-shallow-repository") == "true"

    def scope(self, target=None, cwd=None):
        result = self.world.run(cwd or self.root, target)
        assert result.returncode == 0, result.stderr
        return json.loads(result.stdout)


class World:
    def __init__(self, root):
        self.root = root
        self.bin = root / "bin"
        self.bin.mkdir()
        gh = self.bin / "gh"
        gh.write_text(f"#!{sys.executable}\n{FAKE_GH}")
        gh.chmod(0o755)
        self.replies = {}
        self.gh_reply(None, None)
        self.env = {
            **os.environ,
            **GIT_ENV,
            "PATH": f"{self.bin}{os.pathsep}{os.environ['PATH']}",
        }

    def gh_reply(self, key, reply):
        if key:
            self.replies[key] = reply
        (self.bin / "gh.json").write_text(json.dumps(self.replies))

    def gh_calls(self):
        log = self.bin / "gh.log"
        if not log.exists():
            return []
        return [json.loads(line) for line in log.read_text().splitlines()]

    def run(self, cwd, target=None):
        args = [] if target is None else ["--target", target]
        return subprocess.run(
            [sys.executable, "-I", str(SCRIPT), *args],
            check=False,
            cwd=cwd,
            capture_output=True,
            text=True,
            env=self.env,
        )

    def repo(self, name, branch="main"):
        repo = Repo(self, self.root / name)
        repo.root.mkdir()
        repo.git("init", "-q", "-b", branch)
        return repo

    def bare(self, name):
        path = self.root / name
        subprocess.run(
            ["git", "init", "-q", "--bare", "-b", "main", str(path)],
            check=True,
            env=self.env,
        )
        return path

    def upstream(self, name="widget.git"):
        """A bare remote plus a seed clone that pushes to it."""
        bare = self.bare(name)
        seed = self.repo(f"seed-{name}")
        seed.git("remote", "add", "origin", str(bare))
        return bare, seed

    def clone(self, source, name, *flags):
        subprocess.run(
            ["git", "clone", "-q", *flags, str(source), str(self.root / name)],
            check=True,
            capture_output=True,
            env=self.env,
        )
        return Repo(self, self.root / name)


@pytest.fixture
def world(tmp_path):
    return World(tmp_path)


@pytest.fixture
def scope(world, monkeypatch):
    """The script as a module, running git and gh in the world's environment."""
    spec = importlib.util.spec_from_file_location("scope", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    monkeypatch.setattr(module, "ENV", world.env)
    return module


def published(world):
    """An upstream whose main has one commit, and a clone of it on a feature
    branch with one commit. Returns (bare, seed, work, m1)."""
    bare, seed = world.upstream()
    m1 = seed.commit("base.txt")
    seed.git("push", "-q", "origin", "main")
    work = world.clone(bare, "work")
    work.publish_as(GH_URL, bare)
    work.git("switch", "-q", "-c", "feature")
    work.commit("feature.txt")
    return bare, seed, work, m1


def changed(repo, merge_base):
    return repo.git("diff", "--name-only", merge_base).splitlines()


# Worked scenarios


def test_normal_clone_pr_into_main_refreshes_the_base(world):
    bare, seed, work, m1 = published(world)
    m2 = seed.commit("upstream.txt")
    seed.git("push", "-q", "origin", "main")
    # The branch merges the newer base by URL, leaving origin/main stale: a
    # stale base would put upstream.txt in scope as if this branch wrote it.
    work.git("pull", "-q", "--no-rebase", "--no-edit", str(bare), "main")
    assert work.rev("origin/main") == m1
    world.gh_reply("pr view", pr_reply(work.head()))

    out = work.scope()

    assert out["status"] == "ok"
    assert out["base"] == m2
    assert out["merge_base"] == m2
    assert changed(work, out["merge_base"]) == ["feature.txt"]
    assert out["pr"] == {
        "url": PR_URL,
        "host": "github.com",
        "owner": "acme",
        "repo": "widget",
        "number": 7,
        "title": "Add a widget",
        "body": "Because.",
        "headRefOid": work.head(),
    }
    assert out["warnings"] == []


def test_pr_into_release_branch_with_matching_remote(world):
    bare, seed = world.upstream()
    m1 = seed.commit("base.txt")
    seed.git("switch", "-q", "-c", "release/1.x")
    r1 = seed.commit("release.txt")
    seed.git("switch", "-q", "main")
    seed.commit("main.txt")
    seed.git("push", "-q", "origin", "main", "release/1.x")
    work = world.clone(bare, "work")
    work.publish_as(GH_URL, bare)
    work.git("switch", "-q", "-c", "feature", "origin/release/1.x")
    work.commit("feature.txt")
    world.gh_reply("pr view", pr_reply(work.head(), base="release/1.x"))

    out = work.scope()

    assert out["status"] == "ok"
    assert out["base"] == r1
    assert out["merge_base"] == r1
    assert work.git("merge-base", "origin/main", "HEAD") == m1
    assert out["warnings"] == []


@pytest.mark.parametrize("host", ["github.com", "ghe.example.com"])
def test_fork_with_only_its_own_origin_fetches_the_base_by_url(world, host):
    upstream, seed = world.upstream()
    seed.commit("base.txt")
    seed.git("switch", "-q", "-c", "release/1.x")
    r1 = seed.commit("release.txt")
    seed.git("push", "-q", "origin", "main", "release/1.x")
    fork = world.root / "fork.git"
    subprocess.run(
        ["git", "clone", "-q", "--bare", str(upstream), str(fork)], check=True, env=world.env
    )
    r2 = seed.commit("release-fix.txt")
    seed.git("push", "-q", "origin", "release/1.x")
    work = world.clone(fork, "work")
    work.publish_as(f"https://{host}/me/widget.git", fork)
    work.alias(f"https://{host}/acme/widget.git", upstream)
    work.git("switch", "-q", "-c", "feature", "origin/release/1.x")
    work.commit("feature.txt")
    url = f"https://{host}/acme/widget/pull/9"
    world.gh_reply("pr view", pr_reply(work.head(), base="release/1.x", url=url, number=9))

    out = work.scope()

    assert out["status"] == "ok"
    assert out["base"] == r2
    assert out["merge_base"] == r1
    assert out["pr"]["host"] == host
    assert out["warnings"] == []


def test_fork_with_origin_and_upstream_picks_the_descendant_merge_base(world):
    upstream, seed = world.upstream()
    seed.commit("base.txt")
    seed.git("push", "-q", "origin", "main")
    fork = world.root / "fork.git"
    subprocess.run(
        ["git", "clone", "-q", "--bare", str(upstream), str(fork)], check=True, env=world.env
    )
    for name in ("u1.txt", "u2.txt", "u3.txt"):
        tip = seed.commit(name)
    seed.git("push", "-q", "origin", "main")
    work = world.clone(fork, "work")
    work.publish_as("https://github.com/me/widget.git", fork)
    work.git("remote", "add", "upstream", GH_URL)
    work.alias(GH_URL, upstream)
    work.git("fetch", "-q", "upstream", "main")
    assert work.has("refs/remotes/origin/HEAD")
    assert not work.has("refs/remotes/upstream/HEAD")
    work.git("switch", "-q", "-c", "feature", "upstream/main")
    work.commit("feature.txt")
    world.gh_reply("repo view " + GH_REPO, {"defaultBranchRef": {"name": "main"}})

    out = work.scope()

    assert out["status"] == "ok"
    assert out["base"] == tip
    assert out["merge_base"] == tip
    assert changed(work, out["merge_base"]) == ["feature.txt"]
    repo_views = [c for c in world.gh_calls() if c[:2] == ["repo", "view"]]
    assert [c[2] for c in repo_views] == [GH_REPO]


def test_single_branch_clone_uses_the_fetched_oid(world):
    bare, seed = world.upstream()
    m1 = seed.commit("base.txt")
    seed.git("switch", "-q", "-c", "feature")
    seed.commit("feature.txt")
    seed.git("switch", "-q", "main")
    m2 = seed.commit("main.txt")
    seed.git("push", "-q", "origin", "main", "feature")
    work = world.clone(bare, "work", "--single-branch", "--branch", "feature")
    work.publish_as(GH_URL, bare)
    world.gh_reply("repo view " + GH_REPO, {"defaultBranchRef": {"name": "main"}})

    out = work.scope()

    assert out["status"] == "ok"
    assert out["base"] == m2
    assert out["merge_base"] == m1
    assert not work.has("refs/remotes/origin/main")
    assert out["warnings"] == []


@pytest.mark.parametrize("name", ["main", "master"])
def test_no_remotes_uses_the_local_head(world, name):
    repo = world.repo("solo", branch=name)
    m1 = repo.commit("base.txt")
    repo.git("switch", "-q", "-c", "feature")
    repo.commit("feature.txt")

    out = repo.scope()

    assert out["status"] == "ok"
    assert out["base"] == name
    assert out["merge_base"] == m1


def test_depth_one_without_a_parent_deepens_to_the_last_commit(world):
    bare, seed = world.upstream()
    seed.commit("base.txt")
    seed.git("switch", "-q", "-c", "feature")
    parent = seed.commit("one.txt")
    seed.commit("two.txt")
    seed.git("push", "-q", "origin", "feature")
    work = world.clone(f"file://{bare}", "work", "--depth", "1", "--branch", "feature")
    assert work.shallow()

    out = work.scope()

    assert out["status"] == "ok"
    assert out["base"] == "HEAD~1"
    assert out["merge_base"] == parent
    assert out["message"].startswith("Reviewing only the last commit")
    assert any("--deepen=1" in w for w in out["warnings"])
    assert not any("scope narrowed" in w for w in out["warnings"])


def test_depth_one_that_cannot_deepen_reports_no_scope(world):
    bare, seed = world.upstream()
    seed.commit("base.txt")
    seed.commit("next.txt")
    seed.git("push", "-q", "origin", "main:feature")
    work = world.clone(f"file://{bare}", "work", "--depth", "1", "--branch", "feature")
    shutil.rmtree(bare)

    out = work.scope()

    assert out["status"] == "no-scope"
    assert out["base"] is None
    assert out["merge_base"] is None
    assert any("--deepen=1 failed" in w for w in out["warnings"])


def test_root_commit_without_a_base_reports_no_scope(world):
    repo = world.repo("solo", branch="feature")
    repo.commit("only.txt")
    (repo.root / "draft.txt").write_text("draft\n")

    out = repo.scope()

    assert out["status"] == "no-scope"
    assert out["base"] is None
    assert "no scope could be resolved" in out["message"]


@pytest.mark.parametrize("with_pr", [True, False])
def test_shallow_branch_clone_unshallows_to_find_the_merge_base(world, with_pr):
    bare, seed = world.upstream()
    m1 = seed.commit("base.txt")
    seed.git("switch", "-q", "-c", "feature")
    seed.commit("f1.txt")
    seed.commit("f2.txt")
    seed.git("switch", "-q", "main")
    seed.commit("m2.txt")
    m3 = seed.commit("m3.txt")
    seed.git("push", "-q", "origin", "main", "feature")
    work = world.clone(f"file://{bare}", "work", "--depth", "1", "--branch", "feature")
    work.publish_as(GH_URL, f"file://{bare}")
    if with_pr:
        world.gh_reply("pr view", pr_reply(work.head()))
    else:
        world.gh_reply("repo view " + GH_REPO, {"defaultBranchRef": {"name": "main"}})

    out = work.scope()

    assert out["status"] == "ok"
    assert out["base"] == m3
    assert out["merge_base"] == m1
    assert any("--unshallow" in w for w in out["warnings"])
    assert not work.shallow()


# Checkout check


def test_pr_not_checked_out(world):
    _, _, work, _ = published(world)
    world.gh_reply("pr view 12", pr_reply("f" * 40, number=12))
    work.git("switch", "-q", "main")

    out = work.scope("12")

    assert out["status"] == "not-checked-out"
    assert "gh pr checkout 12" in out["message"]
    assert out["target"] == {"kind": "pr", "value": "12"}
    assert out["base"] is None
    assert out["pr"]["number"] == 12


def test_stale_local_branch_of_the_right_name_is_not_checked_out(world):
    bare, _, work, _ = published(world)
    work.git("push", "-q", str(bare), "feature")
    other = world.clone(bare, "other")
    other.git("switch", "-q", "feature")
    newer = other.commit("newer.txt")
    world.gh_reply("pr view 12", pr_reply(newer, number=12))

    out = work.scope("#12")

    assert out["status"] == "not-checked-out"
    assert "`gh pr checkout 12`" in out["message"]


def test_pr_url_target_that_is_checked_out(world):
    _, _, work, m1 = published(world)
    world.gh_reply("pr view " + PR_URL, pr_reply(work.head()))

    out = work.scope(PR_URL)

    assert out["status"] == "ok"
    assert out["target"] == {"kind": "pr", "value": PR_URL}
    assert out["merge_base"] == m1


def test_pr_target_gh_cannot_find_is_a_bad_target(world):
    _, _, work, _ = published(world)

    out = work.scope("99")

    assert out["status"] == "bad-target"
    assert "no pull requests found" in out["message"]


def test_ref_target_that_is_checked_out(world):
    _, _, work, m1 = published(world)

    out = work.scope("feature")

    assert out["status"] == "ok"
    assert out["target"] == {"kind": "ref", "value": "feature"}
    assert out["merge_base"] == m1


@pytest.mark.parametrize(
    ("ref", "command"),
    [("main", "git switch main"), ("v1", "git switch --detach {}"), ("HEAD~1", None)],
)
def test_ref_target_not_checked_out(world, ref, command):
    _, _, work, _ = published(world)
    work.git("tag", "v1", "main")
    # A relative ref moves once switched to, so only its oid converges.
    command = (command or "git switch --detach {}").format(work.rev(ref))

    out = work.scope(ref)

    assert out["status"] == "not-checked-out"
    assert f"`{command}`" in out["message"]
    assert "./" not in out["message"]


def test_ref_that_is_also_a_path_names_the_path_form(world):
    _, _, work, _ = published(world)
    (work.root / "main").mkdir()
    (work.root / "main/new.py").write_text("x = 1\n")

    out = work.scope("main")

    assert out["status"] == "not-checked-out"
    assert out["message"].endswith("; to review the path instead, pass ./main.")
    assert work.scope("./main")["path"] == "main"


@pytest.mark.parametrize("target", ["high", "XH", "med feature"])
def test_leftover_level_is_dropped(world, target):
    _, _, work, m1 = published(world)

    out = work.scope(target)

    assert out["status"] == "ok"
    assert out["merge_base"] == m1
    assert any("pm-risk" in w for w in out["warnings"])


def test_a_path_whose_first_word_is_a_level_is_kept(world):
    _, _, work, _ = published(world)
    (work.root / "max docs").mkdir()
    (work.root / "max docs/new.md").write_text("# new\n")

    out = work.scope("max docs")

    assert out["status"] == "ok"
    assert out["path"] == "max docs"
    assert out["warnings"] == []


def test_a_dropped_level_is_reported_on_a_bad_target(world):
    _, _, work, _ = published(world)

    out = work.scope("high nonexistent")

    assert out["status"] == "bad-target"
    assert out["target"]["value"] == "nonexistent"
    assert any("ignored `high`" in w for w in out["warnings"])


def test_merged_pr_of_the_current_branch_is_ignored(world):
    _, _, work, m1 = published(world)
    world.gh_reply("pr view", {**pr_reply(work.head()), "state": "MERGED"})

    out = work.scope()

    assert out["status"] == "ok"
    assert out["pr"] is None
    assert out["merge_base"] == m1
    assert out["warnings"] == []


def test_failed_open_pr_lookup_is_a_warning(world):
    _, _, work, m1 = published(world)
    world.gh_reply("pr view", "HTTP 502: Bad Gateway")

    out = work.scope()

    assert out["status"] == "ok"
    assert out["merge_base"] == m1
    assert out["warnings"] == [
        "could not check for an open PR (HTTP 502: Bad Gateway); using the default branch"
    ]


def test_detached_head_skips_the_open_pr_warning(world):
    _, _, work, m1 = published(world)
    work.git("switch", "-q", "--detach")
    world.gh_reply("pr view", "could not determine current branch: not on any branch")

    out = work.scope()

    assert out["status"] == "ok"
    assert out["warnings"] == []


def test_bad_target(world):
    _, _, work, _ = published(world)

    out = work.scope("no-such-thing")

    assert out["status"] == "bad-target"
    assert out["target"]["value"] == "no-such-thing"


# Base resolution details


def test_fetch_failure_falls_back_to_the_local_ref(world):
    bare, _, work, m1 = published(world)
    shutil.rmtree(bare)

    out = work.scope()

    assert out["status"] == "ok"
    assert out["base"] == "origin/main"
    assert out["merge_base"] == m1
    assert "base may be stale (fetch failed, using origin/main)" in out["warnings"]


def test_pr_fetch_failure_falls_back_to_the_local_ref(world):
    bare, _, work, _ = published(world)
    world.gh_reply("pr view", pr_reply(work.head()))
    shutil.rmtree(bare)

    out = work.scope()

    assert out["status"] == "ok"
    assert out["base"] == "origin/main"
    assert out["pr"]["number"] == 7
    assert "base may be stale (fetch failed, using origin/main)" in out["warnings"]


def test_unfetchable_pr_base_never_falls_back_to_a_default_branch(world):
    _, _, work, _ = published(world)
    assert work.has("refs/remotes/origin/HEAD")
    url = "https://github.com/acme/elsewhere/pull/3"
    world.gh_reply("pr view", pr_reply(work.head(), base="release/1.x", url=url, number=3))

    out = work.scope()

    assert out["status"] == "pr-base-unfetchable"
    assert "https://github.com/acme/elsewhere.git" in out["message"]
    assert out["base"] is None


def test_pr_base_with_unrelated_history_is_unfetchable(world):
    _, seed, work, _ = published(world)
    seed.git("switch", "-q", "--orphan", "release/1.x")
    seed.commit("orphan.txt")
    seed.git("push", "-q", "origin", "release/1.x")
    world.gh_reply("pr view", pr_reply(work.head(), base="release/1.x"))

    out = work.scope()

    assert out["status"] == "pr-base-unfetchable"
    assert "no merge base" in out["message"]


@pytest.mark.parametrize(
    "url",
    [
        "git@github.com:acme/widget.git",
        "ssh://git@github.com/acme/widget.git",
        "https://github.com/Acme/Widget",
        "https://github.com/acme/widget/",
    ],
)
def test_pr_base_matches_a_remote_in_any_url_form(world, url):
    bare, _, work, m1 = published(world)
    work.publish_as(url, bare)
    world.gh_reply("pr view", pr_reply(work.head()))

    out = work.scope()

    # Had no remote matched, the base would be fetched from GH_URL, which the
    # test env maps nowhere, so a match is what makes this succeed.
    assert out["status"] == "ok"
    assert out["merge_base"] == m1


def test_pr_base_matches_a_remote_behind_an_ssh_alias(world):
    bare, _, work, m1 = published(world)
    work.publish_as("git@work-gh:acme/widget.git", bare)
    world.gh_reply("pr view", pr_reply(work.head()))

    out = work.scope()

    assert out["status"] == "ok"
    assert out["merge_base"] == m1
    assert out["warnings"] == []


def test_default_branch_lookup_tries_every_remote_url(world):
    _, _, work, m1 = published(world)
    alias = "git@work-gh:acme/widget.git"
    work.git("remote", "set-url", "origin", alias)
    work.alias(alias, "ssh://git@github.com/acme/widget.git")
    work.git("remote", "set-head", "origin", "-d")
    world.env["GIT_SSH_COMMAND"] = "false"
    world.gh_reply("repo view " + GH_REPO, {"defaultBranchRef": {"name": "main"}})

    out = work.scope()

    assert out["status"] == "ok"
    assert out["base"] == "origin/main"
    assert out["merge_base"] == m1
    repo_views = [c[2] for c in world.gh_calls() if c[:2] == ["repo", "view"]]
    assert repo_views == ["https://work-gh/acme/widget", GH_REPO]


def test_equal_merge_bases_either_serves(world):
    bare, _, work, m1 = published(world)
    work.git("remote", "add", "mirror", str(bare))
    work.git("fetch", "-q", "mirror", "main:refs/remotes/mirror/main")
    work.git("remote", "set-head", "mirror", "main")

    out = work.scope()

    assert out["status"] == "ok"
    assert out["base"] == m1
    assert out["warnings"] == []


def test_symref_strips_the_whole_remote_prefix(world):
    bare, seed = world.upstream()
    seed.commit("base.txt")
    seed.git("switch", "-q", "-c", "release/v2")
    v2 = seed.commit("v2.txt")
    seed.git("push", "-q", "origin", "main", "release/v2")
    work = world.clone(bare, "work")
    work.git("symbolic-ref", "refs/remotes/origin/HEAD", "refs/remotes/origin/release/v2")
    work.git("switch", "-q", "-c", "feature", "origin/release/v2")
    work.commit("feature.txt")

    out = work.scope()

    assert out["status"] == "ok"
    assert out["base"] == v2
    assert out["merge_base"] == v2


def test_tracking_ref_after_push_is_never_the_base(world):
    _, _, work, m1 = published(world)
    work.git("push", "-q", "-u", "origin", "feature")

    out = work.scope()

    assert out["base"] == m1
    assert changed(work, out["merge_base"]) == ["feature.txt"]


def test_local_head_when_every_candidate_is_dropped(world):
    repo = world.repo("solo")
    m1 = repo.commit("base.txt")
    repo.git("switch", "-q", "-c", "feature")
    repo.commit("feature.txt")
    repo.git("remote", "add", "origin", "https://github.com/acme/gone.git")
    world.gh_reply("repo view https://github.com/acme/gone", {"defaultBranchRef": {"name": "main"}})

    out = repo.scope()

    assert out["status"] == "ok"
    assert out["base"] == "main"
    assert out["merge_base"] == m1
    assert any(w.startswith("skipped origin/main: git fetch") for w in out["warnings"])


def test_a_hung_fetch_times_out_to_the_local_ref(world, scope, monkeypatch):
    _, _, work, m1 = published(world)
    work.git("config", "remote.origin.uploadpack", "sh -c 'sleep 5'")
    monkeypatch.setattr(scope, "network_deadline", time.monotonic() + 1)

    started = time.monotonic()
    out = scope.resolve(work.git("rev-parse", "--show-toplevel"), "")

    assert time.monotonic() - started < 4
    assert out["status"] == "ok"
    assert out["base"] == "origin/main"
    assert out["merge_base"] == m1
    assert "base may be stale (fetch failed, using origin/main)" in out["warnings"]


def test_a_hung_gh_call_times_out(world, scope, monkeypatch):
    world.gh_reply("repo view", {"sleep": 5})
    monkeypatch.setattr(scope, "network_deadline", time.monotonic() + 1)

    started = time.monotonic()
    out, err = scope.gh(str(world.root), "repo", "view")

    assert time.monotonic() - started < 4
    assert out is None
    assert err == "timed out after 1s"


def test_a_spent_network_budget_runs_nothing(world, scope, monkeypatch):
    _, _, work, _ = published(world)
    monkeypatch.setattr(scope, "network_deadline", time.monotonic() - 1)

    out, err = scope.gh(str(work.root), "repo", "view")
    fetch = scope.git(str(work.root), "fetch", "origin", check=False, network=True)

    assert out is None
    assert err.startswith("timed out")
    assert world.gh_calls() == []
    assert fetch.returncode == 1
    assert fetch.stderr.startswith("timed out")


# Output


def test_top_and_head_are_reported(world):
    _, _, work, _ = published(world)
    top = work.git("rev-parse", "--show-toplevel")

    ok = work.scope()
    bad = work.scope("no-such-thing")

    assert (ok["top"], ok["head"]) == (top, work.head())
    assert (bad["status"], bad["top"], bad["head"]) == ("bad-target", top, work.head())


def test_head_is_null_without_commits(world):
    repo = world.repo("empty")

    out = repo.scope()

    assert out["status"] == "no-scope"
    assert out["top"] == repo.git("rev-parse", "--show-toplevel")
    assert out["head"] is None


# Scope


def test_path_target_from_a_subdirectory(world):
    _, _, work, _ = published(world)
    (work.root / "src").mkdir()
    (work.root / "src/new.py").write_text("x = 1\n")
    (work.root / "docs").mkdir()
    (work.root / "docs/new.md").write_text("# new\n")

    out = work.scope(".", cwd=work.root / "src")

    assert out["status"] == "ok"
    assert out["target"] == {"kind": "path", "value": "."}
    assert out["path"] == "src"
    assert [u["path"] for u in out["untracked"]] == ["src/new.py"]

    whole = work.scope(cwd=work.root / "src")
    assert [u["path"] for u in whole["untracked"]] == ["docs/new.md", "src/new.py"]


def test_path_target_with_a_committed_change_under_it(world):
    _, _, work, _ = published(world)
    work.commit("src/x.py")
    (work.root / "elsewhere.txt").write_text("not under src\n")

    out = work.scope("src")

    assert out["status"] == "ok"
    assert out["path"] == "src"
    assert out["untracked"] == []


def test_path_target_with_no_changes_under_it_is_no_scope(world):
    _, _, work, _ = published(world)
    (work.root / "src").mkdir()
    (work.root / "src/keep.py").write_text("x = 1\n")
    work.git("add", "src/keep.py")
    work.git("commit", "-q", "-m", "keep")
    work.git("push", "-q", "origin", "HEAD:main")

    out = work.scope("src")

    assert out["status"] == "no-scope"
    assert out["path"] == "src"


def test_path_outside_the_repository_is_a_bad_target(world, tmp_path):
    _, _, work, _ = published(world)

    out = work.scope(str(tmp_path))

    assert out["status"] == "bad-target"
    assert "outside this repository" in out["message"]


def test_untracked_symlink_binary_and_awkward_names(world, tmp_path):
    _, _, work, _ = published(world)
    secret = tmp_path / "secret.txt"
    secret.write_text("do not read\n")
    (work.root / "link").symlink_to(secret)
    (work.root / "blob.bin").write_bytes(b"head\0tail")
    (work.root / "café.py").write_text("x = 1\n")
    (work.root / "-n").write_text("dash\n")
    (work.root / "plain space.py").write_text("y = 2\n")
    (work.root / "line\nbreak.py").write_text("z = 3\n")
    with open(os.path.join(os.fsencode(work.root), b"bad\xff.txt"), "wb") as f:
        f.write(b"latin\n")

    out = work.scope()

    assert out["status"] == "ok"
    assert sorted(out["untracked"], key=lambda u: u["path"]) == [
        {"path": "-n", "kind": "file", "target": None},
        {"path": "café.py", "kind": "file", "target": None},
        {"path": "link", "kind": "symlink", "target": str(secret)},
        {"path": "plain space.py", "kind": "file", "target": None},
    ]
    assert sorted(out["skipped"], key=lambda s: s["path"]) == [
        {"path": "bad\\xff.txt", "reason": "name is not valid UTF-8"},
        {"path": "blob.bin", "reason": "binary"},
        {"path": "line\nbreak.py", "reason": "name holds a control character"},
    ]


def test_untracked_listing_is_capped(world):
    _, _, work, _ = published(world)
    for i in range(205):
        (work.root / f"new{i:03}.txt").write_text("x\n")

    out = work.scope()

    assert len(out["untracked"]) == 200
    assert out["untracked"][-1]["path"] == "new199.txt"
    assert "5 more untracked files were not listed" in out["warnings"]


def test_untracked_path_is_matched_literally(world):
    _, _, work, _ = published(world)
    for name in ("a*", "ab"):
        (work.root / name).mkdir()
        (work.root / name / "new.py").write_text("x = 1\n")

    out = work.scope("a*")

    assert out["path"] == "a*"
    assert [u["path"] for u in out["untracked"]] == ["a*/new.py"]


def test_binary_probe_reads_only_the_head(world):
    _, _, work, _ = published(world)
    (work.root / "late.dat").write_bytes(b"a" * 8000 + b"\0")

    out = work.scope()

    assert out["untracked"] == [{"path": "late.dat", "kind": "file", "target": None}]


@pytest.mark.skipif(os.geteuid() == 0, reason="root reads any file")
def test_unreadable_untracked_file_is_skipped(world):
    _, _, work, _ = published(world)
    locked = work.root / "locked.py"
    locked.write_text("x = 1\n")
    locked.chmod(0)
    try:
        out = work.scope()
    finally:
        locked.chmod(0o644)

    assert out["skipped"] == [{"path": "locked.py", "reason": "unreadable (Permission denied)"}]


def test_empty_scope_is_no_scope(world):
    _, _, work, _ = published(world)
    work.git("switch", "-q", "main")

    out = work.scope()

    assert out["status"] == "no-scope"
    assert out["merge_base"] == work.head()
    assert out["untracked"] == []


def test_uncommitted_changes_alone_are_in_scope(world):
    _, _, work, m1 = published(world)
    work.git("switch", "-q", "main")
    (work.root / "base.txt").write_text("edited\n")

    out = work.scope()

    assert out["status"] == "ok"
    assert out["merge_base"] == m1


def test_a_skipped_untracked_file_alone_is_still_scope(world):
    _, _, work, _ = published(world)
    work.git("switch", "-q", "main")
    (work.root / "blob.bin").write_bytes(b"\0")

    out = work.scope()

    assert out["status"] == "ok"
    assert out["skipped"] == [{"path": "blob.bin", "reason": "binary"}]


def test_outside_a_repository_is_an_internal_error(world, tmp_path):
    empty = tmp_path / "empty"
    empty.mkdir()
    world.env["GIT_CEILING_DIRECTORIES"] = str(tmp_path)

    result = world.run(empty)

    assert result.returncode == 1
    assert result.stderr.startswith("scope:")

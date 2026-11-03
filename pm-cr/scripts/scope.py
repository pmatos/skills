#!/usr/bin/env python3
"""Resolve the base of a pm-cr review and gather its scope.

Prints one JSON object on stdout and exits 0 whenever it produced one,
whatever its status. Exits 1 only on an internal error, such as running
outside a git work tree.
"""

import argparse
import json
import math
import os
import re
import stat
import subprocess
import sys
import time

BINARY_PROBE = 8000
UNTRACKED_CAP = 200
# Claude Code's Bash tool gives up at 120s, so every fetch and gh call shares
# a budget that leaves room to print the result.
NETWORK_BUDGET = 90
PR_FIELDS = "url,number,baseRefName,headRefOid,title,body,state"
# Earlier versions of pm-cr took a review level before the target.
LEVELS = ("low", "medium", "high", "xhigh", "max", "ultra")
PR_NUMBER = re.compile(r"#?(\d+)")
PR_URL = re.compile(r"https?://([^/\s]+)/([^/\s]+)/([^/\s]+)/pull/(\d+)(?:[/?#]\S*)?")
SCHEME_URL = re.compile(
    r"(?:https?|ssh|git|git\+ssh|ssh\+git)://(?:[^@/]*@)?([^/:]+)(?::\d*)?/(.*)"
)
SCP_URL = re.compile(r"(?:[^@/]*@)?([^/:]+):(?!//)(.*)")
NO_OPEN_PR = "the current branch has no open PR"
CONTROL = re.compile(r"[\x00-\x1f\x7f]")
ENV = {
    **os.environ,
    "GIT_TERMINAL_PROMPT": "0",
    "GH_PROMPT_DISABLED": "1",
    "GH_NO_UPDATE_NOTIFIER": "1",
}
# Set by main; None leaves network calls unbounded.
network_deadline = None


def run(argv, network=False, **kwargs):
    """subprocess.run, giving a network call only what is left of the budget."""
    timeout = None
    if network and network_deadline is not None:
        timeout = network_deadline - time.monotonic()
        if timeout <= 0:
            return subprocess.CompletedProcess(
                argv, 1, "", "timed out: the network budget is spent"
            )
    try:
        return subprocess.run(
            argv,
            check=False,
            capture_output=True,
            stdin=subprocess.DEVNULL,
            env=ENV,
            timeout=timeout,
            **kwargs,
        )
    except subprocess.TimeoutExpired:
        return subprocess.CompletedProcess(argv, 1, "", f"timed out after {math.ceil(timeout)}s")


def git(top, *args, check=True, network=False):
    result = run(["git", "-C", top, *args], network, encoding="utf-8", errors="surrogateescape")
    if check and result.returncode != 0:
        raise RuntimeError(f"git {' '.join(args)}: {result.stderr.strip()}")
    return result


def gh(top, *args):
    try:
        result = run(["gh", *args], True, cwd=top, encoding="utf-8", errors="replace")
    except OSError as e:
        return None, f"gh could not run ({e.strerror})"
    if result.returncode != 0:
        return None, first_line(result.stderr) or f"gh exited with status {result.returncode}"
    return result.stdout, None


def first_line(text):
    return next((line.strip() for line in text.splitlines() if line.strip()), "")


def rev_parse(top, rev):
    result = git(top, "rev-parse", "--verify", "-q", "--end-of-options", rev, check=False)
    return result.stdout.strip() if result.returncode == 0 else None


def has_ref(top, ref):
    return git(top, "show-ref", "--verify", "-q", ref, check=False).returncode == 0


def is_shallow(top):
    return git(top, "rev-parse", "--is-shallow-repository").stdout.strip() == "true"


def is_ancestor(top, a, b):
    return git(top, "merge-base", "--is-ancestor", a, b, check=False).returncode == 0


def repo_identity(url):
    """Return (host, owner, repo) for a GitHub-shaped clone or PR URL."""
    m = SCHEME_URL.fullmatch(url) or SCP_URL.fullmatch(url)
    if not m:
        return None
    parts = m.group(2).strip("/").removesuffix(".git").split("/")
    if len(parts) != 2 or not all(parts):
        return None
    return m.group(1), parts[0], parts[1]


def same_repo(a, b):
    def key(ident):
        host, owner, repo = ident
        return re.sub(r":\d*$", "", host).lower(), owner.lower(), repo.lower()

    return key(a) == key(b)


def remotes(top):
    return git(top, "remote").stdout.splitlines()


def remote_identities(top, remote):
    raw = git(top, "config", "--get-all", f"remote.{remote}.url", check=False).stdout
    expanded = git(top, "remote", "get-url", remote, check=False).stdout.strip()
    return [i for i in map(repo_identity, raw.splitlines()[:1] + [expanded]) if i]


def record(top, remote, branch):
    local = f"{remote}/{branch}" if has_ref(top, f"refs/remotes/{remote}/{branch}") else None
    return {"remote": remote, "branch": branch, "local_ref": local, "label": f"{remote}/{branch}"}


def pr_view(top, arg):
    """Return (pr, baseRefName, error) from `gh pr view`. A PR that is not
    open counts only when the caller named it."""
    out, err = gh(top, "pr", "view", *([arg] if arg else []), "--json", PR_FIELDS)
    if out is None:
        return None, None, err
    try:
        data = json.loads(out)
    except ValueError:
        return None, None, "gh printed something that is not JSON"
    m = PR_URL.fullmatch(data.get("url") or "")
    if not m or not data.get("baseRefName"):
        return None, None, "gh returned a PR without a usable URL or base branch"
    if arg is None and data.get("state", "OPEN") != "OPEN":
        return None, None, NO_OPEN_PR
    host, owner, repo, number = m.groups()
    pr = {
        "url": data["url"],
        "host": host,
        "owner": owner,
        "repo": repo,
        "number": data.get("number") or int(number),
        "title": data.get("title") or "",
        "body": data.get("body") or "",
        "headRefOid": data.get("headRefOid") or "",
    }
    return pr, data["baseRefName"], None


def repo_relative(top, token):
    """Return the path relative to the repo top, or None when it lies outside.

    Only the parent is resolved first, so a symlink inside the repository
    names itself rather than whatever it points at.
    """
    absolute = os.path.abspath(token)
    real_top = os.path.realpath(top)
    parent = os.path.realpath(os.path.dirname(absolute))
    for candidate in (os.path.join(parent, os.path.basename(absolute)), os.path.realpath(absolute)):
        rel = os.path.relpath(candidate, real_top)
        if rel != os.pardir and not rel.startswith(os.pardir + os.sep):
            return rel.replace(os.sep, "/")
    return None


def classify(top, token):
    """Return (kind, path, problem) for a target token."""
    if not token.strip():
        return "none", None, None
    if PR_NUMBER.fullmatch(token) or PR_URL.fullmatch(token):
        return "pr", None, None
    if not token.startswith("-") and rev_parse(top, f"{token}^{{commit}}"):
        return "ref", None, None
    if os.path.lexists(token):
        rel = repo_relative(top, token)
        if rel is None:
            return "path", None, f"{token} is outside this repository, so it cannot be reviewed."
        return "path", rel, None
    return (
        None,
        None,
        f"{token} is not a PR number or URL, a branch or other ref, or an existing path.",
    )


class Resolver:
    def __init__(self, top, warnings):
        self.top = top
        self.warnings = warnings
        self.unshallowed = None

    def fetch(self, *args):
        return git(
            self.top,
            "fetch",
            "--quiet",
            "--no-tags",
            "--no-recurse-submodules",
            *args,
            check=False,
            network=True,
        )

    def unshallow(self):
        """Fetch the full history once; True only on the call that did so."""
        if self.unshallowed is not None or not is_shallow(self.top):
            return False
        # --deepen=1 is not enough: the branch point can be many commits back.
        result = self.fetch("--unshallow")
        self.unshallowed = result.returncode == 0
        if self.unshallowed:
            self.warnings.append(
                "fetched the full history (git fetch --unshallow) to find the merge base"
            )
        else:
            self.warnings.append(f"git fetch --unshallow failed: {first_line(result.stderr)}")
        return self.unshallowed

    def merge_base(self, rev):
        """Return (oid, None) or (None, why) for the merge base of rev and HEAD."""
        result = git(self.top, "merge-base", rev, "HEAD", check=False)
        # A --depth 1 checkout of the branch makes HEAD the shallow boundary:
        # the graft cuts its link to the base even after a successful fetch.
        if result.returncode != 0 and not result.stderr.strip() and self.unshallow():
            result = git(self.top, "merge-base", rev, "HEAD", check=False)
        if result.returncode == 0:
            return result.stdout.strip(), None
        if result.stderr.strip():
            return None, first_line(result.stderr)
        if is_shallow(self.top):
            return None, "no merge base (shallow clone?)"
        return None, "no merge base: the histories are unrelated"

    def settle(self, rec):
        """Step 3: refresh a record and find its merge base with HEAD.

        Sets base, merge_base and stale on the record and returns None, or
        returns why the record was dropped.
        """
        # The branch operand is never optional: `git fetch <url>` alone fetches
        # that repository's HEAD, not the branch the PR targets.
        result = self.fetch("--end-of-options", rec["remote"], rec["branch"])
        # Capture FETCH_HEAD now, since the next fetch overwrites it, and use
        # the oid rather than <remote>/<branch>, which a --single-branch clone
        # never writes.
        oid = rev_parse(self.top, "FETCH_HEAD^{commit}") if result.returncode == 0 else None
        if oid:
            rec.update(base=oid, rev=oid, stale=False)
        elif rec["local_ref"]:
            rec.update(base=rec["local_ref"], rev=f"refs/remotes/{rec['local_ref']}", stale=True)
        else:
            why = first_line(result.stderr) or "no commit was fetched"
            return f"git fetch {rec['remote']} {rec['branch']} failed: {why}"
        rec["merge_base"], why = self.merge_base(rec["rev"])
        return why

    def pr_record(self, pr, branch):
        ident = (pr["host"], pr["owner"], pr["repo"])
        idents = {remote: remote_identities(self.top, remote) for remote in remotes(self.top)}
        for remote, found in idents.items():
            if any(same_repo(ident, i) for i in found):
                return record(self.top, remote, branch)
        # An SSH Host alias such as `work-gh` never names the PR's host.
        for remote, found in idents.items():
            if any(same_repo(ident, (pr["host"], *i[1:])) for i in found):
                return record(self.top, remote, branch)
        # Built from the PR URL's own host: an Enterprise PR is not on github.com.
        url = f"https://{pr['host']}/{pr['owner']}/{pr['repo']}.git"
        return {"remote": url, "branch": branch, "local_ref": None, "label": f"{branch} from {url}"}

    def candidates(self):
        """Rule 1b: one default-branch candidate per remote that answers.

        Never @{upstream}: after `git push -u` it names this branch's own tip.
        """
        found = []
        for remote in remotes(self.top):
            # Per remote: `git remote add` never sets <remote>/HEAD, so a single
            # pass would always answer from origin.
            prefix = f"refs/remotes/{remote}/"
            ref = git(self.top, "symbolic-ref", "-q", f"{prefix}HEAD", check=False).stdout.strip()
            branch = ref.removeprefix(prefix) if ref.startswith(prefix) else None
            if branch is None:
                branch = self.gh_default_branch(remote)
            if branch:
                found.append(record(self.top, remote, branch))
        return found

    def gh_default_branch(self, remote):
        urls = [f"https://{h}/{o}/{r}" for h, o, r in remote_identities(self.top, remote)]
        for url in dict.fromkeys(urls):
            out, _ = gh(self.top, "repo", "view", url, "--json", "defaultBranchRef")
            try:
                branch = json.loads(out or "{}")["defaultBranchRef"]["name"]
            except (ValueError, KeyError, TypeError):
                branch = None
            if branch:
                return branch
        return None

    def default_base(self):
        """Rules 1b and Step 2: the candidate whose merge base is nearest HEAD."""
        settled = []
        for rec in self.candidates():
            why = self.settle(rec)
            if why:
                self.warnings.append(f"skipped {rec['label']}: {why}")
            else:
                settled.append(rec)
        if not settled:
            return None
        best = settled[0]
        for rec in settled[1:]:
            # Three dots only guard against a base ahead of the branch point: a
            # fork's default three commits behind upstream would put those
            # upstream commits in scope, so the descendant merge base wins.
            if rec["merge_base"] != best["merge_base"] and is_ancestor(
                self.top, best["merge_base"], rec["merge_base"]
            ):
                best = rec
        if any(not is_ancestor(self.top, r["merge_base"], best["merge_base"]) for r in settled):
            self.warnings.append(
                f"the default-branch candidates' merge bases diverge; using {best['label']}"
            )
        for rec in settled:
            if rec["stale"] and rec is not best:
                self.warnings.append(
                    f"{rec['label']} may be stale (fetch failed), so the base pick may be off"
                )
        return best

    def local_head(self):
        """Rule 1c: a local main or master."""
        for name in ("main", "master"):
            if has_ref(self.top, f"refs/heads/{name}"):
                merge_base, why = self.merge_base(f"refs/heads/{name}")
                if merge_base:
                    return {
                        "base": name,
                        "merge_base": merge_base,
                        "stale": False,
                        "label": f"local {name}",
                    }
                self.warnings.append(f"skipped local {name}: {why}")
        return None

    def last_commit(self):
        """Step 4: HEAD~1, deepening a shallow clone by one commit if needed."""
        parent = rev_parse(self.top, "HEAD~1^{commit}")
        if parent is None and is_shallow(self.top):
            result = self.fetch("--deepen=1")
            if result.returncode == 0:
                self.warnings.append(
                    "deepened the shallow clone by one commit (git fetch --deepen=1)"
                )
            else:
                self.warnings.append(f"git fetch --deepen=1 failed: {first_line(result.stderr)}")
            parent = rev_parse(self.top, "HEAD~1^{commit}")
        if parent is None:
            return None
        return {"base": "HEAD~1", "merge_base": parent, "stale": False, "label": "HEAD~1"}


def inspect(full):
    """Return (kind, target, None) for a reviewable file, or (None, None, reason)."""
    try:
        mode = os.lstat(full).st_mode
        if stat.S_ISLNK(mode):
            # Never read through a symlink: it may point outside the repository.
            # The link text is what git itself stores.
            return "symlink", os.readlink(full).decode("utf-8", "replace"), None
    except OSError as e:
        return None, None, f"unreadable ({e.strerror})"
    if not stat.S_ISREG(mode):
        return None, None, "not a regular file"
    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_NONBLOCK", 0)
    try:
        with os.fdopen(os.open(full, flags), "rb") as f:
            head = f.read(BINARY_PROBE)
    except OSError as e:
        return None, None, f"unreadable ({e.strerror})"
    if b"\0" in head:
        return None, None, "binary"
    return "file", None, None


def untracked_files(top, spec):
    """List untracked files under the pathspec, split into reviewable entries
    and skipped ones, plus how many were left unlisted past the cap."""
    # -z keeps every name intact: the plain listing octal-escapes non-ASCII
    # names and C-quotes ones holding a quote, tab or newline.
    listing = run(
        ["git", "-C", top, "--literal-pathspecs", "ls-files", "--others", "--exclude-standard"]
        + ["-z", "--", *spec]
    )
    if listing.returncode != 0:
        raise RuntimeError(f"git ls-files: {listing.stderr.decode('utf-8', 'replace').strip()}")
    top_bytes = os.fsencode(top)
    files, skipped, unlisted = [], [], 0
    for name in listing.stdout.split(b"\0"):
        if not name:
            continue
        if len(files) == UNTRACKED_CAP:
            unlisted += 1
            continue
        try:
            text = name.decode("utf-8")
        except UnicodeDecodeError:
            shown = name.decode("utf-8", "backslashreplace")
            skipped.append({"path": shown, "reason": "name is not valid UTF-8"})
            continue
        if CONTROL.search(text):
            skipped.append({"path": text, "reason": "name holds a control character"})
            continue
        kind, target, reason = inspect(os.path.join(top_bytes, name.rstrip(b"/")))
        if reason:
            skipped.append({"path": text, "reason": reason})
        else:
            files.append({"path": text, "kind": kind, "target": target})
    return files, skipped, unlisted


def drop_level(top, token):
    """Drop a leading former review level, such as `high`, that names no ref or
    path. Return the remaining target and a warning, or the token unchanged."""
    words = token.split(maxsplit=1)
    if not words or not any(level.startswith(words[0].lower()) for level in LEVELS):
        return token, None
    if classify(top, token)[0] is not None or classify(top, words[0])[0] is not None:
        return token, None
    rest = words[1] if len(words) > 1 else ""
    return rest, f"ignored `{words[0]}`: pm-cr now sets the review depth from pm-risk"


def resolve(top, token):
    token, dropped = drop_level(top, token)
    head = rev_parse(top, "HEAD^{commit}")
    out = {
        "status": "ok",
        "message": "",
        "top": top,
        "head": head,
        "target": {"kind": "none", "value": None},
        "base": None,
        "merge_base": None,
        "pr": None,
        "path": None,
        "untracked": [],
        "skipped": [],
        "warnings": [dropped] if dropped else [],
    }

    def finish(status, message):
        out["status"], out["message"] = status, message
        return out

    kind, path, problem = classify(top, token)
    out["target"] = {"kind": kind, "value": None if kind == "none" else token}
    out["path"] = path
    if problem:
        return finish("bad-target", problem)

    if head is None:
        return finish("no-scope", "The repository has no commits yet, so there is no base.")

    res = Resolver(top, out["warnings"])
    if kind == "pr":
        number = PR_NUMBER.fullmatch(token)
        arg = number.group(1) if number else token
        pr, base_branch, err = pr_view(top, arg)
        if pr is None:
            return finish(
                "bad-target",
                f"gh could not look up PR {token} ({err}); check the number, "
                "network access and `gh auth status`, then rerun.",
            )
        out["pr"] = pr
        # Compare commits, not branch names: a stale local branch of the right
        # name has files on disk the PR diff's line numbers do not match.
        if pr["headRefOid"] != head:
            return finish(
                "not-checked-out",
                f"PR #{pr['number']} is not checked out here (HEAD is {head[:12]}, "
                f"the PR head is {pr['headRefOid'][:12] or 'unknown'}); "
                f"run `gh pr checkout {arg}`, then rerun.",
            )
    else:
        if kind == "ref":
            oid = rev_parse(top, f"{token}^{{commit}}")
            if oid != head:
                # A relative ref such as HEAD~1 moves once switched to.
                local = has_ref(top, f"refs/heads/{token}")
                command = f"git switch {token}" if local else f"git switch --detach {oid}"
                message = (
                    f"{token} is not checked out here (HEAD is {head[:12]}, {token} is "
                    f"{oid[:12]}); run `{command}`, then rerun"
                )
                if os.path.lexists(token):
                    message += f"; to review the path instead, pass ./{token}"
                return finish("not-checked-out", message + ".")
        pr, base_branch, err = pr_view(top, None)
        # gh cannot look a PR up from a detached HEAD, which is no failure.
        if err not in (None, NO_OPEN_PR) and not err.startswith("no pull requests found"):
            if git(top, "symbolic-ref", "-q", "HEAD", check=False).returncode == 0:
                res.warnings.append(
                    f"could not check for an open PR ({err}); using the default branch"
                )
        out["pr"] = pr

    last_commit = False
    if pr:
        rec = res.pr_record(pr, base_branch)
        why = res.settle(rec)
        if why:
            # Rule 1a is authoritative: any default branch is a different range
            # and would put commits outside the PR in scope.
            return finish(
                "pr-base-unfetchable",
                f"Could not use {rec['label']}, the base of PR #{pr['number']}: {why}; "
                "check network access, then rerun.",
            )
    else:
        rec = res.default_base() or res.local_head()
        if rec is None:
            rec = res.last_commit()
            last_commit = rec is not None
        if rec is None:
            # Never the empty tree: it would put every existing file in scope.
            return finish(
                "no-scope",
                "No base branch was found and HEAD has no parent commit, "
                "so no scope could be resolved.",
            )
    label = rec["label"]
    if rec["stale"]:
        res.warnings.append(f"base may be stale (fetch failed, using {rec['base']})")
        label += " (local copy)"
    out["base"], out["merge_base"] = rec["base"], rec["merge_base"]

    spec = [path] if path else []
    out["untracked"], out["skipped"], unlisted = untracked_files(top, spec)
    if unlisted:
        res.warnings.append(f"{unlisted} more untracked files were not listed")
    changed = git(
        top, "--literal-pathspecs", "diff", "--name-only", "-z", rec["merge_base"], "--", *spec
    ).stdout
    where = f" under {path}" if path else ""
    if not changed and not out["untracked"] and not out["skipped"]:
        return finish(
            "no-scope",
            f"Nothing to review: no changes{where} since the merge base with {label}, "
            "and no untracked files.",
        )
    if last_commit:
        return finish("ok", f"Reviewing only the last commit{where}: no base branch was found.")
    subject = f"PR #{pr['number']}" if pr else "this branch"
    return finish(
        "ok",
        f"Reviewing {subject}{where} from {rec['merge_base'][:12]}, its merge base with {label}.",
    )


def main():
    global network_deadline
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--target", default="", help="a PR number or URL, a ref, or a path")
    args = parser.parse_args()
    network_deadline = time.monotonic() + NETWORK_BUDGET
    try:
        top = git(os.getcwd(), "rev-parse", "--show-toplevel").stdout.strip()
        result = resolve(top, args.target)
    except RuntimeError as e:
        print(f"scope: {e}", file=sys.stderr)
        return 1
    text = json.dumps(result, indent=2, ensure_ascii=False) + "\n"
    sys.stdout.buffer.write(text.encode("utf-8", "backslashreplace"))
    return 0


if __name__ == "__main__":
    sys.exit(main())

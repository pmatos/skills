#!/usr/bin/env python3
"""Gather the merge-risk facts of a change and the floor they set.

Every fact comes from git metadata and file paths, so the same change and base
always get the same facts and floor. The floor covers only what is risky
whatever the code says: a high-stakes path means at least high, and an edit to
review instructions means at least medium. Size and test coverage are facts
for the judgment, not floors. A repo's own high-stakes paths are read from the
base commit's REVIEW.md, so a change cannot lower its own floor by editing it.

Prints one JSON object on stdout. Exits 1 when git cannot resolve a revision.
"""

import argparse
import fnmatch
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import PurePosixPath

# Size thresholds for the size fact. A change is low only within both LOW
# limits and medium only within all three MEDIUM limits.
LOW_MAX_LINES = 20
LOW_MAX_FILES = 2
MEDIUM_MAX_LINES = 200
MEDIUM_MAX_FILES = 10
MEDIUM_MAX_TOP_DIRS = 3
LIST_LIMIT = 20

INSTRUCTION_FILES = {"claude.md", "claude.local.md", "agents.md", "review.md"}

TEST_DIRS = {"test", "tests", "__tests__", "e2e"}
TEST_NAMES = ("test_*", "*_test.*", "*.test.*", "*_spec.*", "*.spec.*", "conftest.py", "tests.py")
# CamelCase names (FooTest.java, FooTests.cs) need case-sensitive matching,
# or "latest.py" would look like a test.
TEST_NAMES_CASED = ("*Test.*", "*Tests.*")

# Kept in step with review-offline's changeset.py. Skills install separately,
# so neither can import the other.
LOCKFILES = frozenset(
    {
        "package-lock.json",
        "npm-shrinkwrap.json",
        "yarn.lock",
        "pnpm-lock.yaml",
        "bun.lock",
        "bun.lockb",
        "deno.lock",
        "uv.lock",
        "pixi.lock",
        "poetry.lock",
        "pdm.lock",
        "pipfile.lock",
        "cargo.lock",
        "go.sum",
        "gemfile.lock",
        "composer.lock",
        "mix.lock",
        "pubspec.lock",
        "podfile.lock",
        "cartfile.resolved",
        "flake.lock",
        "gradle.lockfile",
        "packages.lock.json",
        "package.resolved",
    }
)
MINIFIED_SUFFIXES = (".min.js", ".min.mjs", ".min.css")
GENERATED_NAME = re.compile(r"(\.generated\.|\.g\.dart$|_pb2(_grpc)?\.pyi?$|\.pb\.go$)")
VENDORED_DIRS = frozenset(
    {"node_modules", "vendor", "third_party", "dist", "__generated__", "generated", ".yarn"}
)
# Vendored third-party code is left out of size but is still high-stakes.
THIRD_PARTY_DIRS = frozenset({"node_modules", "vendor", "third_party", ".yarn"})

# Tests cannot cover these, so they never make a change untested. Dotfiles
# count as config too.
NON_CODE_SUFFIXES = {
    ".md",
    ".markdown",
    ".rst",
    ".txt",
    ".adoc",
    ".json",
    ".yml",
    ".yaml",
    ".toml",
    ".ini",
    ".cfg",
    ".conf",
    ".xml",
    ".csv",
    ".svg",
}
NON_CODE_NAMES = ("license*", "readme*", "notice*", "authors*", "changelog*", "codeowners")

# Matched against the lowercased path. A pattern without "/" matches the file
# name in any directory. A pattern with "/" matches the whole repo-relative
# path, and "*" also matches "/". Lockfiles and third-party directories are
# high-stakes too. Test paths never are.
HIGH_STAKES = (
    # CI and automation run with repository secrets.
    ".github/workflows/*",
    ".github/actions/*",
    ".github/scripts/*",
    ".github/dependabot.yml",
    "action.yml",
    "action.yaml",
    ".gitlab-ci.yml",
    ".circleci/*",
    ".buildkite/*",
    "jenkinsfile",
    "azure-pipelines.yml",
    ".pre-commit-config.yaml",
    # Dependency manifests decide which third-party code runs.
    "package.json",
    "cargo.toml",
    "pyproject.toml",
    "setup.py",
    "setup.cfg",
    "requirements*.txt",
    "requirements/*.txt",
    "pipfile",
    "go.mod",
    "gemfile",
    "pom.xml",
    "build.gradle",
    "build.gradle.kts",
    "composer.json",
    # Deploy config and schema migrations are hard to roll back.
    "dockerfile",
    "dockerfile.*",
    "*.dockerfile",
    "containerfile",
    "containerfile.*",
    "docker-compose*.yml",
    "docker-compose*.yaml",
    "compose.yml",
    "compose.yaml",
    "*.tf",
    "*.tfvars",
    "migrations/*",
    "*/migrations/*",
    "db/migrate/*",
    "*/db/migrate/*",
)

HEADING = re.compile(r"^(#+)\s")
REVIEW_HEADING = re.compile(r"^(#+)\s+high-stakes paths\s*$", re.IGNORECASE)


def git(repo, *args, check=True, env=None):
    result = subprocess.run(
        ["git", "-C", repo, *args],
        check=False,
        capture_output=True,
        encoding="utf-8",
        errors="surrogateescape",
        env=env,
    )
    if check and result.returncode != 0:
        reason = result.stderr.strip() or f"exit status {result.returncode}"
        raise RuntimeError(f"git {' '.join(args)}: {reason}")
    return result


def matches(path, name, pattern):
    return fnmatch.fnmatchcase(path if "/" in pattern else name, pattern)


def is_test(path):
    p = PurePosixPath(path)
    if any(part.lower() in TEST_DIRS for part in p.parts[:-1]):
        return True
    name = p.name
    if any(fnmatch.fnmatchcase(name, n) for n in TEST_NAMES_CASED):
        return True
    return any(fnmatch.fnmatchcase(name.lower(), n) for n in TEST_NAMES)


def is_code(path):
    name = PurePosixPath(path).name.lower()
    if name.startswith(".") or any(fnmatch.fnmatchcase(name, n) for n in NON_CODE_NAMES):
        return False
    return PurePosixPath(name).suffix not in NON_CODE_SUFFIXES


def excluded_reason(path):
    parts = path.split("/")
    name = parts[-1].lower()
    if name in LOCKFILES or name.endswith(".lock"):
        return "lockfile"
    if name.endswith(MINIFIED_SUFFIXES):
        return "minified"
    if name.endswith(".map"):
        return "source map"
    if GENERATED_NAME.search(name):
        return "generated"
    if VENDORED_DIRS.intersection(parts[:-1]):
        return "vendored"
    return None


def expand_glob(glob):
    """Expand gitignore-style "**/" so that it also matches zero directories."""
    if glob.startswith("**/"):
        rest = glob[3:]
        return expand_glob(rest) + expand_glob("*/" + rest)
    if "/**/" in glob:
        head, tail = glob.split("/**/", 1)
        return expand_glob(f"{head}/{tail}") + expand_glob(f"{head}/*/{tail}")
    return [glob]


def high_stakes_match(paths, review_patterns):
    for path in paths:
        name = PurePosixPath(path).name
        for glob in review_patterns:
            if any(matches(path, name, g) for g in expand_glob(glob)):
                return {"path": path, "rule": glob, "source": "REVIEW.md"}
        if is_test(path):
            continue
        lower = path.lower()
        if excluded_reason(path) == "lockfile":
            return {"path": path, "rule": "lockfile", "source": "built-in"}
        if THIRD_PARTY_DIRS.intersection(lower.split("/")[:-1]):
            return {"path": path, "rule": "third-party directory", "source": "built-in"}
        for pattern in HIGH_STAKES:
            if matches(lower, name.lower(), pattern):
                return {"path": path, "rule": pattern, "source": "built-in"}
    return None


def normalize_glob(glob):
    glob = glob.strip()
    for prefix in ("./", "/"):
        glob = glob.removeprefix(prefix)
    if glob.endswith("/"):
        glob += "*"
    return glob


def review_md_patterns(repo, base):
    """Return the globs listed under a "High-stakes paths" heading in the
    base's root REVIEW.md: the first backticked span of each bullet."""
    shown = git(repo, "show", f"{base}:REVIEW.md", check=False)
    if shown.returncode != 0:
        return []
    patterns, depth, fenced = [], None, False
    for line in shown.stdout.splitlines():
        if line.lstrip().startswith(("```", "~~~")):
            fenced = not fenced
            continue
        if fenced:
            continue
        heading = HEADING.match(line)
        if heading:
            m = REVIEW_HEADING.match(line)
            if m:
                depth = len(m.group(1))
                continue
            if depth is not None and len(heading.group(1)) <= depth:
                depth = None
        if depth is not None and re.match(r"^\s*[-*+]\s", line):
            span = re.search(r"`([^`]+)`", line)
            if span:
                patterns.append(normalize_glob(span.group(1)))
    return patterns


def numstat(repo, *rev_args, pathspec, env=None):
    out = git(repo, "diff", "--numstat", "-z", "-M", *rev_args, "--", *pathspec, env=env)
    tokens = out.stdout.split("\0")
    changes, i = [], 0
    while i < len(tokens) and tokens[i]:
        added, deleted, path = tokens[i].split("\t", 2)
        old = None
        if path == "":
            old, path = tokens[i + 1], tokens[i + 2]
            i += 3
        else:
            i += 1
        binary = added == "-"
        changes.append(
            {
                "path": path,
                "old_path": old,
                "added": 0 if binary else int(added),
                "deleted": 0 if binary else int(deleted),
            }
        )
    return changes


def changes(repo, merge_base, head, pathspec):
    if head:
        return numstat(repo, merge_base, head, pathspec=pathspec)
    # Stage the working tree into a scratch index, so that untracked files,
    # renames, binaries, and symlinks are diffed exactly as a commit would be.
    # Copying the real index first keeps git's stat cache, so only changed
    # files are hashed.
    with tempfile.TemporaryDirectory() as tmp:
        index = os.path.join(tmp, "index")
        real = git(repo, "rev-parse", "--git-path", "index").stdout.strip()
        real = real if os.path.isabs(real) else os.path.join(repo, real)
        if os.path.exists(real):
            shutil.copyfile(real, index)
        env = {**os.environ, "GIT_INDEX_FILE": index}
        git(repo, "add", "-A", "--ignore-errors", "--", *(pathspec or [":/"]), check=False, env=env)
        return numstat(repo, "--cached", merge_base, pathspec=pathspec, env=env)


def base_has_tests(repo, base):
    listing = git(repo, "ls-tree", "-r", "-z", "--name-only", base).stdout
    return any(is_test(p) for p in listing.split("\0") if p)


def capped(items):
    return items[:LIST_LIMIT], len(items)


def gather(repo, base, head=None, path=None):
    mb = git(repo, "merge-base", base, head or "HEAD", check=False)
    if mb.returncode != 0:
        reason = mb.stderr.strip() or "no merge base (shallow clone? run git fetch --unshallow)"
        raise RuntimeError(f"git merge-base {base} {head or 'HEAD'}: {reason}")
    merge_base = mb.stdout.strip()
    scoped = changes(repo, merge_base, head, [path] if path else [])
    # Tests for a path target usually live outside it, so look for test
    # changes across the whole change.
    whole = changes(repo, merge_base, head, []) if path else scoped

    review_patterns = review_md_patterns(repo, base)
    lines = files = code_lines = 0
    top_dirs = set()
    excluded, instruction_files, high_stakes = [], [], []
    for c in scoped:
        paths = [p for p in (c["path"], c["old_path"]) if p]
        hit = high_stakes_match(paths, review_patterns)
        if hit:
            high_stakes.append(hit)
        if any(PurePosixPath(p).name.lower() in INSTRUCTION_FILES for p in paths):
            instruction_files.append(c["path"])
        reason = excluded_reason(c["path"])
        if reason:
            excluded.append({"path": c["path"], "reason": reason})
            continue
        n = c["added"] + c["deleted"]
        if c["old_path"] and n == 0:
            continue
        files += 1
        lines += n
        parts = PurePosixPath(c["path"]).parts
        top_dirs.add(parts[0] if len(parts) > 1 else ".")
        if not is_test(c["path"]) and is_code(c["path"]):
            code_lines += n
    # A deleted test is not coverage. An added, edited, or renamed one is.
    test_files = sum(
        1
        for c in whole
        if (c["added"] or c["old_path"])
        and any(is_test(p) for p in (c["path"], c["old_path"]) if p)
    )

    if lines <= LOW_MAX_LINES and files <= LOW_MAX_FILES:
        size = "low"
    elif (
        lines <= MEDIUM_MAX_LINES
        and files <= MEDIUM_MAX_FILES
        and len(top_dirs) <= MEDIUM_MAX_TOP_DIRS
    ):
        size = "medium"
    else:
        size = "high"
    has_tests = base_has_tests(repo, base) if code_lines and not test_files else None
    untested = bool(has_tests)

    facts = [f"size {size}: {lines} lines in {files} files across {len(top_dirs)} top-level dirs"]
    if excluded:
        facts.append(f"not counted in size: {len(excluded)} lockfile, generated, or vendored files")
    if untested:
        facts.append(f"untested: {code_lines} code lines changed and no test file changed")
    elif test_files:
        facts.append(f"tests: {test_files} test files changed")
    for hit in high_stakes[:5]:
        facts.append(f"high-stakes: {hit['path']} ({hit['rule']}, {hit['source']})")
    if len(high_stakes) > 5:
        facts.append(f"high-stakes: {len(high_stakes) - 5} more paths")
    if instruction_files:
        facts.append(f"edits review instructions: {', '.join(instruction_files[:5])}")

    if high_stakes:
        floor, floor_reason = "high", f"touches high-stakes path {high_stakes[0]['path']}"
    elif instruction_files:
        floor, floor_reason = "medium", f"edits {instruction_files[0]}"
    else:
        floor, floor_reason = "low", None

    shown_hs, hs_total = capped(high_stakes)
    shown_ex, ex_total = capped(excluded)
    return {
        "floor": floor,
        "floor_reason": floor_reason,
        "facts": facts,
        "base": base,
        "head": head,
        "merge_base": merge_base,
        "path": path,
        "signals": {
            "size": size,
            "lines": lines,
            "files": files,
            "top_dirs": sorted(top_dirs),
            "code_lines": code_lines,
            "test_files": test_files,
            "base_has_tests": has_tests,
            "untested": untested,
            "instruction_files": instruction_files[:LIST_LIMIT],
            "high_stakes": shown_hs,
            "high_stakes_total": hs_total,
            "excluded": shown_ex,
            "excluded_total": ex_total,
            "review_md_patterns": review_patterns,
        },
        "thresholds": {
            "low_max_lines": LOW_MAX_LINES,
            "low_max_files": LOW_MAX_FILES,
            "medium_max_lines": MEDIUM_MAX_LINES,
            "medium_max_files": MEDIUM_MAX_FILES,
            "medium_max_top_dirs": MEDIUM_MAX_TOP_DIRS,
        },
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--base", required=True, help="the revision the change merges into")
    parser.add_argument("--head", help="the change's tip; omit to use the working tree")
    parser.add_argument("--path", help="limit the facts to this path")
    args = parser.parse_args()

    try:
        top = git(os.getcwd(), "rev-parse", "--show-toplevel").stdout.strip()
        path = None
        if args.path:
            rel = os.path.relpath(os.path.realpath(args.path), os.path.realpath(top))
            path = rel.replace(os.sep, "/")
        result = gather(top, args.base, args.head, path)
    except RuntimeError as e:
        print(f"score_risk: {e}", file=sys.stderr)
        return 1
    json.dump(result, sys.stdout, indent=1)
    print()
    return 0


if __name__ == "__main__":
    sys.exit(main())

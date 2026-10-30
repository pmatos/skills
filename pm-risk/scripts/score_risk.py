#!/usr/bin/env python3
"""Score the merge risk of a change from cheap, deterministic signals.

The same change and base always get the same risk. Every signal comes from
git metadata and file paths, never from reading the code, so the agent that
wrote a change cannot argue its risk down. A repo's own high-stakes paths are
read from the base commit's REVIEW.md, so a change cannot lower its own risk
by editing that file.

Prints one JSON object on stdout. Exits 1 when git cannot resolve a revision.
"""

import argparse
import fnmatch
import json
import os
import re
import subprocess
import sys
from pathlib import PurePosixPath

RISKS = ("low", "medium", "high", "critical")

# Size thresholds. A change is low only within both LOW limits and medium only
# within all three MEDIUM limits. Anything larger is high. Size alone never
# reaches critical.
LOW_MAX_LINES = 20
LOW_MAX_FILES = 2
MEDIUM_MAX_LINES = 200
MEDIUM_MAX_FILES = 10
MEDIUM_MAX_TOP_DIRS = 3

INSTRUCTION_FILES = {"claude.md", "claude.local.md", "agents.md", "review.md"}

TEST_DIRS = {"test", "tests", "__tests__"}
TEST_NAMES = ("test_*", "*_test.*", "*.test.*", "*_spec.*", "*.spec.*")

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
# Vendored third-party code is excluded from size but still high-stakes.
THIRD_PARTY_DIRS = frozenset({"node_modules", "vendor", "third_party", ".yarn"})

# Tests cannot cover these, so they count toward size but never make a change
# untested. Dotfiles count as config too.
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
# high-stakes too.
HIGH_STAKES = (
    # CI and automation run with repository secrets.
    ".github/workflows/*",
    ".github/actions/*",
    ".github/dependabot.yml",
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


def git(repo, *args, check=True):
    result = subprocess.run(
        ["git", "-C", repo, *args],
        check=False,
        capture_output=True,
        encoding="utf-8",
        errors="surrogateescape",
    )
    if check and result.returncode != 0:
        raise RuntimeError(f"git {' '.join(args)}: {result.stderr.strip()}")
    return result


def matches(path, name, pattern):
    return fnmatch.fnmatchcase(path if "/" in pattern else name, pattern)


def is_test(path):
    p = PurePosixPath(path)
    if any(part in TEST_DIRS for part in p.parts[:-1]):
        return True
    return any(fnmatch.fnmatchcase(p.name, n) for n in TEST_NAMES)


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


def high_stakes_match(paths, review_patterns):
    for path in paths:
        lower = path.lower()
        name = PurePosixPath(lower).name
        if excluded_reason(path) == "lockfile":
            return {"path": path, "rule": "lockfile", "source": "built-in"}
        if THIRD_PARTY_DIRS.intersection(lower.split("/")[:-1]):
            return {"path": path, "rule": "third-party directory", "source": "built-in"}
        for pattern in HIGH_STAKES:
            if matches(lower, name, pattern):
                return {"path": path, "rule": pattern, "source": "built-in"}
        for pattern in review_patterns:
            if matches(path, PurePosixPath(path).name, pattern):
                return {"path": path, "rule": pattern, "source": "REVIEW.md"}
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


def numstat(repo, *rev_args, pathspec):
    out = git(repo, "diff", "--numstat", "-z", "-M", *rev_args, "--", *pathspec)
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
            {"path": path, "old_path": old, "lines": 0 if binary else int(added) + int(deleted)}
        )
    return changes


def count_lines(full):
    """Return the file's line count, or None for a binary or unreadable file."""
    try:
        with open(full, "rb") as f:
            head = f.read(8000)
            if b"\0" in head:
                return None
            lines, last = head.count(b"\n"), head[-1:]
            for block in iter(lambda: f.read(1 << 16), b""):
                lines += block.count(b"\n")
                last = block[-1:]
    except OSError:
        return None
    return lines + (1 if last and last != b"\n" else 0)


def untracked_changes(repo, pathspec):
    out = git(repo, "ls-files", "--others", "--exclude-standard", "-z", "--", *pathspec)
    changes = []
    for path in filter(None, out.stdout.split("\0")):
        full = os.path.join(repo, path)
        if os.path.islink(full) or excluded_reason(path):
            changes.append({"path": path, "old_path": None, "lines": 1})
            continue
        if not os.path.isfile(full):
            continue
        lines = count_lines(full)
        if lines is not None:
            changes.append({"path": path, "old_path": None, "lines": lines})
    return changes


def step(risk, change):
    return RISKS[max(0, min(len(RISKS) - 1, RISKS.index(risk) + change))]


def describe(signal, old, new):
    return f"{signal}: {old} -> {new}" if new != old else f"{signal}: stays {old}"


def base_has_tests(repo, base):
    listing = git(repo, "ls-tree", "-r", "-z", "--name-only", base).stdout
    return any(is_test(p) for p in listing.split("\0") if p)


def score(repo, base, head=None, path=None):
    merge_base = git(repo, "merge-base", base, head or "HEAD").stdout.strip()
    pathspec = [path] if path else []
    if head:
        changes = numstat(repo, merge_base, head, pathspec=pathspec)
    else:
        changes = numstat(repo, merge_base, pathspec=pathspec)
        changes += untracked_changes(repo, pathspec)

    review_patterns = review_md_patterns(repo, base)
    lines = files = code_lines = test_files = 0
    top_dirs = set()
    excluded, instruction_files, high_stakes = [], [], []
    for c in changes:
        paths = [p for p in (c["path"], c["old_path"]) if p]
        hit = high_stakes_match(paths, review_patterns)
        if hit:
            high_stakes.append(hit)
        if any(PurePosixPath(p).name.lower() in INSTRUCTION_FILES for p in paths):
            instruction_files.append(c["path"])
        if any(is_test(p) for p in paths):
            test_files += 1
        reason = excluded_reason(c["path"])
        if reason:
            excluded.append({"path": c["path"], "reason": reason})
            continue
        files += 1
        lines += c["lines"]
        parts = PurePosixPath(c["path"]).parts
        top_dirs.add(parts[0] if len(parts) > 1 else ".")
        if not is_test(c["path"]) and is_code(c["path"]):
            code_lines += c["lines"]

    if lines <= LOW_MAX_LINES and files <= LOW_MAX_FILES:
        size_risk = "low"
    elif (
        lines <= MEDIUM_MAX_LINES
        and files <= MEDIUM_MAX_FILES
        and len(top_dirs) <= MEDIUM_MAX_TOP_DIRS
    ):
        size_risk = "medium"
    else:
        size_risk = "high"

    risk = size_risk
    steps = [f"size {size_risk} ({lines} lines, {files} files, {len(top_dirs)} top-level dirs)"]
    has_tests = None
    if code_lines > 0 and test_files == 0:
        has_tests = base_has_tests(repo, base)
    untested = bool(has_tests)
    if untested:
        new = min(step(risk, 1), "high", key=RISKS.index)
        steps.append(describe(f"untested code ({code_lines} lines)", risk, new))
        risk = new
    if high_stakes:
        new = step(risk, 2)
        steps.append(describe(f"high-stakes path {high_stakes[0]['path']}", risk, new))
        risk = new
    if instruction_files:
        new = max(risk, "medium", key=RISKS.index)
        steps.append(describe(f"edits {instruction_files[0]}", risk, new))
        risk = new

    return {
        "risk": risk,
        "size_risk": size_risk,
        "steps": steps,
        "base": base,
        "head": head,
        "merge_base": merge_base,
        "path": path,
        "signals": {
            "lines": lines,
            "files": files,
            "top_dirs": sorted(top_dirs),
            "code_lines": code_lines,
            "test_files": test_files,
            "base_has_tests": has_tests,
            "untested": untested,
            "instruction_files": instruction_files,
            "high_stakes": high_stakes,
            "excluded": excluded,
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
    parser.add_argument("--head", help="the change's tip; omit to score the working tree")
    parser.add_argument("--path", help="limit the score to this path")
    args = parser.parse_args()

    try:
        top = git(os.getcwd(), "rev-parse", "--show-toplevel").stdout.strip()
        path = None
        if args.path:
            rel = os.path.relpath(os.path.realpath(args.path), os.path.realpath(top))
            path = rel.replace(os.sep, "/")
        result = score(top, args.base, args.head, path)
    except RuntimeError as e:
        print(f"score_risk: {e}", file=sys.stderr)
        return 1
    json.dump(result, sys.stdout, indent=2)
    print()
    return 0


if __name__ == "__main__":
    sys.exit(main())

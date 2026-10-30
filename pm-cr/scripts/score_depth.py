#!/usr/bin/env python3
"""Choose pm-cr's review depth from cheap, deterministic signals of a change.

The same diff and base always get the same depth. Every signal comes from git
metadata and file paths, never from reading the code, so the agent that wrote
a change cannot argue its depth down. A repo's own high-stakes paths are read
from the base commit's REVIEW.md, so a change cannot lower its own depth by
editing that file.

Prints one JSON object on stdout. Exits 1 when git cannot resolve the base.
"""

import argparse
import fnmatch
import json
import os
import re
import subprocess
import sys
from pathlib import PurePosixPath

LEVELS = ("low", "medium", "high", "xhigh")

# Size thresholds. A change is low only within both LOW limits and medium only
# within all three MEDIUM limits. Anything larger is high. Size alone never
# reaches xhigh.
LOW_MAX_LINES = 20
LOW_MAX_FILES = 2
MEDIUM_MAX_LINES = 200
MEDIUM_MAX_FILES = 10
MEDIUM_MAX_TOP_DIRS = 3

INSTRUCTION_FILES = {"CLAUDE.md", "CLAUDE.local.md", "AGENTS.md", "REVIEW.md"}

TEST_DIRS = {"test", "tests", "spec", "specs", "__tests__", "testdata", "fixtures"}
TEST_NAMES = ("test_*", "*_test.*", "*.test.*", "*_spec.*", "*.spec.*")

LOCKFILES = (
    "package-lock.json",
    "npm-shrinkwrap.json",
    "yarn.lock",
    "pnpm-lock.yaml",
    "Cargo.lock",
    "poetry.lock",
    "uv.lock",
    "Pipfile.lock",
    "go.sum",
    "Gemfile.lock",
    "composer.lock",
)
GENERATED_NAMES = ("*.min.js", "*.min.css", "*.map")
GENERATED_DIRS = {"vendor", "node_modules"}

# Tests cannot cover these, so they count toward size but never make a change
# untested.
NON_CODE_SUFFIXES = {
    "",
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
    ".lock",
    ".svg",
}

# A pattern without "/" matches the file name in any directory. A pattern with
# "/" matches the whole repo-relative path, and "*" also matches "/".
HIGH_STAKES = (
    # CI and automation run with repository secrets.
    ".github/workflows/*",
    ".github/actions/*",
    ".gitlab-ci.yml",
    ".circleci/*",
    ".buildkite/*",
    "Jenkinsfile",
    "azure-pipelines.yml",
    ".pre-commit-config.yaml",
    # Dependency manifests and lockfiles decide which third-party code runs.
    "package.json",
    "Cargo.toml",
    "pyproject.toml",
    "setup.py",
    "setup.cfg",
    "requirements*.txt",
    "go.mod",
    "Gemfile",
    "pom.xml",
    "build.gradle",
    "build.gradle.kts",
    "composer.json",
    *LOCKFILES,
    # Deploy config and schema migrations are hard to roll back.
    "Dockerfile",
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
)

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


def matches(path, pattern):
    if "/" in pattern:
        return fnmatch.fnmatchcase(path, pattern)
    return fnmatch.fnmatchcase(PurePosixPath(path).name, pattern)


def high_stakes_match(paths, review_patterns):
    for path in paths:
        for source, patterns in (
            ("built-in", HIGH_STAKES),
            ("REVIEW.md", review_patterns),
        ):
            for pattern in patterns:
                if matches(path, pattern):
                    return {"path": path, "pattern": pattern, "source": source}
    return None


def is_test(path):
    p = PurePosixPath(path)
    if any(part in TEST_DIRS for part in p.parts[:-1]):
        return True
    return any(fnmatch.fnmatchcase(p.name, n) for n in TEST_NAMES)


def excluded_reason(path):
    p = PurePosixPath(path)
    if p.name in LOCKFILES:
        return "lockfile"
    if any(fnmatch.fnmatchcase(p.name, n) for n in GENERATED_NAMES):
        return "generated"
    if any(part in GENERATED_DIRS for part in p.parts[:-1]):
        return "vendored"
    return None


def review_md_patterns(repo, base):
    """Return the globs listed under a "High-stakes paths" heading in the
    base's root REVIEW.md, one backticked glob per bullet."""
    shown = git(repo, "show", f"{base}:REVIEW.md", check=False)
    if shown.returncode != 0:
        return []
    patterns, depth = [], None
    for line in shown.stdout.splitlines():
        heading = re.match(r"^(#+)\s", line)
        if heading:
            m = REVIEW_HEADING.match(line)
            if m:
                depth = len(m.group(1))
                continue
            if depth is not None and len(heading.group(1)) <= depth:
                depth = None
        if depth is not None and re.match(r"^\s*[-*+]\s", line):
            patterns.extend(re.findall(r"`([^`]+)`", line))
    return patterns


def tracked_changes(repo, merge_base, pathspec):
    out = git(repo, "diff", "--numstat", "-z", "-M", merge_base, "--", *pathspec)
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
                "lines": 0 if binary else int(added) + int(deleted),
            }
        )
    return changes


def untracked_changes(repo, pathspec):
    out = git(repo, "ls-files", "--others", "--exclude-standard", "-z", "--", *pathspec)
    changes = []
    for path in filter(None, out.stdout.split("\0")):
        full = os.path.join(repo, path)
        if os.path.islink(full):
            changes.append({"path": path, "old_path": None, "lines": 1})
            continue
        if not os.path.isfile(full):
            continue
        with open(full, "rb") as f:
            data = f.read()
        if b"\0" in data[:8000]:
            continue
        lines = data.count(b"\n") + (1 if data and not data.endswith(b"\n") else 0)
        changes.append({"path": path, "old_path": None, "lines": lines})
    return changes


def step(level, change):
    return LEVELS[max(0, min(len(LEVELS) - 1, LEVELS.index(level) + change))]


def at_least(level, floor):
    return max(level, floor, key=LEVELS.index)


def describe(signal, old, new):
    return f"{signal}: {old} -> {new}" if new != old else f"{signal}: stays {old}"


def score(repo, base, path=None):
    merge_base = git(repo, "merge-base", base, "HEAD").stdout.strip()
    pathspec = [path] if path else []
    changes = tracked_changes(repo, merge_base, pathspec)
    changes += untracked_changes(repo, pathspec)

    review_patterns = review_md_patterns(repo, base)
    base_files = git(repo, "ls-tree", "-r", "-z", "--name-only", base).stdout
    base_has_tests = any(is_test(p) for p in base_files.split("\0") if p)

    lines = files = code_lines = test_lines = 0
    top_dirs = set()
    excluded, instruction_files, high_stakes = [], [], []
    for c in changes:
        paths = [p for p in (c["path"], c["old_path"]) if p]
        hit = high_stakes_match(paths, review_patterns)
        if hit:
            high_stakes.append(hit)
        if any(PurePosixPath(p).name in INSTRUCTION_FILES for p in paths):
            instruction_files.append(c["path"])
        reason = excluded_reason(c["path"])
        if reason:
            excluded.append({"path": c["path"], "reason": reason})
            continue
        files += 1
        lines += c["lines"]
        parts = PurePosixPath(c["path"]).parts
        top_dirs.add(parts[0] if len(parts) > 1 else ".")
        if is_test(c["path"]):
            test_lines += c["lines"]
        elif PurePosixPath(c["path"]).suffix.lower() not in NON_CODE_SUFFIXES:
            code_lines += c["lines"]

    if lines <= LOW_MAX_LINES and files <= LOW_MAX_FILES:
        size_level = "low"
    elif (
        lines <= MEDIUM_MAX_LINES
        and files <= MEDIUM_MAX_FILES
        and len(top_dirs) <= MEDIUM_MAX_TOP_DIRS
    ):
        size_level = "medium"
    else:
        size_level = "high"

    level = size_level
    steps = [f"size {size_level} ({lines} lines, {files} files, {len(top_dirs)} top-level dirs)"]
    untested = code_lines > 0 and test_lines == 0 and base_has_tests
    if untested:
        new = min(step(level, 1), "high", key=LEVELS.index)
        steps.append(describe(f"untested code ({code_lines} lines)", level, new))
        level = new
    if high_stakes:
        new = at_least(step(level, 2), "high")
        steps.append(describe(f"high-stakes path {high_stakes[0]['path']}", level, new))
        level = new
    if instruction_files:
        new = at_least(level, "medium")
        steps.append(describe(f"edits {instruction_files[0]}", level, new))
        level = new

    return {
        "level": level,
        "size_level": size_level,
        "steps": steps,
        "base": base,
        "merge_base": merge_base,
        "path": path,
        "signals": {
            "lines": lines,
            "files": files,
            "top_dirs": sorted(top_dirs),
            "code_lines": code_lines,
            "test_lines": test_lines,
            "base_has_tests": base_has_tests,
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
    parser.add_argument("--base", required=True, help="the base Phase 1 diffed against")
    parser.add_argument("--path", help="the path target, if any")
    args = parser.parse_args()

    try:
        top = git(os.getcwd(), "rev-parse", "--show-toplevel").stdout.strip()
        path = None
        if args.path:
            path = os.path.relpath(os.path.abspath(args.path), top).replace(os.sep, "/")
        result = score(top, args.base, path)
    except RuntimeError as e:
        print(f"score_depth: {e}", file=sys.stderr)
        return 1
    json.dump(result, sys.stdout, indent=2)
    print()
    return 0


if __name__ == "__main__":
    sys.exit(main())

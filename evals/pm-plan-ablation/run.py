#!/usr/bin/env python3
"""A/B eval: /investigate with pm-plan available (arm A) vs switched off (arm B).

Each run copies a fixture into a throwaway git repo with a local bare remote,
puts a fake `gh` first on PATH, runs `claude -p "/investigate <N>"`, then grades
the result with hidden tests the agent never saw.

Two fixture kinds:
- toy: `repo/`, `hidden_tests/` (unittest) and `reference/fix.patch`.
- git-snapshot: `fixture.json` naming a source clone and a fix commit. The
  workspace is the tree at the fix's parent as one commit with no history; the
  hidden tests are the fix's versions of `hidden_paths`, run with Bazel.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict, dataclass, field
from pathlib import Path

HERE = Path(__file__).resolve().parent
FIXTURES = HERE / "fixtures"
FAKE_GH_DIR = HERE / "bin"

ARMS = {
    "A": {},
    "B": {"skillOverrides": {"pm-plan": "off"}},
}

GIT_ID = ["-c", "user.name=Eval Bot", "-c", "user.email=eval@example.invalid"]
WEB_PATTERN = re.compile(r"\b(curl|wget|pip install|git (clone|fetch|ls-remote))\b")


@dataclass
class Fixture:
    name: str
    issue: int
    spec: dict | None

    @classmethod
    def load(cls, name: str) -> Fixture:
        d = FIXTURES / name
        issue = json.loads((d / "issue.json").read_text())["number"]
        spec_file = d / "fixture.json"
        spec = json.loads(spec_file.read_text()) if spec_file.exists() else None
        return cls(name, issue, spec)

    @property
    def dir(self) -> Path:
        return FIXTURES / self.name

    @property
    def source(self) -> Path:
        assert self.spec
        return Path(os.path.expanduser(self.spec["source"]))

    @property
    def bazel_targets(self) -> list[str]:
        assert self.spec
        targets = []
        for path in self.spec["hidden_paths"]:
            pkg, name = path.rsplit("/", 1)
            targets.append(f"//{pkg}:{name}.test")
        return targets


@dataclass
class RunResult:
    fixture: str
    arm: str
    run: int
    workspace: str
    exit_code: int | None = None
    timed_out: bool = False
    is_error: bool | None = None
    stop_reason: str | None = None
    cost_usd: float | None = None
    duration_s: float | None = None
    num_turns: int | None = None
    output_tokens: int | None = None
    pm_plan_fired: bool = False
    ultraplan_files: list[str] = field(default_factory=list)
    agent_calls: int = 0
    advisor_calls: int = 0
    advisor_errors: int = 0
    skills_called: list[str] = field(default_factory=list)
    pm_plan_listed: bool | None = None
    web_access: list[str] = field(default_factory=list)
    hidden_passed: int = 0
    hidden_total: int = 0
    visible_ok: bool = False
    grade_passed: bool = False
    grade_exit: int | None = None
    commits: int = 0
    pushed: bool = False
    pr_opened: bool = False
    issue_commented: bool = False
    files_changed: list[str] = field(default_factory=list)

    @property
    def solved(self) -> bool:
        return self.grade_passed


def sh(cmd: list[str], cwd: Path, env: dict | None = None, check: bool = True) -> str:
    out = subprocess.run(cmd, cwd=cwd, env=env, check=check, capture_output=True, text=True)
    return out.stdout


def git_show(fx: Fixture, rev_path: str) -> bytes:
    return subprocess.run(
        ["git", "-C", str(fx.source), "show", rev_path], check=True, capture_output=True
    ).stdout


def setup_workspace(fx: Fixture, root: Path) -> Path:
    seed = root / "seed"
    if fx.spec:
        seed.mkdir()
        archive = subprocess.run(
            ["git", "-C", str(fx.source), "archive", f"{fx.spec['fix']}^"],
            check=True,
            capture_output=True,
        ).stdout
        subprocess.run(["tar", "-x", "-C", str(seed)], input=archive, check=True)
    else:
        shutil.copytree(fx.dir / "repo", seed, ignore=shutil.ignore_patterns("__pycache__"))
    env = {
        **os.environ,
        "GIT_AUTHOR_DATE": "2026-01-05T10:00:00Z",
        "GIT_COMMITTER_DATE": "2026-01-05T10:00:00Z",
    }
    sh(["git", "init", "-q", "-b", "main"], seed)
    sh(["git", "add", "-A", "-f"], seed)
    sh(["git", *GIT_ID, "commit", "-q", "-m", "Initial import"], seed, env=env)
    sh(["git", "clone", "-q", "--bare", str(seed), str(root / "origin.git")], root)
    ws = root / "ws"
    sh(["git", "clone", "-q", str(root / "origin.git"), str(ws)], root)
    shutil.rmtree(seed)
    sh(["git", "config", "user.name", "Eval Bot"], ws)
    sh(["git", "config", "user.email", "eval@example.invalid"], ws)
    sh(["git", "switch", "-q", "-c", f"issue-{fx.issue}"], ws)
    if fx.spec and fx.spec.get("setup"):
        script = (fx.dir / fx.spec["setup"]).resolve()
        subprocess.run(
            ["bash", str(script)],
            cwd=ws,
            env={**os.environ, "EVAL_SOURCE": str(fx.source)},
            check=True,
        )
    return ws


def run_unittest(start_dir: str, ws: Path) -> tuple[int, int, bool]:
    proc = subprocess.run(
        [sys.executable, "-m", "unittest", "discover", "-s", start_dir],
        check=False,
        cwd=ws,
        env={**os.environ, "PYTHONPATH": str(ws)},
        capture_output=True,
        text=True,
        timeout=120,
    )
    out = proc.stderr
    ran = int(m.group(1)) if (m := re.search(r"Ran (\d+) test", out)) else 0
    bad = sum(int(n) for n in re.findall(r"(?:failures|errors)=(\d+)", out))
    return max(ran - bad, 0), ran, proc.returncode == 0 and ran > 0


def run_hidden(fx: Fixture, ws: Path, log: Path, res: RunResult, timeout: int) -> None:
    """Overlay the hidden tests on the workspace and run them."""
    if fx.spec:
        for path in fx.spec["hidden_paths"]:
            (ws / path).parent.mkdir(parents=True, exist_ok=True)
            (ws / path).write_bytes(git_show(fx, f"{fx.spec['fix']}:{path}"))
        try:
            proc = subprocess.run(
                ["./bazelw", "test", "--test_output=errors", *fx.bazel_targets],
                cwd=ws,
                check=False,
                capture_output=True,
                text=True,
                timeout=timeout,
            )
            log.write_text(proc.stdout + proc.stderr)
            res.grade_exit = proc.returncode
            passed = proc.returncode == 0
        except subprocess.TimeoutExpired:
            log.write_text("grading timed out\n")
            passed = False
        res.hidden_total = len(fx.bazel_targets)
        res.hidden_passed = res.hidden_total if passed else 0
        res.visible_ok = True
        res.grade_passed = passed
        subprocess.run(["./bazelw", "shutdown"], cwd=ws, check=False, capture_output=True)
    else:
        _, _, res.visible_ok = run_unittest("tests", ws)
        hidden = ws / "_eval_hidden"
        shutil.copytree(fx.dir / "hidden_tests", hidden, dirs_exist_ok=True)
        res.hidden_passed, res.hidden_total, _ = run_unittest("_eval_hidden", ws)
        shutil.rmtree(hidden)
        res.grade_passed = (
            res.hidden_total > 0 and res.hidden_passed == res.hidden_total and res.visible_ok
        )


def parse_stream(path: Path, res: RunResult) -> None:
    for line in path.read_text().splitlines():
        try:
            msg = json.loads(line)
        except json.JSONDecodeError:
            continue
        if msg.get("type") == "system" and msg.get("subtype") == "init":
            res.pm_plan_listed = "pm-plan" in (msg.get("skills") or [])
        if msg.get("type") == "assistant":
            for block in msg.get("message", {}).get("content", []):
                kind, name = block.get("type"), block.get("name")
                if kind == "tool_use" and name == "Skill":
                    skill = str(block.get("input", {}).get("skill", ""))
                    res.skills_called.append(skill)
                    if skill.split(":")[-1] == "pm-plan":
                        res.pm_plan_fired = True
                elif kind == "tool_use" and name in ("Agent", "Task"):
                    res.agent_calls += 1
                elif kind == "tool_use" and name in ("WebFetch", "WebSearch"):
                    res.web_access.append(f"{name}: {json.dumps(block.get('input'))[:200]}")
                elif kind == "tool_use" and name == "Bash":
                    command = str(block.get("input", {}).get("command", ""))
                    if WEB_PATTERN.search(command):
                        res.web_access.append(f"Bash: {command[:200]}")
                elif kind == "server_tool_use" and name == "advisor":
                    res.advisor_calls += 1
                elif kind == "advisor_tool_result":
                    if "error" in str((block.get("content") or {}).get("type", "")):
                        res.advisor_errors += 1
        if msg.get("type") == "result":
            res.is_error = msg.get("is_error")
            res.stop_reason = msg.get("subtype")
            res.cost_usd = msg.get("total_cost_usd")
            res.num_turns = msg.get("num_turns")
            res.output_tokens = (msg.get("usage") or {}).get("output_tokens")


def grade(fx: Fixture, ws: Path, root: Path, res: RunResult, timeout: int) -> None:
    res.ultraplan_files = sorted(
        str(p.relative_to(ws)) for p in ws.glob(".ultraplan/**/*") if p.is_file()
    )
    if res.ultraplan_files:
        res.pm_plan_fired = True
    res.commits = int(
        sh(["git", "rev-list", "--count", "origin/main..HEAD"], ws, check=False).strip() or 0
    )
    res.pushed = bool(
        sh(
            ["git", "--git-dir", str(root / "origin.git"), "branch", "--list", f"issue-{fx.issue}"],
            ws,
        )
    )
    changed = sh(["git", "diff", "--name-only", "origin/main"], ws, check=False).split()
    untracked = sh(["git", "ls-files", "--others", "--exclude-standard"], ws, check=False).split()
    res.files_changed = sorted(set(changed + untracked))
    (root / "final.diff").write_text(sh(["git", "diff", "origin/main"], ws, check=False))

    gh_log = root / "gh.log"
    calls = (
        [json.loads(line) for line in gh_log.read_text().splitlines()] if gh_log.exists() else []
    )
    res.pr_opened = any(c[:2] == ["pr", "create"] for c in calls)
    res.issue_commented = any(c[:2] == ["issue", "comment"] for c in calls)

    run_hidden(fx, ws, root / "grade.log", res, timeout)


def one_run(fixture: str, arm: str, i: int, args, work: Path, out: Path) -> RunResult:
    fx = Fixture.load(fixture)
    # A unique path per run: Claude keys auto-memory on the working directory.
    root = Path(tempfile.mkdtemp(prefix=f"{fixture}-{arm}-{i}-", dir=work))
    ws = setup_workspace(fx, root)
    (root / "ghcfg").mkdir()
    shutil.copytree(FAKE_GH_DIR, root / "bin")
    shutil.copy(fx.dir / "issue.json", root / "issue.json")
    res = RunResult(fixture, arm, i, str(ws))

    inherited = {k: v for k, v in os.environ.items() if not k.startswith("CLAUDE_CODE_")}
    env = {
        **inherited,
        "PATH": f"{root / 'bin'}{os.pathsep}{os.environ['PATH']}",
        "EVAL_ISSUE_JSON": str(root / "issue.json"),
        "EVAL_GH_LOG": str(root / "gh.log"),
        "GH_CONFIG_DIR": str(root / "ghcfg"),
        "GH_TOKEN": "eval-invalid-token",
    }
    cmd = [
        "claude",
        "-p",
        f"/investigate {fx.issue}",
        "--disallowedTools",
        "WebFetch",
        "WebSearch",
        "--model",
        args.model,
        "--output-format",
        "stream-json",
        "--verbose",
        "--dangerously-skip-permissions",
        "--max-budget-usd",
        str(args.budget_usd),
        "--settings",
        json.dumps(ARMS[arm]),
    ]
    stream = root / "run.jsonl"
    started = time.monotonic()
    print(f"[start] {fixture} arm {arm} run {i}", flush=True)
    with stream.open("w") as fh, (root / "stderr.log").open("w") as err:
        try:
            res.exit_code = subprocess.run(
                cmd, check=False, cwd=ws, env=env, stdout=fh, stderr=err, timeout=args.timeout
            ).returncode
        except subprocess.TimeoutExpired:
            res.timed_out = True
    res.duration_s = round(time.monotonic() - started, 1)

    parse_stream(stream, res)
    grade(fx, ws, root, res, args.grade_timeout)
    drop_project_state(ws, root)

    dest = out / f"{fixture}-{arm}-{i}"
    dest.mkdir(parents=True)
    for name in ("run.jsonl", "stderr.log", "gh.log", "final.diff", "grade.log"):
        if (root / name).exists():
            shutil.copy(root / name, dest / name)
    (dest / "result.json").write_text(json.dumps(asdict(res) | {"solved": res.solved}, indent=2))
    print(
        f"[done]  {fixture} arm {arm} run {i}: solved={res.solved} "
        f"pm_plan={res.pm_plan_fired} web={len(res.web_access)} "
        f"cost=${res.cost_usd} time={res.duration_s}s",
        flush=True,
    )
    return res


def drop_project_state(ws: Path, root: Path) -> None:
    """Move the run's Claude project dir (transcripts, auto-memory) out of ~/.claude."""
    slug = re.sub(r"[^A-Za-z0-9]", "-", str(ws))
    project = Path.home() / ".claude" / "projects" / slug
    if project.is_dir():
        shutil.move(str(project), str(root / "claude-project"))


def validate(fixture: str, work: Path, timeout: int) -> bool:
    """Hidden tests must fail on the starting tree and pass with the reference fix."""
    fx = Fixture.load(fixture)
    root = work / f"validate-{fixture}"
    root.mkdir(parents=True)
    ws = setup_workspace(fx, root)

    before = RunResult(fixture, "-", 0, str(ws))
    run_hidden(fx, ws, root / "before.log", before, timeout)
    sh(["git", "checkout", "-q", "--", "."], ws)
    sh(["git", "clean", "-fdq", "-e", "local.bazelrc"], ws)

    if fx.spec:
        patch = subprocess.run(
            ["git", "-C", str(fx.source), "diff", f"{fx.spec['fix']}^", fx.spec["fix"]],
            check=True,
            capture_output=True,
        ).stdout
    else:
        patch = (fx.dir / "reference" / "fix.patch").read_bytes()
    subprocess.run(["git", "apply", "-"], cwd=ws, input=patch, check=True)
    after = RunResult(fixture, "-", 0, str(ws))
    run_hidden(fx, ws, root / "after.log", after, timeout)

    # Bazel exits 3 when tests ran and failed; anything else is a broken setup.
    failed_properly = before.grade_exit == 3 if fx.spec else not before.grade_passed
    ok = failed_properly and after.grade_passed
    print(
        f"[validate] {fixture}: before={'pass' if before.grade_passed else 'fail'} "
        f"(exit {before.grade_exit}) "
        f"after={'pass' if after.grade_passed else 'fail'} -> {'OK' if ok else 'BAD'} "
        f"(logs in {root})",
        flush=True,
    )
    return ok


def summarize(results: list[RunResult], out: Path) -> str:
    rows = [
        "| fixture | arm | run | solved | pm-plan fired | agents | advisor (errors) "
        "| web | cost $ | time s | turns | PR |",
        "|---|---|---|---|---|---|---|---|---|---|---|---|",
    ]
    for r in sorted(results, key=lambda r: (r.fixture, r.arm, r.run)):
        cost = f"{r.cost_usd:.2f}" if r.cost_usd is not None else "?"
        rows.append(
            f"| {r.fixture} | {r.arm} | {r.run} | {'yes' if r.solved else 'no'} | "
            f"{'yes' if r.pm_plan_fired else 'no'} | {r.agent_calls} | "
            f"{r.advisor_calls} ({r.advisor_errors}) | {len(r.web_access)} | {cost} | "
            f"{r.duration_s} | {r.num_turns} | {'yes' if r.pr_opened else 'no'} |"
        )
    table = "# pm-plan ablation results\n\n" + "\n".join(rows) + "\n"
    (out / "summary.md").write_text(table)
    (out / "summary.json").write_text(
        json.dumps([asdict(r) | {"solved": r.solved} for r in results], indent=2)
    )
    return table


def main() -> int:
    all_fixtures = sorted(
        d.name for d in FIXTURES.iterdir() if d.is_dir() and (d / "issue.json").exists()
    )
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--fixtures", nargs="+", default=all_fixtures)
    p.add_argument("--arms", nargs="+", default=list(ARMS), choices=list(ARMS))
    p.add_argument("--runs", type=int, default=1)
    p.add_argument("--model", default="claude-opus-5-5")
    p.add_argument("--budget-usd", type=float, default=15.0, help="per-run cap passed to claude")
    p.add_argument("--timeout", type=int, default=2400, help="per-run wall-clock limit, seconds")
    p.add_argument("--grade-timeout", type=int, default=1800, help="hidden-test limit, seconds")
    p.add_argument("--jobs", type=int, default=2)
    p.add_argument(
        "--work-dir", type=Path, help="where throwaway workspaces go (default: a new temp dir)"
    )
    p.add_argument(
        "--validate", action="store_true", help="check the fixtures instead of running agents"
    )
    args = p.parse_args()

    work = args.work_dir or Path(tempfile.mkdtemp(prefix="pm-plan-ablation-"))
    if args.validate:
        oks = [validate(f, work, args.grade_timeout) for f in args.fixtures]
        return 0 if all(oks) else 1

    out = HERE / "results" / time.strftime("%Y%m%d-%H%M%S")
    out.mkdir(parents=True)
    jobs = [(f, a, i) for f in args.fixtures for i in range(1, args.runs + 1) for a in args.arms]
    print(f"{len(jobs)} runs, workspaces in {work}, results in {out}", flush=True)

    with ThreadPoolExecutor(max_workers=args.jobs) as pool:
        results = list(pool.map(lambda j: one_run(*j, args, work, out), jobs))

    print(summarize(results, out))
    return 0


if __name__ == "__main__":
    sys.exit(main())

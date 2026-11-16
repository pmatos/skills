#!/usr/bin/env python3
"""A/B eval: /investigate with pm-plan available (arm A) vs switched off (arm B).

Each run copies a fixture into a throwaway git repo with a local bare remote,
puts a fake `gh` first on PATH, runs `claude -p "/investigate <N>"`, then grades
the result with hidden tests the agent never saw.
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
    hidden_passed: int = 0
    hidden_total: int = 0
    visible_ok: bool = False
    commits: int = 0
    pushed: bool = False
    pr_opened: bool = False
    issue_commented: bool = False
    files_changed: list[str] = field(default_factory=list)

    @property
    def solved(self) -> bool:
        return self.hidden_total > 0 and self.hidden_passed == self.hidden_total and self.visible_ok


def sh(cmd: list[str], cwd: Path, env: dict | None = None, check: bool = True) -> str:
    out = subprocess.run(cmd, cwd=cwd, env=env, check=check, capture_output=True, text=True)
    return out.stdout


def setup_workspace(fixture: str, root: Path, issue: int) -> Path:
    seed = root / "seed"
    shutil.copytree(FIXTURES / fixture / "repo", seed, ignore=shutil.ignore_patterns("__pycache__"))
    env = {
        **os.environ,
        "GIT_AUTHOR_DATE": "2026-01-05T10:00:00Z",
        "GIT_COMMITTER_DATE": "2026-01-05T10:00:00Z",
    }
    sh(["git", "init", "-q", "-b", "main"], seed)
    sh(["git", "add", "-A"], seed)
    sh(["git", *GIT_ID, "commit", "-q", "-m", "Initial import"], seed, env=env)
    sh(["git", "clone", "-q", "--bare", str(seed), str(root / "origin.git")], root)
    ws = root / "ws"
    sh(["git", "clone", "-q", str(root / "origin.git"), str(ws)], root)
    shutil.rmtree(seed)
    sh(["git", "config", "user.name", "Eval Bot"], ws)
    sh(["git", "config", "user.email", "eval@example.invalid"], ws)
    sh(["git", "switch", "-q", "-c", f"issue-{issue}"], ws)
    return ws


def run_tests(start_dir: str, ws: Path) -> tuple[int, int, bool]:
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
                if block.get("type") != "tool_use":
                    continue
                if block.get("name") == "Skill":
                    skill = str(block.get("input", {}).get("skill", ""))
                    res.skills_called.append(skill)
                    if skill.split(":")[-1] == "pm-plan":
                        res.pm_plan_fired = True
                elif block.get("name") in ("Agent", "Task"):
                    res.agent_calls += 1
            for block in msg.get("message", {}).get("content", []):
                if block.get("type") == "server_tool_use" and block.get("name") == "advisor":
                    res.advisor_calls += 1
                elif block.get("type") == "advisor_tool_result":
                    if "error" in str((block.get("content") or {}).get("type", "")):
                        res.advisor_errors += 1
        if msg.get("type") == "result":
            res.is_error = msg.get("is_error")
            res.stop_reason = msg.get("subtype")
            res.cost_usd = msg.get("total_cost_usd")
            res.num_turns = msg.get("num_turns")
            res.output_tokens = (msg.get("usage") or {}).get("output_tokens")


def grade(fixture: str, ws: Path, root: Path, issue: int, res: RunResult) -> None:
    res.ultraplan_files = sorted(
        str(p.relative_to(ws)) for p in ws.glob(".ultraplan/**/*") if p.is_file()
    )
    if res.ultraplan_files:
        res.pm_plan_fired = True
    res.commits = int(
        sh(["git", "rev-list", "--count", "origin/main..HEAD"], ws, check=False).strip() or 0
    )
    res.pushed = bool(
        sh(["git", "--git-dir", str(root / "origin.git"), "branch", "--list", f"issue-{issue}"], ws)
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

    _, _, res.visible_ok = run_tests("tests", ws)
    hidden = ws / "_eval_hidden"
    shutil.copytree(FIXTURES / fixture / "hidden_tests", hidden, dirs_exist_ok=True)
    res.hidden_passed, res.hidden_total, _ = run_tests("_eval_hidden", ws)
    shutil.rmtree(hidden)


def one_run(fixture: str, arm: str, i: int, args, work: Path, out: Path) -> RunResult:
    issue_file = FIXTURES / fixture / "issue.json"
    issue = json.loads(issue_file.read_text())["number"]
    root = work / f"{fixture}-{arm}-{i}"
    root.mkdir(parents=True)
    ws = setup_workspace(fixture, root, issue)
    (root / "ghcfg").mkdir()
    shutil.copytree(FAKE_GH_DIR, root / "bin")
    shutil.copy(issue_file, root / "issue.json")
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
        f"/investigate {issue}",
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
    grade(fixture, ws, root, issue, res)

    dest = out / root.name
    dest.mkdir(parents=True)
    for name in ("run.jsonl", "stderr.log", "gh.log", "final.diff"):
        if (root / name).exists():
            shutil.copy(root / name, dest / name)
    (dest / "result.json").write_text(json.dumps(asdict(res) | {"solved": res.solved}, indent=2))
    print(
        f"[done]  {fixture} arm {arm} run {i}: solved={res.solved} "
        f"hidden={res.hidden_passed}/{res.hidden_total} pm_plan={res.pm_plan_fired} "
        f"cost=${res.cost_usd} time={res.duration_s}s",
        flush=True,
    )
    return res


def summarize(results: list[RunResult], out: Path) -> str:
    rows = [
        "| fixture | arm | run | solved | hidden | pm-plan fired | agents | advisor (errors) | cost $ | time s | turns | PR |",
        "|---|---|---|---|---|---|---|---|---|---|---|---|",
    ]
    for r in sorted(results, key=lambda r: (r.fixture, r.arm, r.run)):
        cost = f"{r.cost_usd:.2f}" if r.cost_usd is not None else "?"
        rows.append(
            f"| {r.fixture} | {r.arm} | {r.run} | {'yes' if r.solved else 'no'} | "
            f"{r.hidden_passed}/{r.hidden_total} | {'yes' if r.pm_plan_fired else 'no'} | {r.agent_calls} | "
            f"{r.advisor_calls} ({r.advisor_errors}) | {cost} | {r.duration_s} | {r.num_turns} | {'yes' if r.pr_opened else 'no'} |"
        )
    table = "# pm-plan ablation results\n\n" + "\n".join(rows) + "\n"
    (out / "summary.md").write_text(table)
    (out / "summary.json").write_text(
        json.dumps([asdict(r) | {"solved": r.solved} for r in results], indent=2)
    )
    return table


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument(
        "--fixtures", nargs="+", default=sorted(d.name for d in FIXTURES.iterdir() if d.is_dir())
    )
    p.add_argument("--arms", nargs="+", default=list(ARMS), choices=list(ARMS))
    p.add_argument("--runs", type=int, default=1)
    p.add_argument("--model", default="claude-opus-5-5")
    p.add_argument("--budget-usd", type=float, default=15.0, help="per-run cap passed to claude")
    p.add_argument("--timeout", type=int, default=2400, help="per-run wall-clock limit, seconds")
    p.add_argument("--jobs", type=int, default=2)
    p.add_argument(
        "--work-dir", type=Path, help="where throwaway workspaces go (default: a new temp dir)"
    )
    args = p.parse_args()

    work = args.work_dir or Path(tempfile.mkdtemp(prefix="pm-plan-ablation-"))
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

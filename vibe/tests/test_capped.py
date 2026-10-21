"""CLI regressions; opt into real systemd/cgroup tests with VIBE_SYSTEMD_TESTS=1."""

import os
from pathlib import Path
import re
import subprocess
import sys
import time

import pytest

CAPPED = Path(__file__).resolve().parents[1] / "scripts" / "capped.sh"
LIVE = pytest.mark.skipif(
    os.environ.get("VIBE_SYSTEMD_TESTS") != "1",
    reason="requires a user systemd manager with cgroup-v2 memory delegation",
)


def run(*args, env=None):
    clean_env = os.environ.copy()
    clean_env.pop("VIBE_ALLOW_UNCAPPED", None)
    clean_env.pop("VIBE_MAX_MEM_GB", None)
    clean_env.update(env or {})
    return subprocess.run(
        [str(CAPPED), *args], capture_output=True, text=True, env=clean_env, timeout=30
    )


@pytest.mark.parametrize("ceiling", ["abc", "32G", "0", "-1"])
def test_invalid_ceiling_is_usage_error(ceiling):
    result = run("-n", "--", "true", env={"VIBE_MAX_MEM_GB": ceiling})
    assert result.returncode == 2
    assert "VIBE_MAX_MEM_GB wants a positive whole number" in result.stderr


def test_lock_wait_requires_lock():
    result = run("-n", "-w", "1", "--", "true")
    assert result.returncode == 2
    assert "-w requires the shared lock" in result.stderr


def test_accepting_properties_without_enforcement_is_refused(tmp_path):
    fake = tmp_path / "systemd-run"
    fake.write_text(
        '#!/bin/sh\nwhile [ "$#" -gt 0 ] && [ "$1" != sh ]; do shift; done\nexec "$@"\n'
    )
    fake.chmod(0o755)
    # A stale success stamp must not bypass the current enforcement check.
    (tmp_path / "vibe-capped.ok").touch()
    result = run(
        "-n",
        "-m",
        "1",
        "--",
        "echo",
        "UNSAFE_COMMAND_RAN",
        env={"PATH": f"{tmp_path}:{os.environ['PATH']}", "XDG_RUNTIME_DIR": str(tmp_path)},
    )
    assert result.returncode == 3
    assert "cannot enforce" in result.stderr
    assert "UNSAFE_COMMAND_RAN" not in result.stdout


@LIVE
def test_low_ceiling_clamps_default_and_enforces_group_oom():
    result = run(
        "-n",
        "--",
        "sh",
        "-c",
        "base=/sys/fs/cgroup$(cut -d: -f3 /proc/self/cgroup); "
        'cat "$base/memory.max" "$base/memory.swap.max" "$base/memory.oom.group"',
        env={"VIBE_MAX_MEM_GB": "1"},
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout.splitlines() == ["1073741824", "0", "1"]


@LIVE
@pytest.mark.parametrize("timeout_args", [[], ["-t", "5"]])
def test_missing_command_has_consistent_status(timeout_args):
    result = run("-n", "-m", "1", *timeout_args, "--", "/no/such/vibe-command")
    assert result.returncode == 127, result.stderr


@LIVE
def test_quoted_arguments_and_command_exit():
    result = run("-n", "-m", "1", "--", "printf", "%s", "a b;$literal;$$;${HOME}")
    assert result.returncode == 0, result.stderr
    assert result.stdout == "a b;$literal;$$;${HOME}"
    assert run("-n", "-m", "1", "--", "sh", "-c", "exit 42").returncode == 42


@LIVE
def test_timeout_is_reported():
    result = run("-n", "-m", "1", "-t", "1", "--", "sleep", "10")
    assert result.returncode == 124
    assert "exit 124: timeout status" in result.stderr


@LIVE
def test_worker_oom_fails_surviving_driver():
    driver = (
        "import subprocess,sys; "
        "worker=subprocess.run([sys.executable,'-c','x=bytearray(2*1024**3)']); "
        "print('driver survived worker',worker.returncode); sys.exit(0)"
    )
    result = run("-n", "-m", "1", "-t", "20", "--", sys.executable, "-c", driver)
    assert result.returncode in (137, 143), result.stderr
    assert "killed by a signal" in result.stderr
    assert "driver survived worker" not in result.stdout


@LIVE
def test_scope_stop_kills_children_and_releases_lock(tmp_path):
    lock = tmp_path / "gate.lock"
    pidfile = tmp_path / "child.pid"
    logfile = tmp_path / "gate.log"
    with logfile.open("w") as log:
        process = subprocess.Popen(
            [
                str(CAPPED),
                "-m",
                "1",
                "-l",
                str(lock),
                "--",
                "sh",
                "-c",
                'echo $$ > "$1"; exec sleep 60',
                "child",
                str(pidfile),
            ],
            stdout=log,
            stderr=log,
        )
        scope = None
        try:
            deadline = time.monotonic() + 10
            while time.monotonic() < deadline:
                match = re.search(r"scope (vibe-capped-\d+\.scope)", logfile.read_text())
                if match:
                    scope = match[1]
                if scope and pidfile.exists():
                    break
                assert process.poll() is None, logfile.read_text()
                time.sleep(0.05)
            assert scope and pidfile.exists(), logfile.read_text()
            child = int(pidfile.read_text())
            subprocess.run(["systemctl", "--user", "stop", scope], check=True, timeout=10)
            assert process.wait(timeout=10) in (137, 143)
            with pytest.raises(ProcessLookupError):
                os.kill(child, 0)
            assert run("-m", "1", "-w", "1", "-l", str(lock), "--", "true").returncode == 0
        finally:
            if scope:
                subprocess.run(
                    ["systemctl", "--user", "stop", scope], capture_output=True, timeout=10
                )
            if process.poll() is None:
                process.kill()
                process.wait(timeout=10)

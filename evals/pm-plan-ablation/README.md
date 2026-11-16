# pm-plan ablation

Does `/investigate` do better with `/pm-plan` than without it?

- **Arm A**: the normal skill set.
- **Arm B**: the same, with `{"skillOverrides": {"pm-plan": "off"}}`, so
  investigate falls back to writing its own plan.

Each run copies a fixture into a throwaway git repo whose `origin` is a local
bare repo, starts on branch `issue-<N>`, and runs `claude -p "/investigate <N>"`.
A fake `gh` (`bin/gh`) serves the fixture's `issue.json` and logs PR and comment
calls. `GH_CONFIG_DIR` and `GH_TOKEN` point at nothing, so the real `gh` cannot
post. Runs load your normal user settings, CLAUDE.md and plugins.

A run is **solved** when the hidden tests pass and the visible tests still pass.
The agent never sees the hidden tests. The harness also records cost, time,
turns, whether pm-plan fired (a `Skill` call or a `.ultraplan/` file), and
whether a commit, push and PR happened.

## Run

```bash
./run.py --runs 1 --jobs 2                       # pilot: every fixture, both arms
./run.py --fixtures eventlog --arms B --runs 3   # a subset
```

Results go to `results/<timestamp>/`: `summary.md`, `summary.json`, and per run
the stream-json log, `gh.log`, `final.diff` and `result.json`.

## Fixtures

`fixtures/<name>/` holds `repo/` (the project), `issue.json`, `hidden_tests/`,
and `reference/fix.patch`. Before adding a fixture, check that the hidden tests
fail on `repo/` and pass with the reference patch applied.

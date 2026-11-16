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

Web tools are disabled in every run. The harness also flags any shell command
that reaches the network (`web` column), since that could find the real fix.

## Fixtures

Every fixture has an `issue.json`, served by the fake `gh`. There are two kinds:

- **Toy** (`shipquote`, `eventlog`): `repo/` is the project, `hidden_tests/`
  holds unittest files, and `reference/fix.patch` is a known-good fix.
- **Snapshot** (`modular-*`): `fixture.json` names a source clone and the commit
  that fixed a real issue. The workspace is the tree at that commit's parent,
  imported as one commit with no history. The hidden tests are the fix's
  versions of `hidden_paths`, run with Bazel. The issue keeps its real text
  under a new number.

The modular fixtures need `~/dev/modular` to have run a Bazel build once.
`fixtures/_modular/setup.sh` reuses the LLVM source that build fetched, because
the LLVM tarball for older pins no longer matches its checksum.

Check new fixtures before spending on agent runs. The hidden tests must fail on
the starting tree and pass with the reference fix:

```bash
./run.py --validate --fixtures modular-hash-signed-zero
```

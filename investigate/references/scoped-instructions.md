# Scoped Instructions — Per-Package CLAUDE.md / AGENTS.md

Detailed reference for Phase 3.2 of the investigate skill. The deterministic
walk lives in `scripts/collect-instructions.sh`; this file explains *why* it
works the way it does and how the caller is expected to use its output.

## The problem

Phase 3.1 reads only the top-level `CLAUDE.md` / `AGENTS.md`. In a repo with
per-package or nested instructions, that misses the checks and commit rules that
apply to the files a fix actually touches. Fixing code under `frontend/` from the
repo root skips `frontend/AGENTS.md`, so the validation phase omits required
commands and the generated PR is likely to fail project policy. Phase 3.2 closes
that gap by consulting every instruction file on the path from each changed file
up to the repo root.

## Why the walk is deferred until the plan is known

The set of instruction files that governs a change depends on *which files*
change, and that is only settled once Phase 4 has produced a plan. So Phase 3.1
still runs first — its baseline informs planning and general context — but the
ancestor walk runs afterwards, over the plan's target paths (4A.4 / 4B.3), and
feeds the merged command set into validation (4A.6 / 4B.5). Running it earlier
would have nothing concrete to walk.

## What `collect-instructions.sh` does

Given the changed paths, for each one it walks from that path's directory up to
the repository root and collects every `CLAUDE.md` / `AGENTS.md` it finds. Paths
need not exist yet: a to-be-created file's nearest existing ancestor directory is
the starting point, because instruction files can only live in directories that
already exist. Paths outside the repo root are skipped with a warning — repo
instructions do not govern them.

Output is repo-relative, one file per line, ordered **baseline (repo root) →
closest (deepest directory)**. Empty output (still exit 0) means no scoped file
governs any of the paths, and the caller falls back to the 3.1 baseline alone.
Exit 1 is reserved for hard failures: no paths given, or not inside a git repo.

## Dedup: symlinks and shared ancestors

Many repos symlink `AGENTS.md → CLAUDE.md` so the two harnesses read identical
instructions. The script must not emit that content twice, and must not let a
symlink masquerade as a distinct scoped override. It dedups by same-file identity
(the `-ef` test, which compares device + inode through symlinks), so an
`AGENTS.md` that is really the same file as a `CLAUDE.md` is emitted once.

Because several changed paths often share ancestors (and the root is an ancestor
of everything), directories are scanned **root-first**. That ordering matters for
aliasing: when a deeper file is a symlink to a shallower one, recording the
shallower occurrence first means the alias dedups to the *baseline* label rather
than the deeper path — the baseline never silently disappears behind one of its
own aliases.

## Merge: closest wins, and surface divergence

The caller reads the listed files and merges them with **closest-wins**
precedence: the top-level file is the baseline; a nearer file overrides it on
conflict and may add checks the baseline omits. Reading top to bottom applies
that precedence directly, since later lines are the closer files.

Merging is a judgment the caller makes, not something the script flattens — it
cannot tell whether `frontend/AGENTS.md`'s `pnpm test` *replaces* or *augments*
the root's `npm test`. So when a scoped file changes or adds a command relative
to the baseline, the caller surfaces a one-line divergence note — which file,
which command — rather than silently folding it in. The skill is deciding what
checks to run, not just what prose to load, so keeping that reasoning auditable
matters: a reviewer can see why the validation command set differs from the
top-level defaults.

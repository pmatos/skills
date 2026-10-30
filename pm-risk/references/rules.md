# Facts and floor

`../scripts/score_risk.py` gathers these facts from git metadata and file
paths. Its thresholds and path lists are constants at the top of the script.

- **Size**: changed lines (added plus deleted), changed files, and top-level
  directories, rated low, medium, or high. Lockfiles, minified, generated, and
  vendored files don't count, and neither does a pure rename.
- **Tests**: whether code changed while no test file did, in a repo whose
  base has tests. Docs, config, and dotfiles never count as code. Vendored,
  generated, and CI files never count as tests, and a deleted test is not
  coverage.
- **High-stakes paths**: CI, hooks, and agent config, wherever they sit.
  Dependency manifests, lockfiles, vendored third-party code, deploy config,
  and schema migrations, except under a test or fixture directory. Plus the
  repo's own list.
- **Review instructions**: edits to `CLAUDE.md`, `CLAUDE.local.md`,
  `AGENTS.md`, or `REVIEW.md`.

Only two facts set the floor, because they are risky whatever the code says:
a high-stakes path means at least high, and an edit to review instructions
means at least medium. Size and tests are evidence for the Impact and
Verification judgments, so a contained, tested refactor can still be low.

## Repo-specific high-stakes paths

A repo adds its own in its root `REVIEW.md`, under a `High-stakes paths`
heading, with one glob per top-level bullet in backticks:

```markdown
## High-stakes paths

- `src/auth/`
- `**/billing/**/*.py`
```

A glob without `/` matches a file name in any directory, and `*` also
matches `/`. An entry without a wildcard also covers the directory of that
name, and `**/` also matches no directory. The script reads `REVIEW.md` from the base, never from
the change, so a change cannot lower its own floor by editing the list.

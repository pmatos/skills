# Risk rules

`../scripts/score_risk.py` applies these rules in order. Its thresholds and
path lists are constants at the top of the script, and its JSON output
carries the raw signals and thresholds behind every score.

1. **Size.** Count changed lines (added plus deleted), changed files, and
   top-level directories. Lockfiles, minified files, source maps, generated
   code, and vendored directories don't count, and a pure rename counts no
   lines. A small change is `low`, a mid-sized one is `medium`, and anything
   larger is `high`. Size alone never reaches `critical`.
2. **Untested code.** When code changes, no test file changes, and the base
   has tests, raise one level, to at most `high`. Docs, config, and dotfiles
   never count as code.
3. **High-stakes paths.** When the change touches one, raise two levels. The
   built-in list covers CI and automation, dependency manifests, lockfiles,
   vendored third-party code, deploy config, and schema migrations.
4. **Instruction files.** When the change edits a `CLAUDE.md`,
   `CLAUDE.local.md`, `AGENTS.md`, or `REVIEW.md`, the risk is at least
   `medium`.

Size is the strongest signal on purpose: larger changes ship more defects.
A behavior-preserving refactor still scores by its size, so a refactor that
keeps scoring `high` is a cue to split it.

## Repo-specific high-stakes paths

A repo adds its own in its root `REVIEW.md`, under a `High-stakes paths`
heading, with one glob per bullet in backticks:

```markdown
## High-stakes paths

- `src/auth/*`
- `billing/`
```

A glob without `/` matches a file name in any directory, `*` also matches
`/`, and a trailing `/` covers the whole directory. The script reads
`REVIEW.md` from the base, never from the change, so a change cannot lower
its own risk by editing the list.

## Reproducibility

The same change and base always get the same risk. Without `--head`, the
script scores the working tree against the merge base, including untracked
files. With `--head`, it scores only the committed range.

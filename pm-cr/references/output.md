# Output

## Reporting findings

Rank findings by severity tier (`../SKILL.md` Constraints) within the
depth's cap. Each finding carries:

- `file`, `line`
- `summary` — one sentence: the defect stated as fact, then the fix
- `short_summary` — the claim in 60 characters or fewer, with no rationale
- `failure_scenario` — concrete inputs or state, then the wrong output or
  crash. For a cleanup finding, the concrete cost.
- `category` — `security`, `correctness`, or `performance` for those tiers.
  Otherwise the angle: `reuse`, `simplification`, `efficiency`, `altitude`,
  `conventions`, or `scope`.
- `verdict` — `CONFIRMED` or `PLAUSIBLE`, when a verify pass produced one

If the `ReportFindings` tool is available, call it once with the findings,
or with an empty array, and do not also print them. If the caller asked for
JSON, make the final message nothing but a JSON array of the findings.
Otherwise print one line per finding, `path:line — the defect and the
concrete failure`, or `(none)`. Never publish an artifact of the review.

## Writing a finding

State the defect as fact, then give the fix with a directive verb such as
Fix, Remove, Change, Add, Return, or Guard. Never hedge: no "maybe", "might
want to", "consider", "possibly", "could be", or "you may want to". A
PLAUSIBLE finding carries its uncertainty in `verdict` and in the trigger
that `failure_scenario` names, not in the wording.

```text
Bad:  Consider checking whether user could be null here.
Good: user.id throws on an expired session, because getUser() returns null
      there (auth.ts:42); return 401 before line 57.
```

## Assessment

After the findings, except in JSON mode, give your overall take on the
change in one to three sentences, or one at the low depth: its main risk
area, or whether it looks sound. Do not summarize the change, and do not
count or repeat the findings. Also state every disclosure here: files not
reviewed, edited review instructions, a stale base, or a single-pass
review.

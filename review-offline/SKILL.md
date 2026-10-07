---
name: review-offline
description: This skill should be used when the user asks to "review this PR in a webpage", "review offline", "open a review page", "review this changeset together", "review the diff with you in the browser", or "collect review comments in a markdown file", or invokes /review-offline. Builds a local review page (animated diagram of what the change does, pre-loaded agent suggestions, accept/edit/comment/ask) for a PR, branch, commit range, path or working-tree diff, and saves the accepted review to `.reviews/<slug>.md`. Read-only upstream; never posts, pushes or edits.
argument-hint: "[pr-number | pr-url | branch | HEAD | a..b | path] [--effort low|medium|high|xhigh] [--fresh]"
user-invocable: true
---

# review-offline

Turn a changeset into a local webpage where the user and an agent review the
code together. The page opens on a picture of what the change does, already holds
the agent's suggestions, and ends with the accepted comments saved to a markdown
file. What happens to that file afterwards is the user's call and outside this
skill.

**This skill never posts, comments, pushes, fixes or edits.** It never modifies a
tracked file and never writes to a remote. It reads the network (`gh` reads, a
`git fetch` of the PR head) and writes only: `<repo>/.reviews/`, a scratch run
directory under the system temp dir, a git worktree entry while a PR or branch is
checked out for reading, and the host CLI's own session and state files. Do not run
any `gh` command that writes, and do not apply a suggestion to the working tree.

Requires Python 3.11 or newer and a git repository. The scripts use only the
standard library.

## Locating the scripts

`<skill-dir>` below is the directory holding this file, the base directory your
harness reports when it loads the skill. Always run the scripts by absolute path from
the user's repository, as `python3 <skill-dir>/scripts/review_offline.py ...`; the
current directory is the user's repo, not the skill's. The files under
`<skill-dir>/references/` are read only where a step says so.

## Step 1: know your host and settings

The page's agent features run headless through the same harness that runs you. Pass
its identity yourself as `--host`: `claude` (Claude Code), `codex` (Codex CLI) or
`omp` (Oh My Pi). There is no auto-detection, so do not guess: you know what you are.

Pass `--model <id>` only when you know the exact id your CLI accepts; omit it
otherwise (a wrong id makes every pass fail). Unpinned, the child runs on the CLI's
configured default model, and the page says so.

Effort is `--effort low|medium|high|xhigh`, default `high`; the user can override it
in the arguments. A host that cannot honor an effort level drops it and the page says
so. Expect `high` to take a minute or two and spend model usage on roughly a dozen
headless calls; mention that if the user seems cost-sensitive. Split the user's
arguments into the target (everything that is not a `--` option) and these options.

## Step 2: prepare the changeset

```bash
python3 <skill-dir>/scripts/review_offline.py prepare "<target>" --repo <repo-dir>
```

Always quote the target (`"#123"` is a shell comment unquoted). `<target>` is anything
that defines a changeset:

- a PR number, `#123` or URL (the repo's `origin` must be that PR's repository);
- a branch or `HEAD`: the whole branch since its merge base with the default branch,
  not only the last commit (on the default branch itself, the last commit);
- a range `a..b` or `a...b`;
- a path: working-tree changes limited to it;
- omitted: the working tree (staged, unstaged and untracked) against the merge base
  with the default branch, which already includes every commit on the current branch.

Translate natural phrases yourself: "current branch", "my changes" and "this branch"
mean omit the target; "this PR" means look up the PR for the checked-out branch with
a read-only `gh pr view` and pass its number; "my last commit" means the range
`HEAD~1..HEAD`.

The command prints JSON: `run_dir`, `slug`, `root` (the tree to read), `base`, `head`,
the files, `graph_path`, `graph_reusable` and `resumed`. If it exits non-zero or lists
no files, report the message and stop; do not guess another target. When `resumed` is
true a saved review exists for this slug and `serve` continues it; tell the user. Pass
`--fresh` only when the user asks to start over (it sets the saved state aside as
`.bak`).

## Step 3: author the visualization

Skip this step when `graph_reusable` is true and the graph at `graph_path` still
validates. Otherwise read the diff at `<run_dir>/prefetch/diff.patch` and the code
around it, then write `graph_path` following `<skill-dir>/references/graph-schema.md`
and `<skill-dir>/references/viz-authoring.md` (an example is at
`<skill-dir>/references/example-graph.json`). Quality here is the point of the page:
pick the nodes a reviewer can name, include unchanged neighbours so the blast radius
shows, write one to three flows with plain-prose captions, and add a panel only when
the graph draws the point badly.

```bash
python3 <skill-dir>/scripts/review_offline.py validate-graph <run_dir>/graph.json --root <root> --changeset <run_dir>/changeset.json
```

Repeat until it prints `ok`. Its errors name the exact field.

## Step 4: serve, in the background

Start the server as a background command so the review can run while you wait:

```bash
python3 <skill-dir>/scripts/review_offline.py serve <run_dir> --host <host> [--model <id>] [--effort <level>]
```

Use the harness's background-run option and note where its output goes. A harness with
no background mode can use `nohup <command> > <run_dir>/serve.log 2>&1 &` and read the
log. The server binds only to 127.0.0.1 and starts the host CLI, so a sandboxed
harness may need to allow both. Read the output once or twice until the first line,
`LISTENING http://127.0.0.1:<port>/#t=<token>`, appears; give the user that link and
open it if the environment can (`xdg-open`, `open`).

If the first line is `REVIEW-ERROR <message>`, nothing is running. Fix a graph error
and restart; for any other error (an unreadable saved state, for example) report it
and leave the saved review alone.

Then say, briefly: the page is open, the agent's suggestions will appear on it as they
finish, and the user clicks **Finish review** when done. Stop and wait. Do not poll in
a loop, and do not review the code yourself in the meantime; the page already holds
the agent's pass and the user is reading it. The server ends itself after 30 idle
minutes (`--idle-minutes` changes that).

## Step 5: when the server ends

The command's last line is the only signal. Act on exactly one of:

- `REVIEW-COMPLETE <path>` — say: "Review complete, results are in `<path>`, do
  you want me to do anything with it?" Then wait for the user. Posting the comments
  upstream or applying fixes is a separate request they make.
- `REVIEW-SUSPENDED stopped <state-path>` — the server stopped before Finish (idle
  timeout or interrupt). The review is saved but not finished. Say so, never say it is
  complete, and tell the user that running `/review-offline` on the same target
  resumes it.
- `REVIEW-ERROR <message>` — report it and stop.
- Anything else (a traceback, a usage error, a killed process): report the last lines
  verbatim, never call the review complete, and run
  `python3 <skill-dir>/scripts/review_offline.py cleanup <run_dir>` to remove any
  worktree left behind.

If the harness does not notify you when a background command ends, tell the user to
reply when they have clicked **Finish review**, then read the end of the output.

## Failure handling

- `prepare` fails on a target it cannot resolve, a missing `gh`, an unreachable PR, or
  a PR whose repository is not `origin` (use a clone of that repository): report the
  message and stop.
- The agent passes can fail while the page still works: the page shows each pass's
  status, and the user can ask the agent on the page instead.
- Resuming a review whose code has changed marks affected comments stale and reruns
  the agent passes; finished reviews keep their accepted comments.

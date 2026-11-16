# Gather the diff

Resolve the base to diff against, in this order — but if the skill's
argument is a PR number, resolve that PR first and let its `url` and
`baseRefName` stand in for rule 1's ambient lookup:

1. If the current branch has an open PR, use its base: `gh pr view --json
   url,baseRefName`. `baseRefName` is only a branch name, so take the base
   *repository* from `url` — a PR URL is always
   `https://github.com/<owner>/<repo>/pull/<n>` in the base repo, never in
   the fork. The base remote is the local remote whose *fetch* URL — the
   `(fetch)` line of `git remote -v`, equivalently `git remote get-url
   <name>` — points at that `<owner>/<repo>` (strip `git@github.com:`,
   `https://github.com/`, and a trailing `.git` before comparing). Match
   the fetch URL specifically: a remote may carry a separate push URL,
   and `git fetch` uses the fetch one. If no remote matches — a fork
   checkout with no `upstream` — use the clone URL
   `https://github.com/<owner>/<repo>.git`, which `git fetch` accepts in
   place of a remote name. If `gh pr view` cannot resolve a single
   repository on its own, fall through to rule 2.
2. Otherwise derive both the remote and the branch — do not assume a
   remote is named `origin`. The base remote is `origin` if `git remote`
   lists it, else the sole remote it lists, else the one the current
   branch tracks (`git config --get branch.<branch>.remote`). The base is
   that remote's default branch — `git symbolic-ref
   refs/remotes/<base-remote>/HEAD` with the
   `refs/remotes/<base-remote>/` prefix stripped — falling back to `main`
   or `master` if that symref is absent.

Refresh that base before diffing — `git fetch <base-remote> <base>` — and
diff `FETCH_HEAD...HEAD`. Both halves matter: hard-coding `origin/<base>`
diffs against the fork's copy of the branch on a cross-repository PR, and
any remote-tracking ref goes stale between fetches. Either way the
three-dot merge-base slides backwards and already-merged commits enter the
scope, where the skill's Phase 2 would edit code the change never touched. Do not
substitute `baseRefOid`: it is frozen at the base tip recorded when the PR
was opened and does not follow the base branch as that branch moves, so it
reintroduces the same stale merge-base. Not `@{upstream}` — once the
branch is pushed that resolves to the branch's own remote copy, so the
three-dot diff is empty and the whole committed PR silently drops out of
scope. Not the local base branch either: it is often stale, which widens
the range to already-merged work.

If the fetch fails, and only when the base remote is a *named* remote,
fall back to `<base-remote>/<base>...HEAD` and say the base may be stale —
a clone-URL base has no local ref to fall back to. With no usable remote
at all, use the local `<base>...HEAD`, and `git diff HEAD~1` only as a
last resort.

Then pick up the working tree as well — this review often runs before the
commit. `git diff HEAD` covers modified tracked files; `git -c
core.quotePath=false ls-files --others --exclude-standard` lists the
untracked ones, which `git diff HEAD` omits entirely. The
`core.quotePath=false` matters: without it a non-ASCII name is
octal-escaped into a quoted path that does not exist, so an untracked
`café.py` would be skipped rather than reviewed. A name holding a quote,
tab, or newline is still C-quoted onto a single line; that residue fails
the regular-file check below and is reported as skipped, which is the
intended fail-closed outcome. Do not reach for `-z` here — NUL separators
do not survive into this listing as text, so every path boundary is lost.

Treat every name in that listing — and any target `readlink` prints
below — as repository-controlled data, never as command text. Never
paste one into a command line: bind it to a variable and expand it
double-quoted, iterating the listing with `while IFS= read -r p` and
using `"$p"` throughout. Unquoted, an everyday name splits on its spaces
— `test -f ./has space.txt` exits 2, so the file silently drops out of
the review scope this phase exists to gather — and a name holding
`$(...)`, a backtick, or `;` is executed by the shell before the command
it was meant as an argument to ever runs. The same applies to the
branch, remote, and PR ref names rules 1 and 2 hand to `git`: `git
check-ref-format` accepts all three of those metacharacters in a ref
name, and on a cross-repository PR the head ref name is chosen by the
fork owner. Quoting and the `--`/`./` below are not substitutes for one
another — `--` and `./` keep an option-looking name out of option
position, which matters only after the shell has already split and
expanded the line, while quoting stops the shell acting on the name at
all — so use both.

Read through an untracked path only once you have positively established
it is a regular file. Run `readlink -- "$p"` first — with the `--`,
because the worktree may hold a file literally named `-n`, which
`readlink` otherwise parses as an option. If it succeeds the path is a
symlink, so record the target it prints as the single added line and do
not read through the link — that is what git itself stores for a
symlink, and dereferencing one pulls whatever it points at, possibly a
file outside the repository, into the review and its subagent prompts. A
failure proves nothing on its own: `readlink` exits 1 alike for "not a
symlink" and for a path it could not resolve. So read the file only once
`test -f "./$p"` succeeds and `test -L "./$p"` fails — the `./` keeps a
leading `-` out of option position, which `test` cannot escape with `--`
— and quote and `./`-prefix every path you hand to a reading command
too. Where you use a structured file-reading tool instead of a shell,
the path is a parameter rather than command text and quoting is moot,
but the same "never as command text" rule applies. Skip and report
anything that classifies as neither. Then read the file in full and
treat it as added lines. Do
not stage anything to make a file show up in the diff (no `git add`, no
`git add -N`) — leave the index exactly as you found it.

If a PR number, branch name, or file path was passed as the skill's
argument, review that target instead. A PR number or branch name must name
the current checkout. For a branch name, compare it against `git rev-parse
--abbrev-ref HEAD`; for a PR number, read `gh pr view <n> --json
url,baseRefName,headRefName,headRefOid,isCrossRepository` and compare its
`headRefName` against that same value. Stop if they differ — `gh pr view`
only displays a PR, it does not switch checkouts, so the skill's Phase 2 would
otherwise apply fixes to whatever branch is actually checked out. That
same command supplies the `url` and `baseRefName` rule 1 needs: a branch
can carry open PRs into two different bases, and diffing against the wrong
one both drops changes belonging to the requested PR and pulls in changes
outside it. A branch name identifies no repository, so when
`isCrossRepository` is true additionally require `git
merge-base --is-ancestor <headRefOid> HEAD` to exit zero; otherwise a
fork's same-named branch passes the name check while its code is nowhere
in this worktree. Any non-zero exit stops, including the exit-128 `fatal:
Not a valid commit name` an unfetched fork commit gives. Ancestry rather
than equality, and only for cross-repository PRs: this skill usually runs
before the commit, so a same-repo branch is routinely ahead of — or
rebased off — the PR head. Ask for the target to be checked out first.

Treat the combined result as the review scope; if it comes out empty, say
the scope was empty rather than reporting the code clean.

# Force-push safety: why the lease is taken before the rebase

`git push --force-with-lease` refuses the push when the remote ref no longer holds the value the
pusher expected. Everything therefore depends on **where that expected value comes from**.

## The sequence that defeats the lease

A tempting reading of "refresh the tracking ref before force-pushing" produces this:

```bash
git rebase origin/main
# ... resolve conflicts, run the gate ...
git fetch origin "$BRANCH"                                   # refresh
git push --force-with-lease="$BRANCH:$(git rev-parse "origin/$BRANCH")"
```

If a colleague pushed to `$BRANCH` while the rebase was being resolved, the `git fetch` on line 3
pulls **their** commit down, and line 4 arms the lease with **their** SHA. The lease check then
passes — the remote really is at that value — and the force-push deletes their commit. The bare form
`--force-with-lease` (no explicit value) fails the same way: it reads the remote-tracking ref, which
the fetch just updated.

The lease is not weakened by this; it is armed with the wrong reference point. It answers "has the
remote moved since I last looked?" and the fetch made "last looked" mean "one millisecond ago".

## The sequence this skill uses

```bash
EXPECTED_REMOTE_SHA=$(scripts/capture-lease.sh "$PUSH_REMOTE" "$HEAD_REF")   # before the rebase
git rebase "$BASE_SHA"
# ... resolve conflicts, run the gate ...
scripts/safe-force-push.sh "$PUSH_REMOTE" "$HEAD_REF" "$EXPECTED_REMOTE_SHA"
```

The anchor is captured **once**, before any rewriting, and never recomputed. `safe-force-push.sh`
still fetches — but only to *compare*: if the remote head has moved off the anchor, it exits 4 and
stands down instead of pushing. The anchor is then passed to git explicitly
(`--force-with-lease=<branch>:<sha>`), so even in the race window between the comparison and the
push, the server-side check rejects the update. Both layers are load-bearing: the comparison gives a
readable stand-down with the other writer's commits listed, the explicit lease closes the window the
comparison cannot.

## Stand down means stand down

On exit 4 the correct response is to report, not to retry. Re-running with a refreshed anchor is
exactly the defeated sequence above, written by hand. Reconciling a concurrent writer's commits with
a rebased branch is a human decision: their work may need to be replayed on top, or the rebase may
need to be redone from their tip.

## `capture-lease.sh`'s three verdicts

| Local vs. remote | Exit | Why |
|------------------|------|-----|
| Equal | 0 | The normal case; the anchor is the shared tip. |
| Local strictly ahead | 3 | Unpushed local commits. Safe to rebase, but the force-push publishes them too, so it is called out in the PR comment. |
| Local ahead, but not tracking the PR branch | 5 | A follow-up branch cut from the PR tip descends from the PR head, so an ancestry test alone calls it "ahead". Pushing it would publish commits the PR never contained, and the lease would not object — the remote has not moved. Identity comes from the tracked upstream, not from ancestry. |
| Local behind, or diverged | 4 | Someone else already pushed before the rebase even began. Rebasing now and force-pushing would drop their commits. |

The "behind" case is deliberately not auto-resolved with a fast-forward: from the outside it is
indistinguishable from a colleague pushing a fix to the PR, and silently rewriting on top of it is
the same clobber, one step earlier.

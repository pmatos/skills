# Manual browser checklist

Run before a release or after changing anything under `scripts/review_offline/page/`.
Start a review on a real branch with `/review-offline`, open the link, then check:

1. The page loads with no console errors, and the title row shows the target, SHAs and
   `<host> · <effort>`.
2. The visualization shows lanes, nodes with delta chips, edges, and the flow selector.
   **before** ghosts added elements, **after** ghosts removed ones, and neither reflows.
3. Play and step through a flow: the current edge or node highlights, a dot travels the
   edge, and the caption under the canvas updates. With reduced motion enabled in the OS
   the dot and pulsing stop but highlighting remains.
4. Clicking a node shows its summary and files. A file in the diff jumps to it; one
   outside the change is marked "outside this change".
5. The diff view: click a line number, shift-click another to extend, and the bar shows
   the exact range and side. Comment adds an inline card and a gutter dot; Ask agent
   opens a thread whose answer arrives without a reload.
6. Agent suggestions stream in with the pass chips changing from running to done. Accept,
   Reject, Restore and Edit behave; a rejected comment never reaches the markdown.
7. Unified and split layouts both render; an all-added file leaves the left side empty.
8. Dark mode and a 400px-wide viewport: no horizontal page scroll, nothing unreadable.
9. Finish review: the confirm sentence counts accepted and pending correctly, the file is
   written under `<repo>/.reviews/`, and the invoking agent reports completion.
10. Kill the server and run again on the same target: comments, threads and the summary
    are restored, finished passes do not rerun, and a moved head is flagged.

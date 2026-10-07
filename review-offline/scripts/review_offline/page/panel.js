/* Review panel: comments, ask threads and the reviewer's summary. */
(function (RO) {
  var P = window.htmPreact;
  var html = P.html, useState = P.useState, useRef = P.useRef, useEffect = P.useEffect;

  var LABELS = ["blocking", "suggestion", "nit", "question"];

  function anchorText(a) {
    if (!a || a.scope === "pr") return "whole change";
    if (a.scope === "file") return a.path;
    return a.path + ":" + (a.start === a.end ? a.start : a.start + "-" + a.end) + " (" + a.side + ")";
  }

  function Composer(props) {
    var bodyS = useState(props.initial ? props.initial.body : ""), body = bodyS[0], setBody = bodyS[1];
    var labelS = useState(props.initial ? props.initial.label : "suggestion"), label = labelS[0], setLabel = labelS[1];
    var sugS = useState(props.initial && props.initial.suggestion ? props.initial.suggestion : ""), sug = sugS[0], setSug = sugS[1];
    var showS = useState(Boolean(sug)), showSug = showS[0], setShowSug = showS[1];
    var ask = props.mode === "ask";
    function submit() {
      if (!body.trim()) return;
      props.onSubmit({ body: body.trim(), label: label, suggestion: showSug && sug.trim() ? sug : null });
    }
    return html`<form class="ro-composer" onSubmit=${function (e) { e.preventDefault(); submit(); }}>
      <div class="ro-composer-anchor muted">${ask ? "Ask the agent about " : "Comment on "}${anchorText(props.anchor)}</div>
      <textarea autofocus rows="3" value=${body} placeholder=${ask ? "What do you want to know?" : "Write a comment"}
        onInput=${function (e) { setBody(e.target.value); }}
        onKeyDown=${function (e) { if ((e.ctrlKey || e.metaKey) && e.key === "Enter") submit(); if (e.key === "Escape") props.onCancel(); }} />
      ${!ask && showSug && html`<textarea rows="3" class="mono" value=${sug} placeholder="Replacement text" onInput=${function (e) { setSug(e.target.value); }} />`}
      <div class="ro-composer-row">
        ${!ask && html`<select value=${label} onChange=${function (e) { setLabel(e.target.value); }} aria-label="Label">
          ${LABELS.map(function (l) { return html`<option value=${l}>${l}</option>`; })}
        </select>`}
        ${!ask && props.anchor.scope === "line" && html`<button type="button" class="link" onClick=${function () { setShowSug(!showSug); }}>${showSug ? "remove suggestion" : "add suggestion"}</button>`}
        <span class="grow"></span>
        <button type="button" onClick=${props.onCancel}>Cancel</button>
        <button type="submit" class="primary" disabled=${!body.trim()}>${ask ? "Ask" : props.initial ? "Save" : "Comment"}</button>
      </div>
    </form>`;
  }

  function CommentCard(props) {
    var c = props.comment;
    var editS = useState(false), editing = editS[0], setEditing = editS[1];
    if (editing) {
      return html`<${Composer} anchor=${c.anchor} initial=${c} onCancel=${function () { setEditing(false); }}
        onSubmit=${function (v) { props.onPatch(c.id, v); setEditing(false); }} />`;
    }
    var agent = c.origin === "agent";
    return html`<article class=${"ro-comment st-" + c.status + (c.stale ? " stale" : "")} id=${"comment-" + c.id}>
      <header>
        <span class=${"ro-label lb-" + c.label}>${c.label}</span>
        ${agent && html`<span class="ro-tag">agent${c.sources && c.sources.length ? " · " + c.sources.join(", ") : ""}</span>`}
        ${c.verdict && html`<span class=${"ro-tag v-" + c.verdict.toLowerCase()}>${c.verdict.toLowerCase()}</span>`}
        ${c.stale && html`<span class="ro-tag warn">stale</span>`}
        ${c.status !== "pending" && html`<span class="ro-tag">${c.status}</span>`}
      </header>
      <button class="link ro-where" onClick=${function () { props.onJump(c.anchor); }}>${anchorText(c.anchor)}</button>
      <p class="ro-body">${c.body}</p>
      ${c.suggestion && html`<pre class="ro-code ro-suggestion">${c.suggestion}</pre>`}
      <footer>
        ${c.status === "pending" && html`<button class="primary" onClick=${function () { props.onPatch(c.id, { status: "accepted" }); }}>Accept</button>`}
        ${c.status === "pending" && html`<button onClick=${function () { props.onPatch(c.id, { status: "rejected" }); }}>Reject</button>`}
        ${c.status === "accepted" && agent && html`<button onClick=${function () { props.onPatch(c.id, { status: "rejected" }); }}>Reject</button>`}
        ${c.status === "rejected" && html`<button onClick=${function () { props.onPatch(c.id, { status: "pending" }); }}>Restore</button>`}
        <button onClick=${function () { setEditing(true); }}>Edit</button>
        ${!agent && html`<button onClick=${function () { props.onDelete(c.id); }}>Delete</button>`}
      </footer>
    </article>`;
  }

  function sortKey(c) {
    var a = c.anchor;
    return [a.scope === "pr" ? 1 : 0, a.path || "", a.scope === "file" ? -1 : a.start || 0, a.side === "old" ? 0 : 1];
  }
  function cmp(a, b) {
    var x = sortKey(a), y = sortKey(b);
    for (var i = 0; i < x.length; i++) if (x[i] !== y[i]) return x[i] < y[i] ? -1 : 1;
    return 0;
  }

  function Passes(props) {
    var names = Object.keys(props.passes || {});
    if (!names.length) return null;
    return html`<div class="ro-passes" aria-live="polite">
      ${names.map(function (n) {
        var s = props.passes[n];
        return html`<span class=${"ro-pass " + s}>${s === "running" ? html`<i class="spin"></i>` : null}${n} ${s}</span>`;
      })}
    </div>`;
  }

  function Thread(props) {
    var t = props.thread;
    var replyS = useState(false), replying = replyS[0], setReplying = replyS[1];
    return html`<article class="ro-thread">
      <button class="link ro-where" onClick=${function () { props.onJump(t.anchor); }}>${anchorText(t.anchor)}</button>
      ${t.messages.map(function (m, i) {
        return html`<div class=${"ro-msg " + m.role} key=${i}>
          <strong>${m.role === "user" ? "you" : "agent"}</strong>
          <p class="ro-body">${m.text}</p>
          ${m.role === "agent" && html`<button class="link" onClick=${function () { props.onPromote(t, m); }}>make comment</button>`}
        </div>`;
      })}
      ${t.pending && html`<div class="ro-msg agent"><i class="spin"></i> <span class="muted">thinking…</span></div>`}
      ${replying
        ? html`<${Composer} mode="ask" anchor=${t.anchor} onCancel=${function () { setReplying(false); }}
            onSubmit=${function (v) { props.onReply(t, v.body); setReplying(false); }} />`
        : html`<button onClick=${function () { setReplying(true); }} disabled=${t.pending}>Reply</button>`}
    </article>`;
  }

  function Panel(props) {
    var tabS = useState("comments"), tab = tabS[0], setTab = tabS[1];
    var filterS = useState("open"), filter = filterS[0], setFilter = filterS[1];
    var prS = useState(false), prComposer = prS[0], setPrComposer = prS[1];
    var st = props.state;
    var comments = st.comments.slice().sort(cmp).filter(function (c) {
      if (filter === "open") return c.status !== "rejected";
      if (filter === "pending") return c.status === "pending";
      if (filter === "accepted") return c.status === "accepted";
      return true;
    });
    var pending = st.comments.filter(function (c) { return c.status === "pending"; }).length;
    var accepted = st.comments.filter(function (c) { return c.status === "accepted"; }).length;
    var summaryRef = useRef(null);

    useEffect(function () {
      if (!props.focusComment) return undefined;
      setTab("comments");
      setFilter("all");
      var t = setTimeout(function () {
        var el = document.getElementById("comment-" + props.focusComment.id);
        if (el) {
          el.scrollIntoView({ block: "nearest" });
          el.classList.add("flash");
          setTimeout(function () { el.classList.remove("flash"); }, 1600);
        }
      }, 50);
      return function () { clearTimeout(t); };
    }, [props.focusComment]);

    return html`<aside class="ro-panel" aria-label="Review">
      <${Passes} passes=${st.passes} />
      <div class="ro-tabs" role="tablist">
        <button role="tab" aria-selected=${tab === "comments"} class=${tab === "comments" ? "on" : ""} onClick=${function () { setTab("comments"); }}>Comments <small>${accepted}${pending ? " + " + pending : ""}</small></button>
        <button role="tab" aria-selected=${tab === "ask"} class=${tab === "ask" ? "on" : ""} onClick=${function () { setTab("ask"); }}>Ask <small>${st.threads.length}</small></button>
        <button role="tab" aria-selected=${tab === "summary"} class=${tab === "summary" ? "on" : ""} onClick=${function () { setTab("summary"); }}>Summary</button>
      </div>
      ${tab === "comments" && html`
        <div class="ro-filter">
          ${["open", "pending", "accepted", "all"].map(function (f) {
            return html`<button class=${filter === f ? "on" : ""} onClick=${function () { setFilter(f); }}>${f}</button>`;
          })}
          <span class="grow"></span>
          <button class="link" onClick=${function () { setPrComposer(true); }}>comment on the change</button>
        </div>
        ${prComposer && html`<${Composer} anchor=${{ scope: "pr" }} onCancel=${function () { setPrComposer(false); }}
          onSubmit=${function (v) { props.onCreate({ scope: "pr" }, v); setPrComposer(false); }} />`}
        ${comments.length === 0 && html`<p class="muted pad">${st.comments.length ? "Nothing in this filter." : "No comments yet. Select lines in the diff to add one."}</p>`}
        ${comments.map(function (c) {
          return html`<${CommentCard} key=${c.id} comment=${c} onPatch=${props.onPatch} onDelete=${props.onDelete} onJump=${props.onJump} />`;
        })}`}
      ${tab === "ask" && html`
        ${st.threads.length === 0 && html`<p class="muted pad">Select lines in the diff and choose Ask agent.</p>`}
        ${st.threads.map(function (t) {
          return html`<${Thread} key=${t.id} thread=${t} onJump=${props.onJump} onReply=${props.onReply} onPromote=${props.onPromote} />`;
        })}`}
      ${tab === "summary" && html`
        <label class="ro-summary-edit">Your summary, written to the review file
          <textarea ref=${summaryRef} rows="10" value=${st.summary || ""} onChange=${function (e) { props.onSummary(e.target.value); }} />
        </label>`}
    </aside>`;
  }

  RO.Panel = Panel;
  RO.Composer = Composer;
  RO.CommentCard = CommentCard;
  RO.anchorText = anchorText;
})(window.RO = window.RO || {});

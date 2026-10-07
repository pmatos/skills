/* Root component: bootstrap, API, event loop, selection and composer routing. */
(function (RO) {
  var P = window.htmPreact;
  var html = P.html, render = P.render, useState = P.useState, useEffect = P.useEffect;
  var useMemo = P.useMemo, useRef = P.useRef;

  var token = (location.hash.match(/t=([A-Za-z0-9_-]+)/) || [])[1] || "";
  try { history.replaceState(null, "", location.pathname); } catch (e) { /* ignore */ }

  function api(method, path, body) {
    return fetch(path, {
      method: method,
      headers: { "X-Review-Token": token, "Content-Type": "application/json" },
      body: body === undefined ? undefined : JSON.stringify(body),
    }).then(function (r) {
      return r.text().then(function (t) {
        var data = t ? JSON.parse(t) : {};
        if (!r.ok) throw new Error(data.error || r.status + " " + r.statusText);
        return data;
      });
    });
  }

  function withPending(state, pendingIds) {
    var pend = {};
    (pendingIds || []).forEach(function (id) { pend[id] = true; });
    state.threads.forEach(function (t) { t.pending = Boolean(pend[t.id]); });
    return state;
  }

  function App() {
    var bootS = useState(null), boot = bootS[0], setBoot = bootS[1];
    var stateS = useState(null), state = stateS[0], setState = stateS[1];
    var errS = useState(null), error = errS[0], setError = errS[1];
    var selS = useState(null), sel = selS[0], setSel = selS[1];
    var compS = useState(null), composer = compS[0], setComposer = compS[1];
    var focusS = useState(null), focus = focusS[0], setFocus = focusS[1];
    var pfS = useState(null), panelFocus = pfS[0], setPanelFocus = pfS[1];
    var splitS = useState(false), split = splitS[0], setSplit = splitS[1];
    var activeS = useState(null), active = activeS[0], setActive = activeS[1];
    var finS = useState(null), finish = finS[0], setFinish = finS[1];
    var confS = useState(false), confirming = confS[0], setConfirming = confS[1];
    var seq = useRef(0);

    function refresh() {
      return api("GET", "/api/snapshot").then(function (s) {
        seq.current = s.state.events;
        setState(withPending(s.state, s.pending_threads));
      });
    }

    useEffect(function () {
      api("GET", "/api/bootstrap").then(function (b) {
        seq.current = b.state.events;
        setBoot(b);
        setState(withPending(b.state, b.pending_threads));
      }).catch(function (e) { setError(e.message); });
    }, []);

    useEffect(function () {
      if (!boot) return undefined;
      var stop = false;
      function loop() {
        if (stop) return;
        api("GET", "/api/events?since=" + seq.current).then(function (r) {
          if (stop) return null;
          setError(null);
          if (r.events.length) return refresh().then(function () { seq.current = Math.max(seq.current, r.last); });
          seq.current = r.last;
          return null;
        }).catch(function () {
          if (!stop) setError("Lost connection to the review server. Is it still running?");
          return new Promise(function (res) { setTimeout(res, 2500); });
        }).then(function () { setTimeout(loop, 50); });
      }
      loop();
      return function () { stop = true; };
    }, [boot]);

    var files = boot ? boot.changeset.files : [];
    var fileSet = useMemo(function () {
      var s = {};
      files.forEach(function (f) { s[f.path] = true; });
      return s;
    }, [boot]);

    var live = state ? state.comments.filter(function (c) { return c.status !== "rejected"; }) : [];
    var marks = useMemo(function () {
      var m = {};
      live.forEach(function (c) {
        var a = c.anchor;
        if (a.scope !== "line") return;
        for (var n = a.start; n <= a.end; n++) m[a.path + "|" + a.side + "|" + n] = true;
      });
      return m;
    }, [state]);
    var fileComments = useMemo(function () {
      var m = {};
      live.forEach(function (c) {
        if (c.anchor.scope === "file") (m[c.anchor.path] = m[c.anchor.path] || []).push(c);
      });
      return m;
    }, [state]);
    var counts = useMemo(function () {
      var m = {};
      live.forEach(function (c) { if (c.anchor.path) m[c.anchor.path] = (m[c.anchor.path] || 0) + 1; });
      return m;
    }, [state]);

    if (error && !boot) return html`<main class="ro-fatal"><h1>review-offline</h1><p>${error}</p></main>`;
    if (!boot || !state) return html`<main class="ro-fatal"><p class="muted">Loading review…</p></main>`;
    if (finish) {
      return html`<main class="ro-fatal"><h1>Review complete</h1>
        <p>Written to <code>${finish.path}</code>.</p>
        <p class="muted">You can close this tab. The agent that started the review has been told.</p></main>`;
    }

    function run(p) { return p.then(refresh).catch(function (e) { setError(e.message); }); }

    function onSelect(path, side, n, shift) {
      setComposer(null);
      if (shift && sel && sel.path === path && sel.side === side) {
        setSel({ path: path, side: side, start: Math.min(sel.start, n), end: Math.max(sel.end, n) });
      } else {
        setSel({ path: path, side: side, start: n, end: n });
      }
    }
    function anchorFromSel(s) {
      return { scope: "line", path: s.path, side: s.side, start: s.start, end: s.end };
    }
    function submitComposer(v) {
      var c = composer;
      setComposer(null);
      setSel(null);
      if (c.mode === "ask") {
        run(api("POST", "/api/ask", { anchor: c.anchor, text: v.body }));
      } else {
        run(api("POST", "/api/comments", { anchor: c.anchor, body: v.body, label: v.label, suggestion: v.suggestion }));
      }
    }
    function jump(anchor) {
      if (anchor.scope === "pr") return;
      setActive(anchor.path);
      setFocus({ path: anchor.path, side: anchor.side || "new", line: anchor.start || 0, n: Date.now() });
    }

    function openComment(id) { setPanelFocus({ id: id, n: Date.now() }); }

    function inlineAt(path, lines, selection) {
      var out = [];
      lines.filter(Boolean).forEach(function (l) {
        var side = l.t === "del" ? "old" : "new", n = l.t === "del" ? l.o : l.n;
        live.forEach(function (c) {
          var a = c.anchor;
          if (a.scope === "line" && a.path === path && a.side === side && a.end === n) out.push(html`<${InlineComment} key=${c.id} comment=${c} onOpen=${function () { openComment(c.id); }} />`);
        });
        if (composer && composer.anchor.scope === "line" && composer.anchor.path === path && composer.anchor.side === side && composer.anchor.end === n) {
          out.push(html`<${RO.Composer} key="composer" mode=${composer.mode} anchor=${composer.anchor}
            onCancel=${function () { setComposer(null); }} onSubmit=${submitComposer} />`);
        } else if (!composer && selection && selection.path === path && selection.side === side && selection.end === n) {
          out.push(html`<div class="ro-actions" key="actions">
            <span class="muted">${RO.anchorText(anchorFromSel(selection))}</span>
            <button class="primary" onClick=${function () { setComposer({ mode: "comment", anchor: anchorFromSel(selection) }); }}>Comment</button>
            <button onClick=${function () { setComposer({ mode: "ask", anchor: anchorFromSel(selection) }); }}>Ask agent</button>
            <button class="link" onClick=${function () { setSel(null); }}>clear</button>
          </div>`);
        }
      });
      return out.length ? out : null;
    }

    function onFileComment(path) {
      setComposer({ mode: "comment", anchor: { scope: "file", path: path } });
    }
    var fileComposer = composer && composer.anchor.scope === "file" ? composer : null;

    function pickFile(path) {
      setActive(path);
      var el = document.getElementById("file-" + path);
      if (el) el.scrollIntoView({ block: "start" });
      setFocus({ path: path, side: "new", line: 0, n: Date.now() });
    }

    var accepted = state.comments.filter(function (c) { return c.status === "accepted"; }).length;
    var pending = state.comments.filter(function (c) { return c.status === "pending"; }).length;
    var busy = Object.keys(state.passes || {}).some(function (k) { return state.passes[k] === "running"; });

    return html`<div class="ro-app">
      <header class="ro-top">
        <div class="ro-title">
          <strong>${boot.changeset.title}</strong>
          <span class="muted">${boot.changeset.target} · ${boot.changeset.base.sha.slice(0, 7)} → ${boot.changeset.head.sha.slice(0, 7)}</span>
        </div>
        <div class="ro-top-right">
          ${state.head_moved && html`<span class="ro-tag warn" title="The head moved since this review started">head moved</span>`}
          <span class="ro-tag" title=${(boot.notes || []).join("\n")}>${boot.host} · ${boot.effort}${(boot.notes || []).length ? " *" : ""}</span>
          <button class="primary" onClick=${function () { setConfirming(true); }}>Finish review</button>
        </div>
      </header>
      ${error && html`<div class="ro-banner" role="alert">${error} <button class="link" onClick=${function () { setError(null); }}>dismiss</button></div>`}
      ${!confirming ? null : html`
        <div class="ro-confirm" role="dialog" aria-label="Finish review">
          <p>Write ${accepted} accepted comment${accepted === 1 ? "" : "s"} to the review file${pending ? " (" + pending + " agent suggestion" + (pending === 1 ? "" : "s") + " still pending and will not be included)" : ""}${busy ? ". Agents are still reviewing; stopping now ends them" : ""}?</p>
          <button class="primary" onClick=${function () {
            api("POST", "/api/finish", {}).then(function (r) { setFinish({ path: r.path }); }).catch(function (e) { setError(e.message); setConfirming(false); });
          }}>Write and finish</button>
          <button onClick=${function () { setConfirming(false); }}>Keep reviewing</button>
        </div>`}
      <${RO.Viz} graph=${boot.graph} hasFile=${function (p) { return Boolean(fileSet[p]); }}
        onOpenFile=${function (p, l) { jump({ scope: "line", path: p, side: "new", start: l || 0 }); }} />
      <div class="ro-main">
        <${RO.FileTree} files=${files} counts=${counts} active=${active} onPick=${pickFile} />
        <section class="ro-diff" aria-label="Diff">
          <div class="ro-diff-bar">
            <strong>${files.length} file${files.length === 1 ? "" : "s"}</strong>
            <span class="grow"></span>
            <div class="ro-toggle" role="group" aria-label="Diff layout">
              <button class=${!split ? "on" : ""} onClick=${function () { setSplit(false); }}>unified</button>
              <button class=${split ? "on" : ""} onClick=${function () { setSplit(true); }}>split</button>
            </div>
          </div>
          ${fileComposer && html`<${RO.Composer} anchor=${fileComposer.anchor} onCancel=${function () { setComposer(null); }} onSubmit=${submitComposer} />`}
          ${files.map(function (f) {
            return html`<${RO.FileDiff} key=${f.path} file=${f} split=${split} sel=${sel} marks=${marks} focus=${focus}
              fileComments=${fileComments} onSelect=${onSelect} onFileComment=${onFileComment}
              inlineAt=${inlineAt} renderInline=${function (c) { return html`<${InlineComment} key=${c.id} comment=${c} onOpen=${function () { openComment(c.id); }} />`; }} />`;
          })}
        </section>
        <${RO.Panel} state=${state} onJump=${jump} focusComment=${panelFocus}
          onCreate=${function (anchor, v) { run(api("POST", "/api/comments", { anchor: anchor, body: v.body, label: v.label, suggestion: v.suggestion })); }}
          onPatch=${function (id, fields) { run(api("PATCH", "/api/comments/" + id, fields)); }}
          onDelete=${function (id) { run(api("DELETE", "/api/comments/" + id)); }}
          onReply=${function (t, text) { run(api("POST", "/api/ask", { thread_id: t.id, anchor: t.anchor, text: text })); }}
          onPromote=${function (t, m) { run(api("POST", "/api/comments", { anchor: t.anchor, body: m.text, label: "question", suggestion: null })); }}
          onSummary=${function (text) { run(api("PUT", "/api/summary", { text: text })); }} />
      </div>
    </div>`;
  }

  function InlineComment(props) {
    var c = props.comment;
    return html`<div class=${"ro-inline-card st-" + c.status} onClick=${props.onOpen}>
      <span class=${"ro-label lb-" + c.label}>${c.label}</span>
      ${c.origin === "agent" && html`<span class="ro-tag">agent</span>`}
      <span class="ro-inline-body">${c.body.length > 220 ? c.body.slice(0, 220) + "…" : c.body}</span>
    </div>`;
  }

  render(html`<${App} />`, document.getElementById("root"));
})(window.RO = window.RO || {});

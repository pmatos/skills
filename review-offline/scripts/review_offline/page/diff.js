/* Diff view: lazy per-file hunks, line-range selection, inline comment markers. */
(function (RO) {
  var P = window.htmPreact;
  var html = P.html, useState = P.useState, useEffect = P.useEffect, useRef = P.useRef, useMemo = P.useMemo;

  function lineSide(line) { return line.t === "del" ? "old" : "new"; }
  function lineNo(line) { return line.t === "del" ? line.o : line.n; }

  function toRows(hunk, split) {
    if (!split) return hunk.lines.map(function (l) { return { line: l }; });
    var rows = [], i = 0, ls = hunk.lines;
    while (i < ls.length) {
      if (ls[i].t === "ctx") { rows.push({ left: ls[i], right: ls[i] }); i++; continue; }
      var dels = [], adds = [];
      while (i < ls.length && ls[i].t === "del") dels.push(ls[i++]);
      while (i < ls.length && ls[i].t === "add") adds.push(ls[i++]);
      for (var k = 0; k < Math.max(dels.length, adds.length); k++)
        rows.push({ left: dels[k] || null, right: adds[k] || null });
    }
    return rows;
  }

  function inSel(sel, path, side, n) {
    return sel && sel.path === path && sel.side === side && n >= sel.start && n <= sel.end;
  }

  function Cell(props) {
    var line = props.line, path = props.path, sel = props.sel;
    if (!line) return html`<td class="ro-num"></td><td class="ro-src empty"></td>`;
    var side = lineSide(line), n = lineNo(line);
    var selected = inSel(sel, path, side, n);
    var cls = "ro-src " + line.t + (selected ? " sel" : "");
    var marks = props.marks[path + "|" + side + "|" + n];
    return html`
      <td class=${"ro-num " + line.t + (selected ? " sel" : "")}>
        <button class="ro-numbtn" aria-label=${"Select line " + n + " (" + side + ")"} onClick=${function (e) { props.onSelect(path, side, n, e.shiftKey); }}>
          ${n}${marks && html`<i class="ro-mark" aria-hidden="true"></i>`}
        </button>
      </td>
      <td class=${cls}><span class="ro-sign">${line.t === "add" ? "+" : line.t === "del" ? "-" : " "}</span>${line.text}</td>`;
  }

  function FileDiff(props) {
    var f = props.file, path = f.path;
    var openS = useState(!f.collapsed && !f.binary), open = openS[0], setOpen = openS[1];
    var visS = useState(false), visible = visS[0], setVisible = visS[1];
    var ref = useRef(null);

    useEffect(function () {
      if (props.focus && props.focus.path === path) { setOpen(true); setVisible(true); }
    }, [props.focus]);

    useEffect(function () {
      if (!ref.current || !("IntersectionObserver" in window)) { setVisible(true); return undefined; }
      var io = new IntersectionObserver(function (es) {
        if (es.some(function (e) { return e.isIntersecting; })) { setVisible(true); io.disconnect(); }
      }, { rootMargin: "600px" });
      io.observe(ref.current);
      return function () { io.disconnect(); };
    }, []);

    useEffect(function () {
      if (!props.focus || props.focus.path !== path || !visible || !open) return;
      var el = ref.current && ref.current.querySelector('[data-line="' + (props.focus.side || "new") + ":" + props.focus.line + '"]');
      if (el) el.scrollIntoView({ block: "center" });
      else if (ref.current) ref.current.scrollIntoView({ block: "start" });
    }, [props.focus, visible, open]);

    var sel = props.sel;
    var fileComments = props.fileComments[path] || [];
    var status = f.status + (f.old_path ? " from " + f.old_path : "");

    return html`<article class="ro-file" id=${"file-" + path} ref=${ref}>
      <header class="ro-file-head">
        <button class="ro-fold" aria-expanded=${open} onClick=${function () { setOpen(!open); }}>${open ? "▾" : "▸"}</button>
        <strong class="ro-path">${path}</strong>
        <span class="muted">${status}</span>
        <span class="ro-stat"><span class="add">+${f.additions}</span> <span class="del">−${f.deletions}</span></span>
        ${f.collapsed && html`<span class="ro-tag">${f.collapse_reason}</span>`}
        <button class="link" onClick=${function () { props.onFileComment(path); }}>comment on file</button>
      </header>
      ${fileComments.length > 0 && html`<div class="ro-inline">${fileComments.map(props.renderInline)}</div>`}
      ${open && (f.binary
        ? html`<p class="muted pad">Binary file not shown.</p>`
        : visible
          ? f.hunks.map(function (h, hi) {
              var rows = toRows(h, props.split);
              return html`<table class=${"ro-hunk" + (props.split ? " split" : "")} key=${hi}>
                <colgroup>${props.split
                  ? [html`<col class="ro-col-num" />`, html`<col />`, html`<col class="ro-col-num" />`, html`<col />`]
                  : [html`<col class="ro-col-num" />`, html`<col />`]}</colgroup>
                <tbody>
                  <tr class="ro-hunkhead"><td colspan=${props.split ? 4 : 2}>${h.header}</td></tr>
                  ${rows.map(function (r, ri) {
                    var main = r.line || r.right || r.left;
                    var below = props.inlineAt(path, [r.line, r.left, r.right], sel);
                    return html`
                      <tr key=${ri + "a"} data-line=${lineSide(main) + ":" + lineNo(main)}>
                        ${props.split
                          ? html`<${Cell} line=${r.left} path=${path} sel=${sel} marks=${props.marks} onSelect=${props.onSelect} />
                                 <${Cell} line=${r.right} path=${path} sel=${sel} marks=${props.marks} onSelect=${props.onSelect} />`
                          : html`<${Cell} line=${r.line} path=${path} sel=${sel} marks=${props.marks} onSelect=${props.onSelect} />`}
                      </tr>
                      ${below && html`<tr key=${ri + "b"} class="ro-below"><td colspan=${props.split ? 4 : 2}>${below}</td></tr>`}`;
                  })}
                </tbody>
              </table>`;
            })
          : html`<p class="muted pad">Loading…</p>`)}
    </article>`;
  }

  function FileTree(props) {
    return html`<nav class="ro-tree" aria-label="Files">
      ${props.files.map(function (f) {
        var n = props.counts[f.path] || 0;
        return html`<button class=${"ro-treeitem" + (props.active === f.path ? " on" : "")} title=${f.path} onClick=${function () { props.onPick(f.path); }}>
          <span class=${"ro-dot-" + f.status}></span>
          <span class="ro-treename">${f.path.split("/").pop()}<small>${f.path.includes("/") ? f.path.slice(0, f.path.lastIndexOf("/")) : ""}</small></span>
          ${n > 0 && html`<span class="ro-count">${n}</span>`}
        </button>`;
      })}
    </nav>`;
  }

  RO.FileDiff = FileDiff;
  RO.FileTree = FileTree;
})(window.RO = window.RO || {});

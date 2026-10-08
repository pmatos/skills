/* Architecture / data-flow visualisation: HTML cards over an SVG edge layer. */
(function (RO) {
  var P = window.htmPreact;
  var html = P.html, useState = P.useState, useEffect = P.useEffect, useRef = P.useRef, useMemo = P.useMemo;

  var ICONS = {
    service: "M3 3h10v4H3zM3 9h10v4H3zM5 5h.01M5 11h.01",
    app: "M2 3h12v10H2zM2 6h12",
    module: "M8 2l5 3v6l-5 3-5-3V5zM8 8l5-3M8 8v6M8 8L3 5",
    function: "M6 3c-2 0-2 1-2 3s0 2-2 2c2 0 2 0 2 2s0 3 2 3M10 3c2 0 2 1 2 3s0 2 2 2c-2 0-2 0-2 2s0 3-2 3",
    route: "M3 8h4l3-4h3M7 8l3 4h3M11 2l2 2-2 2M11 10l2 2-2 2",
    job: "M8 2a6 6 0 100 12A6 6 0 008 2zM8 5v3l2 2",
    queue: "M2 4h12M2 8h12M2 12h12M12 2l2 2-2 2",
    datastore: "M3 4c0-1 2-2 5-2s5 1 5 2-2 2-5 2-5-1-5-2zM3 4v8c0 1 2 2 5 2s5-1 5-2V4M3 8c0 1 2 2 5 2s5-1 5-2",
    cache: "M9 2L4 9h4l-1 5 5-7H8z",
    external: "M6 3H3v10h10v-3M9 3h4v4M13 3L7 9",
    ui: "M3 2l9 6-4 1-2 4zM3 2",
    config: "M3 4h6M11 4h2M3 8h2M7 8h6M3 12h8M13 12h0M9 3v2M5 7v2M11 11v2",
    test: "M3 8l3 3 7-7",
    package: "M8 2l5 2.5v7L8 14l-5-2.5v-7zM3 4.5L8 7l5-2.5M8 7v7",
    other: "M8 3a5 5 0 100 10A5 5 0 008 3z",
  };

  var DELTA_LABEL = { added: "added", modified: "modified", removed: "removed", unchanged: "unchanged" };
  var DELTA_CHIP = { added: "+", modified: "~", removed: "−", unchanged: "" };

  function Icon(props) {
    return html`<svg class="ro-icon" viewBox="0 0 16 16" aria-hidden="true"><path d=${ICONS[props.kind] || ICONS.other} /></svg>`;
  }

  function reducedMotion() {
    return window.matchMedia && window.matchMedia("(prefers-reduced-motion: reduce)").matches;
  }

  function ghosted(delta, mode) {
    return (mode === "before" && delta === "added") || (mode === "after" && delta === "removed");
  }

  function Viz(props) {
    var graph = props.graph;
    var edges = graph.edges || [];
    var layout = useMemo(function () { return RO.layout.layoutGraph(graph); }, [graph]);
    var modeS = useState("both"), mode = modeS[0], setMode = modeS[1];
    var flowS = useState(graph.flows && graph.flows.length ? graph.flows[0].id : null);
    var flowId = flowS[0], setFlowId = flowS[1];
    var stepS = useState(0), step = stepS[0], setStep = stepS[1];
    var playS = useState(false), playing = playS[0], setPlaying = playS[1];
    var selS = useState(null), selected = selS[0], setSelected = selS[1];
    var hoverS = useState(null), hoverEdge = hoverS[0], setHoverEdge = hoverS[1];
    var dotRef = useRef(null);
    var pathRefs = useRef({});

    var flow = useMemo(function () {
      return (graph.flows || []).find(function (f) { return f.id === flowId; }) || null;
    }, [graph, flowId]);
    var cur = flow ? flow.steps[Math.min(step, flow.steps.length - 1)] : null;

    var inFlow = useMemo(function () {
      var s = { nodes: {}, edges: {} };
      if (flow) flow.steps.forEach(function (st) {
        if (st.node) s.nodes[st.node] = true;
        if (st.edge) { s.edges[st.edge] = true; }
      });
      if (flow) flow.steps.forEach(function (st) {
        if (st.edge) {
          var e = edges.find(function (x) { return x.id === st.edge; });
          if (e) { s.nodes[e.from] = true; s.nodes[e.to] = true; }
        }
      });
      return s;
    }, [graph, flow]);

    useEffect(function () { setStep(0); setPlaying(false); }, [flowId]);

    useEffect(function () {
      if (!playing || !flow) return undefined;
      var t = setTimeout(function () {
        if (step + 1 >= flow.steps.length) setPlaying(false);
        else setStep(step + 1);
      }, 2600);
      return function () { clearTimeout(t); };
    }, [playing, step, flow]);

    useEffect(function () {
      var dot = dotRef.current;
      if (!dot) return undefined;
      if (!cur || !cur.edge || reducedMotion() || !pathRefs.current[cur.edge]) {
        dot.style.display = "none";
        return undefined;
      }
      var path = pathRefs.current[cur.edge];
      var len = path.getTotalLength(), start = null, raf;
      dot.style.display = "";
      function tick(ts) {
        if (start === null) start = ts;
        var t = Math.min(1, (ts - start) / 1100);
        var pt = path.getPointAtLength(len * t);
        dot.setAttribute("cx", pt.x);
        dot.setAttribute("cy", pt.y);
        if (t < 1) raf = requestAnimationFrame(tick);
      }
      raf = requestAnimationFrame(tick);
      return function () { cancelAnimationFrame(raf); };
    }, [cur, flowId]);

    var showLabels = edges.length <= 15;
    var focusNode = selected && graph.nodes.find(function (n) { return n.id === selected; });

    function nodeClass(n) {
      var c = "ro-node d-" + n.delta;
      if (ghosted(n.delta, mode)) c += " ghost";
      if (flow && !inFlow.nodes[n.id]) c += " dim";
      if (cur && cur.node === n.id) c += " current";
      if (selected === n.id) c += " selected";
      return c;
    }
    function edgeClass(e) {
      var c = "ro-edge d-" + e.delta + " em-" + (e.emphasis || "normal");
      if (e.animated || e.emphasis === "hero") c += " flowing";
      if (ghosted(e.delta, mode)) c += " ghost";
      if (flow && !inFlow.edges[e.id]) c += " dim";
      if (cur && cur.edge === e.id) c += " current";
      return c;
    }

    var panels = graph.panels || [];

    return html`
      <section class="ro-viz" aria-label="What this change does">
        <div class="ro-viz-head">
          <div>
            <h2>${graph.title}</h2>
            <p class="ro-summary">${graph.summary}</p>
          </div>
          <div class="ro-toggle" role="group" aria-label="Before and after">
            ${["before", "both", "after"].map(function (m) {
              return html`<button class=${mode === m ? "on" : ""} aria-pressed=${mode === m} onClick=${function () { setMode(m); }}>${m}</button>`;
            })}
          </div>
        </div>
        ${(graph.flows || []).length > 0 && html`
          <div class="ro-flowbar">
            <label>Flow
              <select value=${flowId || ""} onChange=${function (e) { setFlowId(e.target.value || null); }}>
                <option value="">none</option>
                ${graph.flows.map(function (f) { return html`<option value=${f.id}>${f.title}</option>`; })}
              </select>
            </label>
            ${flow && html`
              <div class="ro-stepper">
                <button disabled=${step === 0} onClick=${function () { setPlaying(false); setStep(step - 1); }} aria-label="Previous step">‹</button>
                <button onClick=${function () { if (!playing && step + 1 >= flow.steps.length) setStep(0); setPlaying(!playing); }}>${playing ? "pause" : "play"}</button>
                <button disabled=${step + 1 >= flow.steps.length} onClick=${function () { setPlaying(false); setStep(step + 1); }} aria-label="Next step">›</button>
                <span class="ro-stepcount">${Math.min(step, flow.steps.length - 1) + 1} / ${flow.steps.length}</span>
              </div>`}
          </div>`}
        <div class="ro-scroll">
          <div class="ro-canvas" style=${{ width: layout.width + "px", height: layout.height + "px" }}>
            ${layout.lanes.map(function (l) {
              return html`<div class="ro-lane" style=${{ left: l.x + "px", width: l.w + "px", height: layout.height + "px" }}>
                <div class="ro-lane-head"><strong>${l.label}</strong>${l.subtitle && html`<span>${l.subtitle}</span>`}</div>
              </div>`;
            })}
            ${layout.groups.map(function (g) {
              return html`<div class="ro-group" style=${{ left: g.x + "px", top: g.y + "px", width: g.w + "px", height: g.h + "px" }}><span>${g.label}</span></div>`;
            })}
            <svg class="ro-edges" width=${layout.width} height=${layout.height} aria-hidden="true">
              <defs>
                ${Object.keys(DELTA_LABEL).map(function (d) {
                  return html`<marker id=${"ro-arrow-" + d} viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" markerHeight="7" orient="auto-start-reverse"><path d="M0 0L10 5L0 10z" class=${"ro-arrow d-" + d} /></marker>`;
                })}
              </defs>
              ${edges.map(function (e) {
                var r = layout.edges[e.id];
                return html`<g class=${edgeClass(e)} onMouseEnter=${function () { setHoverEdge(e.id); }} onMouseLeave=${function () { setHoverEdge(null); }}>
                  <path d=${r.d} class="ro-hit" />
                  <path d=${r.d} class="ro-line" marker-end=${"url(#ro-arrow-" + e.delta + ")"} ref=${function (el) { if (el) pathRefs.current[e.id] = el; }} />
                </g>`;
              })}
              <circle ref=${dotRef} r="5" class="ro-dot" style="display:none" />
            </svg>
            ${edges.map(function (e) {
              var r = layout.edges[e.id];
              if (!e.label || !(showLabels || hoverEdge === e.id || (cur && cur.edge === e.id))) return null;
              return html`<div class=${"ro-edgelabel d-" + e.delta + (ghosted(e.delta, mode) ? " ghost" : "")} style=${{ left: r.label.x + "px", top: r.label.y + "px" }}>${e.label}</div>`;
            })}
            ${graph.nodes.map(function (n) {
              var p = layout.nodes[n.id];
              return html`<button class=${nodeClass(n)} style=${{ left: p.x + "px", top: p.y + "px", width: p.w + "px", height: p.h + "px" }}
                  onClick=${function () { setSelected(selected === n.id ? null : n.id); }} aria-label=${n.label + ", " + DELTA_LABEL[n.delta]}>
                <${Icon} kind=${n.kind} />
                <span class="ro-node-text">
                  <span class="ro-node-label">${n.label}</span>
                  ${n.subtitle && html`<span class="ro-node-sub">${n.subtitle}</span>`}
                </span>
                ${DELTA_CHIP[n.delta] && html`<span class=${"ro-chip d-" + n.delta} aria-hidden="true">${DELTA_CHIP[n.delta]}</span>`}
              </button>`;
            })}
          </div>
        </div>
        <div class="ro-caption" aria-live="polite">
          ${cur
            ? html`<p><strong>${flow.title} · step ${Math.min(step, flow.steps.length - 1) + 1}</strong> ${cur.caption}</p>`
            : html`<p class="muted">Pick a flow to step through it, or select a node.</p>`}
          ${focusNode && html`
            <div class="ro-nodeinfo">
              <p><strong>${focusNode.label}</strong> <span class=${"ro-tag d-" + focusNode.delta}>${focusNode.delta}</span> ${focusNode.summary}</p>
              ${(focusNode.files || []).length > 0
                ? html`<ul>${focusNode.files.map(function (f) {
                    var inDiff = props.hasFile(f.path);
                    return html`<li><button class="link" disabled=${!inDiff} onClick=${function () { props.onOpenFile(f.path, f.start); }}>${f.path}${f.start ? ":" + f.start : ""}</button>${!inDiff && html` <span class="muted">outside this change</span>`}</li>`;
                  })}</ul>`
                : html`<p class="muted">No files: outside this change.</p>`}
            </div>`}
        </div>
        ${panels.length > 0 && html`<${Panels} panels=${panels} />`}
      </section>`;
  }

  function Panels(props) {
    var s = useState(props.panels[0].id), tab = s[0], setTab = s[1];
    var panel = props.panels.find(function (p) { return p.id === tab; }) || props.panels[0];
    var lines = panel.text.split("\n");
    return html`<div class="ro-panels">
      <div class="ro-tabs" role="tablist">
        ${props.panels.map(function (p) {
          return html`<button role="tab" aria-selected=${p.id === panel.id} class=${p.id === panel.id ? "on" : ""} onClick=${function () { setTab(p.id); }}>${p.title}</button>`;
        })}
      </div>
      <pre class="ro-code">${lines.map(function (l) {
        var cls = panel.diff ? (l[0] === "+" ? "add" : l[0] === "-" ? "del" : "") : "";
        return html`<span class=${"ro-pl " + cls}>${l || " "}\n</span>`;
      })}</pre>
    </div>`;
  }

  RO.Viz = Viz;
})(window.RO = window.RO || {});

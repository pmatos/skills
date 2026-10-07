/* Pure, deterministic graph layout. Lays out the union graph once so view toggles never reflow. */
(function (root) {
  var C = {
    laneW: 340, cardW: 232, cardH: 64, gapY: 26, pad: 24, header: 56,
    groupPad: 10, groupHead: 20, sweeps: 3, channelGap: 14,
  };

  function layoutGraph(graph) {
    var lanes = graph.lanes
      .map(function (l, i) { return { lane: l, i: i }; })
      .sort(function (a, b) { return a.lane.order - b.lane.order || a.i - b.i; })
      .map(function (e) { return e.lane; });
    var laneIdx = {};
    lanes.forEach(function (l, i) { laneIdx[l.id] = i; });

    var nodeIdx = {};
    graph.nodes.forEach(function (n, i) { nodeIdx[n.id] = i; });

    var neighbours = {};
    graph.nodes.forEach(function (n) { neighbours[n.id] = []; });
    (graph.edges || []).forEach(function (e) {
      neighbours[e.from].push(e.to);
      neighbours[e.to].push(e.from);
    });

    var units = lanes.map(function () { return []; });
    var groupUnit = {};
    graph.nodes.forEach(function (n) {
      var li = laneIdx[n.lane];
      if (n.group) {
        var key = li + "/" + n.group;
        if (!groupUnit[key]) {
          groupUnit[key] = { group: n.group, lane: li, nodes: [], idx: nodeIdx[n.id] };
          units[li].push(groupUnit[key]);
        }
        groupUnit[key].nodes.push(n);
      } else {
        units[li].push({ group: null, lane: li, nodes: [n], idx: nodeIdx[n.id] });
      }
    });

    var order = {};
    function place() {
      units.forEach(function (list) {
        var k = 0;
        list.forEach(function (u) { u.nodes.forEach(function (n) { order[n.id] = k++; }); });
      });
    }
    place();

    for (var s = 0; s < C.sweeps; s++) {
      var seq = s % 2 === 0 ? lanes.map(function (_, i) { return i; })
        : lanes.map(function (_, i) { return lanes.length - 1 - i; });
      seq.forEach(function (li) {
        units[li].forEach(function (u) {
          var ys = [];
          u.nodes.forEach(function (n) {
            neighbours[n.id].forEach(function (o) {
              if (laneIdx[nodeById(o).lane] !== li) ys.push(order[o]);
            });
          });
          u.bary = ys.length ? median(ys) : null;
        });
        var anchored = units[li].filter(function (u) { return u.bary !== null; });
        anchored.sort(function (a, b) { return a.bary - b.bary || a.idx - b.idx; });
        var merged = [], ai = 0;
        units[li].forEach(function (u) { merged.push(u.bary === null ? u : anchored[ai++]); });
        units[li] = merged;
        place();
      });
    }

    function nodeById(id) { return graph.nodes[nodeIdx[id]]; }

    var pos = {}, groups = [], laneBottom = [];
    lanes.forEach(function (lane, li) {
      var x = C.pad + li * C.laneW + (C.laneW - C.cardW) / 2;
      var y = C.header;
      units[li].forEach(function (u) {
        if (u.group) {
          var gy = y;
          y += C.groupHead + C.groupPad;
          u.nodes.forEach(function (n) {
            pos[n.id] = { x: x, y: y, w: C.cardW, h: C.cardH };
            y += C.cardH + C.gapY;
          });
          y += C.groupPad - C.gapY;
          groups.push({
            id: lane.id + "/" + u.group, label: u.group,
            x: x - C.groupPad, y: gy, w: C.cardW + 2 * C.groupPad, h: y - gy,
          });
          y += C.gapY;
        } else {
          pos[u.nodes[0].id] = { x: x, y: y, w: C.cardW, h: C.cardH };
          y += C.cardH + C.gapY;
        }
      });
      laneBottom[li] = y;
    });

    var stackBottom = Math.max.apply(null, laneBottom.concat([C.header + C.cardH]));
    var ports = portOffsets(graph, pos, laneIdx);
    var channel = 0;
    var sameLaneCount = {};
    var edges = {};
    (graph.edges || []).forEach(function (e) {
      var a = pos[e.from], b = pos[e.to];
      var la = laneIdx[nodeById(e.from).lane], lb = laneIdx[nodeById(e.to).lane];
      var out = ports[e.id];
      edges[e.id] = route(e, a, b, la, lb, out);
    });

    function route(e, a, b, la, lb, out) {
      if (la === lb) {
        var n = (sameLaneCount[la] = (sameLaneCount[la] || 0) + 1);
        var x = a.x + a.w, y1 = a.y + out.fromY, y2 = b.y + out.toY;
        var k = Math.min(70, 26 + Math.abs(y2 - y1) * 0.22) + (n - 1) * 8;
        return {
          d: "M" + x + " " + y1 + " C" + (x + k) + " " + y1 + " " + (x + k) + " " + y2 + " " + x + " " + y2,
          label: { x: x + k * 0.75, y: (y1 + y2) / 2 },
        };
      }
      if (Math.abs(lb - la) === 1) {
        var fw = lb > la;
        var x1 = fw ? a.x + a.w : a.x, x2 = fw ? b.x : b.x + b.w, ya = a.y + out.fromY, yb = b.y + out.toY;
        var dx = Math.max(40, Math.abs(x2 - x1) / 2) * (fw ? 1 : -1);
        return {
          d: "M" + x1 + " " + ya + " C" + (x1 + dx) + " " + ya + " " + (x2 - dx) + " " + yb + " " + x2 + " " + yb,
          label: { x: (x1 + x2) / 2, y: (ya + yb) / 2 },
        };
      }
      var forward = lb > la;
      var sx = forward ? a.x + a.w : a.x, tx = forward ? b.x : b.x + b.w;
      var sy = a.y + out.fromY, ty = b.y + out.toY;
      var ch = stackBottom + 18 + channel++ * C.channelGap;
      var stub = forward ? 18 : -18;
      var pts = [[sx, sy], [sx + stub, sy], [sx + stub, ch], [tx - stub, ch], [tx - stub, ty], [tx, ty]];
      return { d: rounded(pts, 10), label: { x: (sx + tx) / 2, y: ch } };
    }

    var bottom = stackBottom + 18 + (channel ? channel * C.channelGap + 6 : 0);
    return {
      width: C.pad * 2 + lanes.length * C.laneW,
      height: bottom + C.pad,
      lanes: lanes.map(function (l, i) {
        return { id: l.id, label: l.label, subtitle: l.subtitle || "", x: C.pad + i * C.laneW, w: C.laneW };
      }),
      nodes: pos,
      groups: groups,
      edges: edges,
    };
  }

  function portOffsets(graph, pos, laneIdx) {
    var side = {};
    var nodeLane = {};
    graph.nodes.forEach(function (n) { nodeLane[n.id] = laneIdx[n.lane]; });
    (graph.edges || []).forEach(function (e) {
      var la = nodeLane[e.from], lb = nodeLane[e.to];
      var fromSide = lb >= la ? "r" : "l";
      var toSide = lb > la ? "l" : "r";
      push(e.from + ":" + fromSide, { e: e, end: "from", other: pos[e.to].y });
      push(e.to + ":" + toSide, { e: e, end: "to", other: pos[e.from].y });
    });
    function push(key, v) { (side[key] = side[key] || []).push(v); }
    var out = {};
    Object.keys(side).forEach(function (key) {
      var list = side[key].sort(function (p, q) { return p.other - q.other; });
      var h = C.cardH, inset = 12, span = h - 2 * inset;
      list.forEach(function (item, i) {
        var y = list.length === 1 ? h / 2 : inset + (span * i) / (list.length - 1);
        var o = (out[item.e.id] = out[item.e.id] || {});
        o[item.end === "from" ? "fromY" : "toY"] = y;
      });
    });
    return out;
  }

  function rounded(pts, r) {
    var d = "M" + pts[0][0] + " " + pts[0][1];
    for (var i = 1; i < pts.length - 1; i++) {
      var p0 = pts[i - 1], p1 = pts[i], p2 = pts[i + 1];
      var r1 = Math.min(r, dist(p0, p1) / 2), r2 = Math.min(r, dist(p1, p2) / 2);
      var a = toward(p1, p0, r1), b = toward(p1, p2, r2);
      d += " L" + a[0] + " " + a[1] + " Q" + p1[0] + " " + p1[1] + " " + b[0] + " " + b[1];
    }
    var last = pts[pts.length - 1];
    return d + " L" + last[0] + " " + last[1];
  }
  function dist(a, b) { return Math.hypot(b[0] - a[0], b[1] - a[1]); }
  function toward(from, to, len) {
    var d = dist(from, to) || 1;
    return [from[0] + ((to[0] - from[0]) * len) / d, from[1] + ((to[1] - from[1]) * len) / d];
  }
  function median(xs) {
    var s = xs.slice().sort(function (a, b) { return a - b; });
    var m = s.length >> 1;
    return s.length % 2 ? s[m] : (s[m - 1] + s[m]) / 2;
  }

  var api = { layoutGraph: layoutGraph, constants: C };
  if (typeof module !== "undefined" && module.exports) module.exports = api;
  else { root.RO = root.RO || {}; root.RO.layout = api; }
})(typeof window !== "undefined" ? window : globalThis);

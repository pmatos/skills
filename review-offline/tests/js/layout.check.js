const fs = require("fs");
const path = require("path");
const { layoutGraph } = require("../../scripts/review_offline/page/layout.js");
const dir = path.join(__dirname, "..", "fixtures", "graphs");
const problems = [];
for (const f of fs.readdirSync(dir).filter((n) => n.endsWith(".json"))) {
  const g = JSON.parse(fs.readFileSync(path.join(dir, f), "utf8"));
  const a = layoutGraph(g);
  const b = layoutGraph(JSON.parse(JSON.stringify(g)));
  if (JSON.stringify(a) !== JSON.stringify(b)) problems.push(f + ": not deterministic");
  const ids = Object.keys(a.nodes);
  if (ids.length !== g.nodes.length) problems.push(f + ": node count");
  for (const id of ids) {
    const n = a.nodes[id];
    for (const v of [n.x, n.y, n.w, n.h]) if (!Number.isFinite(v)) problems.push(f + ": NaN " + id);
    if (n.x < 0 || n.y < 0 || n.x + n.w > a.width || n.y + n.h > a.height) problems.push(f + ": out of bounds " + id);
  }
  for (let i = 0; i < ids.length; i++)
    for (let j = i + 1; j < ids.length; j++) {
      const p = a.nodes[ids[i]], q = a.nodes[ids[j]];
      if (p.x < q.x + q.w && q.x < p.x + p.w && p.y < q.y + q.h && q.y < p.y + p.h)
        problems.push(f + ": overlap " + ids[i] + " " + ids[j]);
    }
  for (const e of g.edges || []) {
    const r = a.edges[e.id];
    if (!r || /NaN|undefined|Infinity/.test(r.d)) problems.push(f + ": bad path " + e.id);
    else if (!Number.isFinite(r.label.x) || !Number.isFinite(r.label.y)) problems.push(f + ": bad label " + e.id);
  }
}
if (problems.length) { console.error(problems.join("\n")); process.exit(1); }
console.log("ok");

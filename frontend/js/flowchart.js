/**
 * codevis/flowchart.js
 * ---------------------
 * A from-scratch Sugiyama-style layered graph layout + interactive SVG
 * renderer, built specifically for flowcharts (small-to-medium DAGs with
 * feedback/back edges from loops).
 *
 * WHY HAND-BUILT INSTEAD OF A LIBRARY: this project is designed to run with
 * zero build step (no npm/webpack/vite), so any layout library has to be
 * loadable straight from a CDN as a browser script. That rules out most of
 * the React-ecosystem options (React Flow needs a bundler + React tree).
 * A layered layout for flowcharts is a well-understood, boundedly-scoped
 * algorithm, so implementing it directly keeps the dependency surface to
 * exactly one external script (Monaco) -- see docs/TECHNICAL_DOCS.md,
 * "Why not React Flow / dagre".
 *
 * Pipeline: classify back-edges -> rank nodes (longest path) -> insert
 * dummy nodes for edges spanning >1 rank -> order nodes within each rank
 * (median heuristic, several sweeps to reduce crossings) -> assign x/y ->
 * render SVG shapes per node type -> render edges as smooth paths ->
 * pan/zoom via a transformed <g> -> click-to-highlight wired to the editor.
 */

const NODE_W = 190;
const NODE_H = 46;
const RANK_GAP = 90;
const COL_GAP = 40;
const DECISION_EXTRA = 20;

const NODE_COLORS = {
  START: "#3fb950",
  END: "#f85149",
  PROCESS: "#4f8cff",
  DECISION: "#d29922",
  LOOP: "#bc8cff",
  INPUT: "#39c5cf",
  OUTPUT: "#39c5cf",
  FUNCTION: "#768390",
  RETURN: "#f778ba",
  BREAK: "#f85149",
  CONTINUE: "#d29922",
};

export function computeAndRender(container, graph, { onNodeClick } = {}) {
  const { nodes, edges, warnings } = graph;
  if (!nodes || nodes.length === 0) {
    return { svgEl: null, layout: null };
  }

  const layout = layoutGraph(nodes, edges);
  const svgEl = renderSvg(container, layout, onNodeClick);
  return { svgEl, layout, warnings };
}

// --------------------------------------------------------------------- //
// 1. Rank assignment (longest path), with back-edge detection via DFS
// --------------------------------------------------------------------- //

function layoutGraph(nodes, edges) {
  const byId = new Map(nodes.map((n) => [n.id, n]));
  const outAdj = new Map(nodes.map((n) => [n.id, []]));
  edges.forEach((e) => outAdj.get(e.source)?.push(e));

  const rootId = nodes.find((n) => n.type === "START")?.id || nodes[0].id;

  // DFS classify: back edges point to a node currently on the recursion stack.
  const state = new Map(); // 0 = unvisited, 1 = active, 2 = done
  const backEdgeIds = new Set();
  (function dfs(id, stack) {
    state.set(id, 1);
    for (const e of outAdj.get(id) || []) {
      const s = state.get(e.target) || 0;
      if (s === 1) {
        backEdgeIds.add(e.id); // edge to an active ancestor -> back edge
      } else if (s === 0) {
        dfs(e.target, stack);
      }
    }
    state.set(id, 2);
  })(rootId, []);

  const forwardEdges = edges.filter((e) => !backEdgeIds.has(e.id));

  // Longest-path ranking over the (now acyclic) forward-edge graph.
  const rank = new Map(nodes.map((n) => [n.id, 0]));
  const forwardOutAdj = new Map(nodes.map((n) => [n.id, []]));
  const indegree = new Map(nodes.map((n) => [n.id, 0]));
  forwardEdges.forEach((e) => {
    forwardOutAdj.get(e.source)?.push(e.target);
    indegree.set(e.target, (indegree.get(e.target) || 0) + 1);
  });

  const queue = nodes.filter((n) => indegree.get(n.id) === 0).map((n) => n.id);
  const processed = new Set();
  while (queue.length) {
    const id = queue.shift();
    if (processed.has(id)) continue;
    processed.add(id);
    for (const targetId of forwardOutAdj.get(id) || []) {
      rank.set(targetId, Math.max(rank.get(targetId), rank.get(id) + 1));
      indegree.set(targetId, indegree.get(targetId) - 1);
      if (indegree.get(targetId) === 0) queue.push(targetId);
    }
  }
  // Any node BFS/topo missed (disconnected / part of a pure cycle) gets rank 0.

  // --------------------------------------------------------------------- //
  // 2. Insert dummy nodes for edges spanning more than one rank
  // --------------------------------------------------------------------- //
  const layoutNodes = nodes.map((n) => ({
    id: n.id, real: n, rank: rank.get(n.id) || 0, dummy: false,
  }));
  const layoutNodesById = new Map(layoutNodes.map((n) => [n.id, n]));
  const renderEdges = []; // { id, points: [nodeId...], back }

  let dummyCounter = 0;
  for (const e of edges) {
    const isBack = backEdgeIds.has(e.id);
    const r1 = layoutNodesById.get(e.source).rank;
    const r2 = layoutNodesById.get(e.target).rank;
    if (isBack || Math.abs(r2 - r1) <= 1) {
      renderEdges.push({ id: e.id, chain: [e.source, e.target], label: e.label, back: isBack });
      continue;
    }
    // Forward edge spanning multiple ranks: insert a dummy at each rank between.
    const chain = [e.source];
    const step = r2 > r1 ? 1 : -1;
    for (let r = r1 + step; r !== r2; r += step) {
      const dummyId = `__dummy_${dummyCounter++}`;
      layoutNodes.push({ id: dummyId, real: null, rank: r, dummy: true });
      layoutNodesById.set(dummyId, layoutNodes[layoutNodes.length - 1]);
      chain.push(dummyId);
    }
    chain.push(e.target);
    renderEdges.push({ id: e.id, chain, label: e.label, back: false });
  }

  // --------------------------------------------------------------------- //
  // 3. Group by rank, order within rank via barycenter heuristic
  // --------------------------------------------------------------------- //
  const maxRank = Math.max(0, ...layoutNodes.map((n) => n.rank));
  const ranks = Array.from({ length: maxRank + 1 }, () => []);
  layoutNodes.forEach((n) => ranks[n.rank].push(n));

  // initial order: stable, by first appearance
  ranks.forEach((arr) => arr.sort((a, b) => (a.dummy === b.dummy ? 0 : a.dummy ? 1 : -1)));

  const neighborsOf = (nodeId, direction) => {
    const result = [];
    for (const re of renderEdges) {
      for (let i = 0; i < re.chain.length - 1; i++) {
        const a = re.chain[i], b = re.chain[i + 1];
        if (direction === "up" && b === nodeId) result.push(a);
        if (direction === "down" && a === nodeId) result.push(b);
      }
    }
    return result;
  };

  const order = new Map(); // nodeId -> position within its rank
  ranks.forEach((arr) => arr.forEach((n, i) => order.set(n.id, i)));

  function sweep(direction) {
    const rankIndices = direction === "down"
      ? [...Array(ranks.length).keys()]
      : [...Array(ranks.length).keys()].reverse();
    for (const ri of rankIndices) {
      const arr = ranks[ri];
      const scored = arr.map((n) => {
        const neigh = neighborsOf(n.id, direction === "down" ? "up" : "down");
        const positions = neigh.map((id) => order.get(id)).filter((p) => p !== undefined);
        const score = positions.length ? positions.reduce((a, b) => a + b, 0) / positions.length : order.get(n.id);
        return { n, score };
      });
      scored.sort((a, b) => a.score - b.score);
      scored.forEach((s, i) => order.set(s.n.id, i));
      ranks[ri] = scored.map((s) => s.n);
    }
  }
  for (let i = 0; i < 4; i++) { sweep("down"); sweep("up"); }

  // --------------------------------------------------------------------- //
  // 4. Assign coordinates
  // --------------------------------------------------------------------- //
  const colWidth = NODE_W + COL_GAP;
  let maxCols = Math.max(1, ...ranks.map((r) => r.length));
  const totalWidth = maxCols * colWidth;

  ranks.forEach((arr, ri) => {
    const rowWidth = arr.length * colWidth;
    const offsetX = (totalWidth - rowWidth) / 2;
    arr.forEach((n, i) => {
      n.x = offsetX + i * colWidth + colWidth / 2;
      n.y = ri * (NODE_H + RANK_GAP) + NODE_H / 2 + 30;
    });
  });

  return {
    nodesById: byId,
    layoutNodesById,
    ranks,
    renderEdges,
    width: totalWidth + 40,
    height: (maxRank + 1) * (NODE_H + RANK_GAP) + 60,
  };
}

// --------------------------------------------------------------------- //
// 5. SVG rendering
// --------------------------------------------------------------------- //

const SVG_NS = "http://www.w3.org/2000/svg";

function el(tag, attrs = {}, children = []) {
  const node = document.createElementNS(SVG_NS, tag);
  for (const [k, v] of Object.entries(attrs)) node.setAttribute(k, v);
  children.forEach((c) => node.appendChild(c));
  return node;
}

function renderSvg(container, layout, onNodeClick) {
  container.innerHTML = "";
  const svg = el("svg", {
    width: "100%",
    height: "100%",
    viewBox: `0 0 ${layout.width} ${layout.height}`,
  });

  const defs = el("defs", {}, [
    arrowMarker("arrow", "#4b5563"),
    arrowMarker("arrow-highlight", "#6ea2ff"),
  ]);
  svg.appendChild(defs);

  const world = el("g", { class: "fc-world" });
  svg.appendChild(world);

  const edgeLayer = el("g", { class: "fc-edges" });
  const nodeLayer = el("g", { class: "fc-nodes" });
  world.appendChild(edgeLayer);
  world.appendChild(nodeLayer);

  // ---- edges ----
  for (const re of layout.renderEdges) {
    const points = re.chain.map((id) => layout.layoutNodesById.get(id));
    const d = buildPath(points, re.back);
    const g = el("g", { class: "fc-edge", "data-edge-id": re.id });
    g.appendChild(el("path", { d, "marker-end": "url(#arrow)" }));
    if (re.label) {
      const mid = points[Math.floor((points.length - 1) / 2)];
      const nxt = points[Math.floor((points.length - 1) / 2) + 1] || mid;
      const lx = (mid.x + nxt.x) / 2 + (re.back ? 34 : 10);
      const ly = (mid.y + nxt.y) / 2;
      const t = el("text", { x: lx, y: ly, "text-anchor": "middle" });
      t.textContent = re.label;
      g.appendChild(t);
    }
    edgeLayer.appendChild(g);
  }

  // ---- nodes ----
  for (const n of layout.layoutNodesById.values()) {
    if (n.dummy) continue;
    const real = n.real;
    const g = el("g", {
      class: "fc-node",
      "data-node-id": real.id,
      transform: `translate(${n.x}, ${n.y})`,
    });
    g.appendChild(nodeShape(real.type));
    const label = el("text", { x: 0, y: 5, "text-anchor": "middle" });
    label.textContent = truncateForDisplay(real.label);
    g.appendChild(label);
    const title = el("title");
    title.textContent = real.label;
    g.appendChild(title);

    g.addEventListener("click", (ev) => {
      ev.stopPropagation();
      onNodeClick?.(real);
    });
    nodeLayer.appendChild(g);
  }

  container.appendChild(svg);
  attachPanZoom(container, svg, world);
  return svg;
}

function truncateForDisplay(text, max = 26) {
  return text.length > max ? text.slice(0, max - 1) + "\u2026" : text;
}

function arrowMarker(id, color) {
  return el("marker", {
    id, viewBox: "0 0 10 10", refX: "9", refY: "5",
    markerWidth: "7", markerHeight: "7", orient: "auto-start-reverse",
  }, [el("path", { d: "M0,0 L10,5 L0,10 z", fill: color })]);
}

function nodeShape(type) {
  const color = NODE_COLORS[type] || "#4f8cff";
  const w = NODE_W, h = NODE_H;
  switch (type) {
    case "START":
    case "END":
      return el("rect", { x: -w / 2, y: -h / 2, width: w, height: h, rx: h / 2, fill: color, stroke: shade(color, -20) });
    case "DECISION":
    case "LOOP": {
      const hw = w / 2 + DECISION_EXTRA, hh = h / 2 + DECISION_EXTRA * 0.6;
      return el("polygon", {
        points: `0,${-hh} ${hw},0 0,${hh} ${-hw},0`,
        fill: color, stroke: shade(color, -20),
      });
    }
    case "INPUT":
    case "OUTPUT": {
      const skew = 16;
      return el("polygon", {
        points: `${-w / 2 + skew},${-h / 2} ${w / 2},${-h / 2} ${w / 2 - skew},${h / 2} ${-w / 2},${h / 2}`,
        fill: color, stroke: shade(color, -20),
      });
    }
    case "RETURN": {
      const notch = 14;
      return el("polygon", {
        points: `${-w / 2},${-h / 2} ${w / 2 - notch},${-h / 2} ${w / 2},0 ${w / 2 - notch},${h / 2} ${-w / 2},${h / 2}`,
        fill: color, stroke: shade(color, -20),
      });
    }
    case "BREAK":
    case "CONTINUE":
      return el("rect", {
        x: -w / 2.6, y: -h / 2.4, width: w / 1.3, height: h / 1.2, rx: 8,
        fill: color, stroke: shade(color, -20), "stroke-dasharray": "4 3",
      });
    case "FUNCTION": {
      const g = el("g");
      g.appendChild(el("rect", { x: -w / 2, y: -h / 2, width: w, height: h, fill: color, stroke: shade(color, -20) }));
      g.appendChild(el("line", { x1: -w / 2 + 10, x2: -w / 2 + 10, y1: -h / 2, y2: h / 2, stroke: shade(color, -20) }));
      g.appendChild(el("line", { x1: w / 2 - 10, x2: w / 2 - 10, y1: -h / 2, y2: h / 2, stroke: shade(color, -20) }));
      return g;
    }
    default:
      return el("rect", { x: -w / 2, y: -h / 2, width: w, height: h, rx: 6, fill: color, stroke: shade(color, -20) });
  }
}

function shade(hex, percent) {
  const num = parseInt(hex.slice(1), 16);
  const amt = Math.round(2.55 * percent);
  const r = Math.max(0, Math.min(255, (num >> 16) + amt));
  const g = Math.max(0, Math.min(255, ((num >> 8) & 0xff) + amt));
  const b = Math.max(0, Math.min(255, (num & 0xff) + amt));
  return `rgb(${r},${g},${b})`;
}

function buildPath(points, isBack) {
  if (!isBack) {
    if (points.length === 2) {
      const [a, b] = points;
      const midY = (a.y + b.y) / 2;
      return `M ${a.x} ${a.y + NODE_H / 2} C ${a.x} ${midY}, ${b.x} ${midY}, ${b.x} ${b.y - NODE_H / 2}`;
    }
    let d = `M ${points[0].x} ${points[0].y + NODE_H / 2}`;
    for (let i = 1; i < points.length; i++) {
      const prev = points[i - 1], cur = points[i];
      const midY = (prev.y + cur.y) / 2;
      d += ` C ${prev.x} ${midY}, ${cur.x} ${midY}, ${cur.x} ${cur.y}`;
    }
    return d;
  }
  // Back edge (loop repeat / continue): route out to the side and back up,
  // like a hand-drawn flowchart loop-back arrow.
  const a = points[0], b = points[points.length - 1];
  const side = a.x >= b.x ? 1 : -1; // route on the side away from the body
  const offset = NODE_W / 2 + 46;
  const x1 = a.x + side * offset;
  return `M ${a.x + (side * NODE_W) / 2} ${a.y} ` +
         `C ${x1} ${a.y}, ${x1} ${b.y}, ${b.x + (side * NODE_W) / 2} ${b.y}`;
}

// --------------------------------------------------------------------- //
// 6. Pan & zoom (no library: wheel = zoom, drag = pan)
// --------------------------------------------------------------------- //

function attachPanZoom(container, svg, world) {
  let scale = 1, tx = 40, ty = 20;
  let dragging = false, lastX = 0, lastY = 0;

  function apply() {
    world.setAttribute("transform", `translate(${tx}, ${ty}) scale(${scale})`);
  }
  apply();

  container.addEventListener("wheel", (ev) => {
    ev.preventDefault();
    const rect = container.getBoundingClientRect();
    const mx = ev.clientX - rect.left, my = ev.clientY - rect.top;
    const factor = ev.deltaY < 0 ? 1.1 : 0.9;
    const newScale = Math.min(2.5, Math.max(0.15, scale * factor));
    tx = mx - ((mx - tx) / scale) * newScale;
    ty = my - ((my - ty) / scale) * newScale;
    scale = newScale;
    apply();
  }, { passive: false });

  container.addEventListener("mousedown", (ev) => {
    dragging = true; lastX = ev.clientX; lastY = ev.clientY;
    container.classList.add("grabbing");
  });
  window.addEventListener("mousemove", (ev) => {
    if (!dragging) return;
    tx += ev.clientX - lastX;
    ty += ev.clientY - lastY;
    lastX = ev.clientX; lastY = ev.clientY;
    apply();
  });
  window.addEventListener("mouseup", () => {
    dragging = false;
    container.classList.remove("grabbing");
  });

  container._codevisView = {
    zoomIn: () => { scale = Math.min(2.5, scale * 1.2); apply(); },
    zoomOut: () => { scale = Math.max(0.15, scale * 0.8); apply(); },
    reset: () => { scale = 1; tx = 40; ty = 20; apply(); },
    fit: () => {
      const rect = container.getBoundingClientRect();
      const bbox = svg.viewBox.baseVal;
      const s = Math.min(rect.width / bbox.width, rect.height / bbox.height) * 0.92;
      scale = Math.max(0.15, Math.min(2.5, s));
      tx = (rect.width - bbox.width * scale) / 2;
      ty = 20;
      apply();
    },
  };
}

export { layoutGraph };
export function getView(container) {
  return container._codevisView;
}

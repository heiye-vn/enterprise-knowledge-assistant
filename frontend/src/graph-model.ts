export type GraphNodeKind = 'document' | 'matter' | 'rule' | 'role' | 'material';
export type KnowledgeNode = { id: string; title: string; detail: string; kind: GraphNodeKind; sources: string[] };
export type KnowledgeEdge = { id: string; source: string; target: string; label: string; sources: string[] };
export type KnowledgeGraph = { nodes: KnowledgeNode[]; edges: KnowledgeEdge[] };
type GraphViewOptions = { rootIds: readonly string[]; expandedIds: readonly string[]; kinds: readonly string[]; search: string; maxNodes?: number };
export type GraphView = KnowledgeGraph & { matchedIds: string[]; truncated: boolean; eligibleCount: number };

export function collapseGraphNode(graph: KnowledgeGraph, options: GraphViewOptions, nodeId: string): string[] {
  const remaining = options.expandedIds.filter(id => id !== nodeId);
  const visible = new Set(buildGraphView(graph, { ...options, expandedIds: remaining }).nodes.map(node => node.id));
  return remaining.filter(id => visible.has(id));
}

export function getGraphViewportFit(points: readonly number[][], width: number, height: number) {
  const valid = points.filter(point => Number.isFinite(point[0]) && Number.isFinite(point[1]));
  if (!valid.length) return { zoom: 1, origin: [width / 2, height / 2], pan: [0, 0] };
  const xs = valid.map(point => point[0]);
  const ys = valid.map(point => point[1]);
  const minX = Math.min(...xs), maxX = Math.max(...xs), minY = Math.min(...ys), maxY = Math.max(...ys);
  const origin = [(minX + maxX) / 2, (minY + maxY) / 2];
  const zoom = Math.min(1, Math.max(40, width - 180) / Math.max(1, maxX - minX), Math.max(40, height - 120) / Math.max(1, maxY - minY));
  return { zoom, origin, pan: [width / 2 - origin[0], height / 2 - origin[1]] };
}

export function buildGraphView(graph: KnowledgeGraph, options: GraphViewOptions): GraphView {
  const eligible = graph.nodes.filter(node => options.kinds.includes(node.kind));
  const byId = new Map(eligible.map(node => [node.id, node]));
  const edges = graph.edges.filter(edge => byId.has(edge.source) && byId.has(edge.target));
  const query = options.search.trim().toLocaleLowerCase();
  const rank = (node: KnowledgeNode) => node.title.toLocaleLowerCase() === query ? 0 : node.title.toLocaleLowerCase().includes(query) ? 1 : 2;
  const matchedIds = query ? eligible.filter(node => `${node.title} ${node.detail}`.toLocaleLowerCase().includes(query)).sort((a, b) => rank(a) - rank(b)).map(node => node.id) : [];
  const roots = query ? matchedIds : options.rootIds.filter(id => byId.has(id));
  if (!query && !roots.length && eligible.length) roots.push(eligible[0].id);
  const limit = Math.max(1, Math.floor(options.maxNodes ?? 80));
  const visible = new Set<string>();
  let truncated = false;
  const add = (id: string) => {
    if (!byId.has(id) || visible.has(id)) return;
    if (visible.size >= limit) { truncated = true; return; }
    visible.add(id);
  };
  const neighbours = new Map<string, Set<string>>();
  for (const edge of edges) {
    if (!neighbours.has(edge.source)) neighbours.set(edge.source, new Set());
    if (!neighbours.has(edge.target)) neighbours.set(edge.target, new Set());
    neighbours.get(edge.source)!.add(edge.target);
    neighbours.get(edge.target)!.add(edge.source);
  }
  roots.forEach(add);
  for (const id of roots) if (visible.has(id)) neighbours.get(id)?.forEach(add);
  const processed = new Set<string>();
  let changed = true;
  while (changed) {
    changed = false;
    for (const id of options.expandedIds) {
      if (!visible.has(id) || processed.has(id)) continue;
      processed.add(id); changed = true; neighbours.get(id)?.forEach(add);
    }
  }
  return {
    nodes: eligible.filter(node => visible.has(node.id)),
    edges: edges.filter(edge => visible.has(edge.source) && visible.has(edge.target)),
    matchedIds, truncated, eligibleCount: eligible.length,
  };
}

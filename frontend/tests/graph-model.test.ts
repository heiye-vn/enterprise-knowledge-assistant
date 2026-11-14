import assert from 'node:assert/strict';
import test from 'node:test';
import { buildGraphView, collapseGraphNode, getGraphViewportFit } from '../src/graph-model.ts';
import type { KnowledgeGraph } from '../src/graph-model.ts';

const graph: KnowledgeGraph = {
  nodes: [
    { id: 'policy', title: '考勤制度', detail: '制度条款', kind: 'document', sources: ['leave'] },
    { id: 'short', title: '一天以内', detail: '请假时长', kind: 'rule', sources: ['leave'] },
    { id: 'long', title: '超过三天', detail: '请假时长', kind: 'rule', sources: ['leave'] },
    { id: 'manager', title: '直属主管', detail: '审批岗位', kind: 'role', sources: ['leave'] },
    { id: 'hr', title: '人力资源部', detail: '备案岗位', kind: 'role', sources: ['leave'] },
    { id: 'other', title: '其他事项', detail: '无直接关联', kind: 'matter', sources: ['training'] },
  ],
  edges: [
    { id: 'a', source: 'policy', target: 'short', label: '包含', sources: ['leave'] },
    { id: 'b', source: 'policy', target: 'long', label: '包含', sources: ['leave'] },
    { id: 'c', source: 'short', target: 'manager', label: '审批', sources: ['leave'] },
    { id: 'd', source: 'long', target: 'manager', label: '审批', sources: ['leave'] },
    { id: 'e', source: 'long', target: 'hr', label: '备案', sources: ['leave'] },
  ],
};
const options = { rootIds: ['policy'], expandedIds: [] as string[], kinds: ['document', 'rule', 'role', 'matter', 'material'] as const, search: '' };
const ids = (view: ReturnType<typeof buildGraphView>) => view.nodes.map(node => node.id).sort();

test('initial view only shows the selected topic and its immediate neighbours', () => {
  const view = buildGraphView(graph, options);
  assert.deepEqual(ids(view), ['long', 'policy', 'short']);
  assert.deepEqual(view.edges.map(edge => edge.id).sort(), ['a', 'b']);
});

test('expanding a visible node adds one hop without including disconnected nodes', () => {
  const view = buildGraphView(graph, { ...options, expandedIds: ['short'] });
  assert.deepEqual(ids(view), ['long', 'manager', 'policy', 'short']);
  assert.deepEqual(view.edges.map(edge => edge.id).sort(), ['a', 'b', 'c', 'd']);
});

test('collapsing a node returns its branch to the unexpanded view', () => {
  const expandedIds = collapseGraphNode(graph, { ...options, expandedIds: ['short'] }, 'short');
  const view = buildGraphView(graph, { ...options, expandedIds });
  assert.deepEqual(ids(view), ['long', 'policy', 'short']);
  assert.deepEqual(view.edges.map(edge => edge.id).sort(), ['a', 'b']);
});

test('collapsing one branch preserves shared nodes needed by another expanded branch', () => {
  const expandedIds = collapseGraphNode(graph, { ...options, expandedIds: ['short', 'long'] }, 'short');
  const view = buildGraphView(graph, { ...options, expandedIds });
  assert.deepEqual(expandedIds, ['long']);
  assert.deepEqual(ids(view), ['hr', 'long', 'manager', 'policy', 'short']);
  assert.deepEqual(view.edges.map(edge => edge.id).sort(), ['a', 'b', 'c', 'd', 'e']);
});

test('collapsing a branch clears hidden descendant expansions before it is expanded again', () => {
  const nested: KnowledgeGraph = {
    nodes: [...graph.nodes, { id: 'attachment', title: '申请材料', detail: '', kind: 'material', sources: ['leave'] }],
    edges: [...graph.edges, { id: 'f', source: 'manager', target: 'attachment', label: '核对材料', sources: ['leave'] }],
  };
  const collapsed = collapseGraphNode(nested, { ...options, expandedIds: ['short', 'manager'] }, 'short');
  assert.deepEqual(collapsed, []);
  const reopened = buildGraphView(nested, { ...options, expandedIds: [...collapsed, 'short'] });
  assert.deepEqual(ids(reopened), ['long', 'manager', 'policy', 'short']);
});

test('collapsing within search results preserves the search context and type filter', () => {
  const searched = { ...options, search: '直属主管', kinds: ['rule', 'role'] as const, expandedIds: ['long'] };
  const expandedIds = collapseGraphNode(graph, searched, 'long');
  const view = buildGraphView(graph, { ...searched, expandedIds });
  assert.deepEqual(ids(view), ['long', 'manager', 'short']);
  assert.deepEqual(view.matchedIds, ['manager']);
});

test('search locates a matched entity while preserving its immediate relationship context', () => {
  const view = buildGraphView(graph, { ...options, search: '  直属主管  ' });
  assert.deepEqual(ids(view), ['long', 'manager', 'short']);
  assert.deepEqual(view.matchedIds, ['manager']);
  assert.deepEqual(view.edges.map(edge => edge.id).sort(), ['c', 'd']);
});

test('an exact entity name is prioritised over mentions inside other node descriptions', () => {
  const mentioned: KnowledgeGraph = { ...graph, nodes: graph.nodes.map(node => node.id === 'policy' ? { ...node, detail: '直属主管参与请假审批' } : node) };
  const view = buildGraphView(mentioned, { ...options, search: '直属主管', maxNodes: 1 });
  assert.equal(view.matchedIds[0], 'manager');
  assert.deepEqual(ids(view), ['manager']);
});

test('type filters remove excluded nodes and every relationship pointing to them', () => {
  const view = buildGraphView(graph, { ...options, expandedIds: ['short', 'long'], kinds: ['document', 'rule'] });
  assert.deepEqual(ids(view), ['long', 'policy', 'short']);
  assert.deepEqual(view.edges.map(edge => edge.id).sort(), ['a', 'b']);
});

test('zero matches or no enabled types produce an empty view', () => {
  assert.deepEqual(ids(buildGraphView(graph, { ...options, search: '不存在' })), []);
  assert.deepEqual(ids(buildGraphView(graph, { ...options, kinds: [] })), []);
});

test('a busy neighbourhood respects the node budget and keeps the focus entity', () => {
  const nodes = Array.from({ length: 250 }, (_, index) => ({ id: `child-${index}`, title: `事项${index}`, detail: '', kind: 'rule' as const, sources: ['leave'] }));
  const busy: KnowledgeGraph = {
    nodes: [graph.nodes[0], ...nodes],
    edges: nodes.map(node => ({ id: `to-${node.id}`, source: 'policy', target: node.id, label: '包含', sources: ['leave'] })),
  };
  const view = buildGraphView(busy, { ...options, maxNodes: 40 });
  assert.equal(view.nodes.length, 40);
  assert(view.nodes.some(node => node.id === 'policy'));
  assert.equal(view.edges.length, 39);
  assert.equal(view.truncated, true);
  assert(view.edges.every(edge => view.nodes.some(node => node.id === edge.source) && view.nodes.some(node => node.id === edge.target)));
});

test('fitting an expanded graph keeps every node inside the canvas with room for labels', () => {
  const points: [number, number][] = [[100, -100], [300, 500]];
  const fit = getGraphViewportFit(points, 400, 300);
  for (const point of points) {
    const x = (point[0] - fit.origin[0]) * fit.zoom + fit.origin[0] + fit.pan[0];
    const y = (point[1] - fit.origin[1]) * fit.zoom + fit.origin[1] + fit.pan[1];
    assert(x >= 90 && x <= 310);
    assert(y >= 60 && y <= 240);
  }
});

test('fitting a single node centres it without enlarging it', () => {
  const fit = getGraphViewportFit([[10, 20]], 400, 300);
  assert.equal(fit.zoom, 1);
  assert.deepEqual(fit.pan, [190, 130]);
});

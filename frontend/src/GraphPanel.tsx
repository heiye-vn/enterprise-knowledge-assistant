import { useEffect, useMemo, useRef, useState } from 'react';
import { ArrowDownToLine, ArrowUpRight, Expand, Focus, GitBranch, Minus, Network, Plus, RotateCcw, Shrink } from 'lucide-react';
import EChartsGraph from './EChartsGraph';
import type { GraphChartHandle } from './EChartsGraph';
import { graphKinds, graphScenarios } from './graph-data';
import type { GraphScenario } from './graph-data';
import { buildGraphView, collapseGraphNode } from './graph-model';
import type { GraphNodeKind } from './graph-model';
import { initialDocuments, sources } from './demo';
import './graph.css';

type Props = { scenario: GraphScenario; search: string; kinds: GraphNodeKind[]; onSource: (id: string) => void; onReset: () => void };
type Selection = { type: 'node' | 'edge'; id: string } | null;

export default function GraphPanel({ scenario, search, kinds, onSource, onReset }: Props) {
  const current = graphScenarios.find(item => item.id === scenario)!;
  const [expandedIds, setExpandedIds] = useState<string[]>([]);
  const [selection, setSelection] = useState<Selection>(null);
  const chart = useRef<GraphChartHandle>(null);
  useEffect(() => { setExpandedIds([]); setSelection(null); }, [search, kinds]);
  const view = useMemo(() => buildGraphView(current.graph, { rootIds: current.rootIds, expandedIds, kinds, search }), [current, expandedIds, kinds, search]);
  const selectedNode = view.nodes.find(node => selection?.type === 'node' && node.id === selection.id)
    ?? (!selection && search.trim() ? view.nodes.find(node => node.id === view.matchedIds[0]) : undefined);
  const selectedEdge = view.edges.find(edge => selection?.type === 'edge' && edge.id === selection.id);
  const byId = new Map(current.graph.nodes.map(node => [node.id, node]));
  const visibleIds = new Set(view.nodes.map(node => node.id));
  const hiddenNeighbours = selectedNode ? new Set(current.graph.edges.flatMap(edge => {
    const neighbourId = edge.source === selectedNode.id ? edge.target : edge.target === selectedNode.id ? edge.source : null;
    const neighbour = neighbourId ? byId.get(neighbourId) : undefined;
    return neighbour && kinds.includes(neighbour.kind) && !visibleIds.has(neighbour.id) ? [neighbour.id] : [];
  })) : new Set<string>();
  const expandableIds = new Set<string>();
  for (const edge of current.graph.edges) {
    if (visibleIds.has(edge.source) && !visibleIds.has(edge.target) && kinds.includes(byId.get(edge.target)!.kind)) expandableIds.add(edge.source);
    if (visibleIds.has(edge.target) && !visibleIds.has(edge.source) && kinds.includes(byId.get(edge.source)!.kind)) expandableIds.add(edge.target);
  }
  const selectedExpanded = !!selectedNode && expandedIds.includes(selectedNode.id);
  const sourceIds = [...new Set(selectedNode?.sources ?? selectedEdge?.sources ?? [])];
  const selectionTitle = selectedNode?.title ?? (selectedEdge ? `${byId.get(selectedEdge.source)?.title} → ${byId.get(selectedEdge.target)?.title}` : '选择节点，探索它的关联');
  const selectionDescription = selectedNode?.detail ?? (selectedEdge ? selectedEdge.label : '点击画布中的节点或连线，可查看详情、展开关联和核对原文。');
  function expand(ids: string[]) {
    const frontier = ids.filter(id => expandableIds.has(id));
    if (frontier.length) setExpandedIds(previous => [...new Set([...previous, ...frontier])]);
  }
  function collapse(nodeId: string) {
    setExpandedIds(previous => collapseGraphNode(current.graph, { rootIds: current.rootIds, expandedIds: previous, kinds, search }, nodeId));
  }
  function collapseAll() {
    setExpandedIds([]); setSelection(null);
  }
  function reset() {
    setExpandedIds([]); setSelection(null); onReset();
  }

  return <div className="graph-view graph-explorer">
    <div className="graph-intro"><span className="eyebrow">CONNECTED KNOWLEDGE</span><h2>探索制度之间的知识关联</h2><p>从一个主题出发，逐层展开，每条关系都能回到原文。</p><span className="graph-demo-label">示例关系 · 尚未接入自动抽取</span></div>
    <div className="graph-explorer-toolbar">
      <div className="graph-topic-label"><Network size={16} /><strong>{current.title}</strong><span role="status">显示 {view.nodes.length} / {view.eligibleCount} 个节点 · {view.edges.length} 条关系</span></div>
      <div className="graph-toolbar-actions"><button className="secondary-button" disabled={!expandableIds.size || view.nodes.length >= 80} onClick={() => expand(view.nodes.map(node => node.id))}><Expand size={14} />展开一层</button><button className="secondary-button" disabled={!expandedIds.length} onClick={collapseAll}><Shrink size={14} />收起全部</button><button className="icon-button" aria-label="重置图谱与筛选" title="重置图谱与筛选" onClick={reset}><RotateCcw size={16} /></button></div>
    </div>
    <div className="graph-type-legend" aria-label="节点类型图例">{graphKinds.filter(kind => kinds.includes(kind.id) && current.graph.nodes.some(node => node.kind === kind.id)).map(kind => <span key={kind.id}><i style={{ backgroundColor: kind.color }} />{kind.label}</span>)}</div>
    <div className="graph-canvas knowledge-canvas" id="knowledge-graph-canvas">
      {view.nodes.length ? <>
        <EChartsGraph ref={chart} view={view} selectedNodeId={selectedNode?.id} selectedEdgeId={selectedEdge?.id} onNode={id => setSelection({ type: 'node', id })} onEdge={id => setSelection({ type: 'edge', id })} />
        <div className="graph-canvas-help"><span className="graph-drag-hint">拖动节点 · </span>平移画布 · 滚轮缩放</div>
        <div className="graph-zoom-controls" aria-label="画布操作"><button aria-label="放大图谱" title="放大" onClick={() => chart.current?.zoom(1.2)}><Plus size={17} /></button><button aria-label="缩小图谱" title="缩小" onClick={() => chart.current?.zoom(1 / 1.2)}><Minus size={17} /></button><button aria-label="适应画布" title="适应画布" onClick={() => chart.current?.fit()}><Focus size={17} /></button></div>
        <div className="graph-canvas-caption">悬停查看关系 · 点击选择节点</div>
      </> : <div className="graph-empty"><Network size={32} /><h3>没有符合条件的节点</h3><p>调整左侧搜索关键词或节点类型。</p><button className="secondary-button" onClick={reset}>重置节点筛选</button></div>}
    </div>
    {view.truncated && <p className="graph-budget-note" role="status">当前画布最多展示 80 个节点，请搜索更具体的实体以缩小范围。</p>}
    <section className={`graph-inspector ${selectedNode || selectedEdge ? 'has-selection' : ''}`} aria-label="图谱选择详情" aria-live="polite">
      <div className="graph-inspector-content"><span className="graph-selection-type">{selectedNode ? graphKinds.find(kind => kind.id === selectedNode.kind)?.label : selectedEdge ? '关系依据' : '关联探索'}</span><h3>{selectionTitle}</h3><p>{selectionDescription}</p>
        {!!sourceIds.length && <div className="graph-evidence-links">{sourceIds.map(id => {
          const source = sources[id];
          const document = initialDocuments.find(doc => doc.id === source.documentId);
          return <button key={id} onClick={() => onSource(id)}><ArrowUpRight size={13} />{document?.title} · {source.clause} · P{source.page}</button>;
        })}</div>}
      </div>
      {selectedNode && <div className="graph-inspector-actions"><button className="secondary-button" aria-expanded={selectedExpanded} aria-controls="knowledge-graph-canvas" disabled={!selectedExpanded && (!hiddenNeighbours.size || view.nodes.length >= 80)} onClick={() => selectedExpanded ? collapse(selectedNode.id) : expand([selectedNode.id])}>{selectedExpanded ? <Shrink size={15} /> : <GitBranch size={15} />}{selectedExpanded ? '收起关联' : `展开关联${hiddenNeighbours.size > 0 ? `（${hiddenNeighbours.size}）` : ''}`}</button><small>{selectedExpanded ? '收起当前分支，保留其他分支的关联' : hiddenNeighbours.size ? '增加与当前节点直接相连的实体' : '当前类型下的直接关联已显示'}</small></div>}
    </section>
    <details className="graph-accessible-list"><summary><span><ArrowDownToLine size={14} />节点与关系列表</span><small>支持键盘选择与查看依据</small></summary><div className="graph-node-list" aria-label="当前画布节点">{view.nodes.map(node => <button key={node.id} className={selectedNode?.id === node.id ? 'active' : ''} aria-pressed={selectedNode?.id === node.id} onClick={() => setSelection({ type: 'node', id: node.id })}><i style={{ backgroundColor: graphKinds.find(kind => kind.id === node.kind)?.color }} /><span>{node.title}</span><small>{graphKinds.find(kind => kind.id === node.kind)?.label}</small></button>)}</div><ul className="graph-edge-list" aria-label="当前画布关系">{view.edges.slice(0, 100).map(edge => <li key={edge.id}><button className={selectedEdge?.id === edge.id ? 'active' : ''} onClick={() => setSelection({ type: 'edge', id: edge.id })}>{byId.get(edge.source)?.title}<span>— {edge.label} →</span>{byId.get(edge.target)?.title}</button></li>)}</ul>{view.edges.length > 100 && <p className="graph-list-note">列表显示前 100 条关系，可用搜索缩小范围。</p>}</details>
  </div>;
}

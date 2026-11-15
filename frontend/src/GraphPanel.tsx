import { useEffect, useMemo, useRef, useState } from 'react';
import { ArrowDownToLine, Expand, Focus, GitBranch, Minus, Network, Plus, RotateCcw, Shrink } from 'lucide-react';
import EChartsGraph from './EChartsGraph';
import type { GraphChartHandle } from './EChartsGraph';
import { graphKinds } from './graph-data';
import {getKnowledgeGraph,buildKnowledgeGraph} from './api';
import {GraphEvidence,GraphJobList} from './GraphDetails';
import type {GraphResponse} from './graph-api-types';
import { buildGraphView, collapseGraphNode } from './graph-model';
import type { GraphNodeKind } from './graph-model';
import type { KnowledgeDocument, ChunkSource } from './document-types';
import './graph.css';

type Props = {documents:KnowledgeDocument[];onSource:(source:ChunkSource,tab?:'passage'|'indexed')=>void};
type Selection = {type:'node'|'edge';id:string}|null;
const emptyGraph={nodes:[],edges:[],root_ids:[],sources:{}};

export default function GraphPanel({documents,onSource}:Props) {
  const [data,setData]=useState<GraphResponse|null>(null);
  const [loading,setLoading]=useState(true);
  const [error,setError]=useState('');
  const [requesting,setRequesting]=useState(false);
  const [notice,setNotice]=useState('');
  const [documentId,setDocumentId]=useState('');
  const [search,setSearch]=useState('');
  const [kinds,setKinds]=useState<GraphNodeKind[]>(graphKinds.map(kind=>kind.id));
  const [refresh,setRefresh]=useState(0);
  const loadedScope=useRef(documentId);
  useEffect(()=>{
    const controller=new AbortController();let timer:ReturnType<typeof setTimeout>;
    setLoading(true);setError('');
    if(loadedScope.current!==documentId){setData(null);loadedScope.current=documentId;}
    async function load(){
      try {
        const response=await getKnowledgeGraph(documentId||null,controller.signal);
        if(controller.signal.aborted)return;
        setData(response);setError('');
        timer=setTimeout(()=>{void load();},response.jobs.some(job=>['queued','running'].includes(job.status))?1500:10000);
      } catch(failure){
        if(controller.signal.aborted)return;
        setError(failure instanceof Error?failure.message:'图谱暂时无法读取。');
        timer=setTimeout(()=>{void load();},5000);
      } finally {if(!controller.signal.aborted)setLoading(false);}
    }
    void load();return()=>{controller.abort();clearTimeout(timer);};
  },[documentId,refresh]);
  async function generate(target:string|null=documentId||null){
    if(requesting)return;setRequesting(true);setError('');setNotice('');
    try {const result=await buildKnowledgeGraph(target?[target]:null);if(result.created===0&&result.jobs.every(job=>job.status==='ready'))setNotice('当前图谱已是最新，无需重复生成。');else setRefresh(value=>value+1);}
    catch(failure){setError(failure instanceof Error?failure.message:'暂时无法生成图谱。');}
    finally{setRequesting(false);}
  }
  const graph=useMemo(()=>data?{nodes:data.nodes,edges:data.edges,root_ids:data.root_ids,sources:data.sources}:emptyGraph,[data?.fingerprint,data?.available]);
  const current=useMemo(()=>({graph,rootIds:graph.root_ids.slice(0,1)}),[graph]);
  const hasActive=!!data?.jobs.some(job=>['queued','running'].includes(job.status));
  const [expandedIds, setExpandedIds] = useState<string[]>([]);
  const [selection, setSelection] = useState<Selection>(null);
  const chart = useRef<GraphChartHandle>(null);
  useEffect(() => { setExpandedIds([]); setSelection(null); }, [search, kinds, data?.fingerprint]);
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
  const selectionDescription = selectedNode ? (selectedNode.kind==='rule'?'规则的适用条件和原文依据见下方。':selectedNode.detail) : selectedEdge?selectedEdge.label:'点击画布中的节点或连线，可查看详情、展开关联和核对原文。';
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
    setExpandedIds([]);setSelection(null);setSearch('');setKinds(graphKinds.map(kind=>kind.id));
  }

  return <div className="graph-view graph-explorer">
    <div className="graph-intro graph-live-intro"><div><h2>探索制度之间的知识关联</h2><p>关系保留适用条件和来源，请结合原文核对。</p></div><button className="primary-button" disabled={requesting||hasActive||!documents.some(doc=>doc.canQuery)} onClick={()=>{void generate();}}><Network size={16}/>{requesting?'提交中…':hasActive?'正在生成…':data?.nodes.length?'补全知识图谱':'生成知识图谱'}</button></div>
    <div className="graph-search-controls"><div className="graph-live-filters"><label><span className="sr-only">图谱文档范围</span><select aria-label="图谱文档范围" value={documentId} onChange={event=>{setDocumentId(event.target.value);setSearch('');setSelection(null);setExpandedIds([]);}}><option value="">全部可用文档</option>{documents.filter(doc=>doc.canQuery).map(doc=><option value={doc.id} key={doc.id}>{doc.title}</option>)}</select></label><label className="search-input"><span className="sr-only">搜索图谱实体</span><input aria-label="搜索图谱实体" value={search} onChange={event=>setSearch(event.target.value)} placeholder="搜索事项、制度或岗位"/></label></div>
    <div className="graph-live-kind-filters" aria-label="图谱节点类型">{graphKinds.map(kind=><label key={kind.id}><input type="checkbox" checked={kinds.includes(kind.id)} onChange={()=>setKinds(previous=>previous.includes(kind.id)?previous.filter(id=>id!==kind.id):[...previous,kind.id])}/><i style={{backgroundColor:kind.color}}/>{kind.label}</label>)}</div></div>
    {notice&&<p role="status" className="graph-task-note">{notice}</p>}
    {error&&<p role="alert" className="graph-task-error">{error}<button className="text-button" onClick={()=>setRefresh(value=>value+1)}>重新加载</button></p>}
    {data&&!data.available&&<p role="alert" className="graph-task-error">{data.error?.message??'图谱服务暂不可用。'}</p>}
    {data&&<GraphJobList jobs={data.jobs} busy={requesting} onRetry={id=>{void generate(id);}} onDocument={setDocumentId}/>}
    {data?.jobs.some(job=>job.rejected_count>0||job.unit_limit_reached)&&<p className="graph-task-warning">部分条款未通过校验或达到处理上限，图谱覆盖范围请查看“文档图谱状态”。</p>}
    <div className="graph-explorer-toolbar">
      <div className="graph-topic-label"><Network size={16} /><strong>{documentId?documents.find(doc=>doc.id===documentId)?.title:'全部制度关联'}</strong><span role="status">显示 {view.nodes.length} / {view.eligibleCount} 个节点 · {view.edges.length} 条关系</span></div>
      <div className="graph-toolbar-actions"><button className="secondary-button" disabled={!expandableIds.size || view.nodes.length >= 80} onClick={() => expand(view.nodes.map(node => node.id))}><Expand size={14} />展开一层</button><button className="secondary-button" disabled={!expandedIds.length} onClick={collapseAll}><Shrink size={14} />收起全部</button><button className="icon-button" aria-label="重置图谱与筛选" title="重置图谱与筛选" onClick={reset}><RotateCcw size={16} /></button></div>
    </div>

    <div className="graph-canvas knowledge-canvas" id="knowledge-graph-canvas">
      {view.nodes.length ? <>
        <EChartsGraph ref={chart} view={view} selectedNodeId={selectedNode?.id} selectedEdgeId={selectedEdge?.id} onNode={id => setSelection({ type: 'node', id })} onEdge={id => setSelection({ type: 'edge', id })} />
        <div className="graph-canvas-help"><span className="graph-drag-hint">拖动节点 · </span>平移画布 · 滚轮缩放</div>
        <div className="graph-zoom-controls" aria-label="画布操作"><button aria-label="放大图谱" title="放大" onClick={() => chart.current?.zoom(1.2)}><Plus size={17} /></button><button aria-label="缩小图谱" title="缩小" onClick={() => chart.current?.zoom(1 / 1.2)}><Minus size={17} /></button><button aria-label="适应画布" title="适应画布" onClick={() => chart.current?.fit()}><Focus size={17} /></button></div>
        <div className="graph-canvas-caption">悬停查看关系 · 点击选择节点</div>
      </> : <div className="graph-empty"><Network size={32} /><h3>{loading?'正在读取图谱…':data&&!data.available?'图谱暂时无法读取':hasActive?'正在生成制度关联':search.trim()?'没有匹配的实体':data?.nodes.length?'当前筛选没有可见节点':'知识图谱尚未生成'}</h3><p>{hasActive?'正在分批处理原文，页面会自动更新。':search.trim()?'可以换一个关键词，或重置筛选。':'文档索引完成后，点击“生成知识图谱”开始。'}</p><button className="secondary-button" onClick={reset}>重置节点筛选</button></div>}
    </div>
    {(view.truncated||data?.truncated) && <p className="graph-budget-note" role="status">当前画布最多展示 80 个节点，请搜索更具体的实体以缩小范围。</p>}
    <section className={`graph-inspector ${selectedNode || selectedEdge ? 'has-selection' : ''}`} aria-label="图谱选择详情" aria-live="polite">
      <div className="graph-inspector-content"><span className="graph-selection-type">{selectedNode ? graphKinds.find(kind => kind.id === selectedNode.kind)?.label : selectedEdge ? '关系依据' : '关联探索'}</span><h3>{selectionTitle}</h3><p>{selectionDescription}</p>
        <GraphEvidence ids={sourceIds} sources={graph.sources} onSource={onSource}/>
      </div>
      {selectedNode && <div className="graph-inspector-actions"><button className="secondary-button" aria-expanded={selectedExpanded} aria-controls="knowledge-graph-canvas" disabled={!selectedExpanded && (!hiddenNeighbours.size || view.nodes.length >= 80)} onClick={() => selectedExpanded ? collapse(selectedNode.id) : expand([selectedNode.id])}>{selectedExpanded ? <Shrink size={15} /> : <GitBranch size={15} />}{selectedExpanded ? '收起关联' : `展开关联${hiddenNeighbours.size > 0 ? `（${hiddenNeighbours.size}）` : ''}`}</button><small>{selectedExpanded ? '收起当前分支，保留其他分支的关联' : hiddenNeighbours.size ? '增加与当前节点直接相连的实体' : '当前类型下的直接关联已显示'}</small></div>}
    </section>
    <details className="graph-accessible-list"><summary><span><ArrowDownToLine size={14} />节点与关系列表</span><small>支持键盘选择与查看依据</small></summary><div className="graph-node-list" aria-label="当前画布节点">{view.nodes.map(node => <button key={node.id} className={selectedNode?.id === node.id ? 'active' : ''} aria-pressed={selectedNode?.id === node.id} onClick={() => setSelection({ type: 'node', id: node.id })}><i style={{ backgroundColor: graphKinds.find(kind => kind.id === node.kind)?.color }} /><span>{node.title}</span><small>{graphKinds.find(kind => kind.id === node.kind)?.label}</small></button>)}</div><ul className="graph-edge-list" aria-label="当前画布关系">{view.edges.slice(0, 100).map(edge => <li key={edge.id}><button className={selectedEdge?.id === edge.id ? 'active' : ''} onClick={() => setSelection({ type: 'edge', id: edge.id })}>{byId.get(edge.source)?.title}<span>— {edge.label} →</span>{byId.get(edge.target)?.title}</button></li>)}</ul>{view.edges.length > 100 && <p className="graph-list-note">列表显示前 100 条关系，可用搜索缩小范围。</p>}</details>
  </div>;
}

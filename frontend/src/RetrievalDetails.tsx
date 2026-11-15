import {ArrowDown,ChevronDown,Clock3,FileSearch} from 'lucide-react';
import type {ChunkSource} from './document-types';
import {InlineMarkdown} from './MarkdownContent';
import {WebSearchDetails} from './WebSources';
import GraphPaths from './GraphPaths';
import type {ExecutionDetails,ExecutionStage,RetrievalCandidate,RetrievalTrace} from './retrieval-types';

const modeNames={general:'通用对话',knowledge:'知识库问答',clarify:'需要澄清',web:'联网查询'};
const stageNames:Record<string,string>={intent:'意图判断',retrieval:'知识检索',answer:'独立回答调用',bm25:'关键词召回',vector:'向量召回',fusion:'RRF 融合',graph:'图谱证据扩展',rerank:'模型重排',validation:'正文与引用校验',web_search:'联网搜索'};
const outcomes:Record<string,string>={general:'模型通用回答',clarify:'等待补充条件',answered:'有据回答',partially_answered:'部分有据回答',refused:'未找到足够依据',no_sources:'未召回可用资料',low_relevance:'相关性不足，未调用回答模型',failed:'本轮执行失败',running:'正在处理',stopped:'已停止生成',interrupted:'生成已中断',web:'联网回答',web_no_results:'未找到足够公开依据'};
function duration(value:number|null){return value===null?'':value<1?'<1 ms':value<1000?`${Math.round(value)} ms`:`${(value/1000).toFixed(2)} s`;}
function StageList({stages}:{stages:ExecutionStage[]}){
  return <ol className="execution-stages">{stages.map(stage=><li key={stage.key} className={`stage-${stage.status}`}><span className="stage-dot"/><span>{stageNames[stage.key]??stage.key}</span><small>{stage.note==='included_in_intent'?'随意图调用返回':stage.status==='skipped'?'未执行':stage.status==='failed'?'失败':'完成'}{stage.duration_ms!==null?` · ${duration(stage.duration_ms)}`:''}</small></li>)}</ol>;
}
function score(candidate:RetrievalCandidate,key:keyof RetrievalCandidate['scores'],trace:RetrievalTrace){
  const value=candidate.scores[key];
  if(typeof value==='number'&&Number.isFinite(value))return value.toFixed(key==='rrf'?6:4);
  if(key==='rrf'&&candidate.graph_expanded)return '未参与融合';
  const stage=trace.stages.find(s=>s.key===(key==='vector_distance'?'vector':key));
  return stage?.status==='failed'?'未完成':key==='rerank'?'未参与':'未命中';
}
function Candidate({candidate,trace,onSource}:{candidate:RetrievalCandidate;trace:RetrievalTrace;onSource:(source:ChunkSource,tab?:'passage'|'indexed')=>void}){
  const source=candidate.source;
  const channels=[candidate.ranks.bm25!==null?'关键词':null,candidate.ranks.vector!==null?'向量':null,candidate.graph_expanded?'图谱':null].filter(Boolean).join(' + ');
  return <article className="candidate-card"><div className="candidate-top"><span className="candidate-ranks">{candidate.ranks.fusion===null?'图谱补充':`融合 #${candidate.ranks.fusion}`}<ArrowDown size={12}/>{candidate.ranks.rerank!==null?`重排 #${candidate.ranks.rerank}`:'未获得重排排名'}</span><span className={`candidate-use ${candidate.used_in_answer?'candidate-cited':''}`}>{candidate.used_in_answer?`实际引用 [${candidate.citation_no}]`:candidate.sent_to_model?'已送入回答':candidate.selected?'入选检索结果':'召回候选'}</span></div><strong className="candidate-title">{source.document_title}<small>切块 {source.ordinal+1}</small></strong><p className="candidate-location"><InlineMarkdown text={source.heading_path.join(' / ')||'正文'}/>{source.page_start!==null?` · 第 ${source.page_start} 页`:''}</p><p className="candidate-excerpt">{source.content}</p><dl className="candidate-scores">{([
    ['bm25','BM25 ↑','关键词匹配得分，越高越相关；不同查询间不能直接比较'],
    ['vector_distance','向量距离 ↓','余弦距离，越低越接近'],
    ['rrf','RRF ↑','按多路召回排名融合，越高越靠前'],
    ['rerank','重排 ↑','重排模型相关性分数，不是答案正确率'],
  ] as const).map(([key,label,title])=><div key={key} title={title}><dt>{label}</dt><dd>{score(candidate,key,trace)}</dd></div>)}</dl><div className="candidate-footer"><span>召回渠道：{channels||'无'}</span><div><button type="button" className="text-button" onClick={()=>onSource(source,'passage')}>查看原文</button><button type="button" className="text-button" onClick={()=>onSource(source,'indexed')}>查看切块</button></div></div></article>;
}

export default function RetrievalDetails({details,warnings=[],onSource}:{details:ExecutionDetails|null|undefined;warnings?:{code:string;message:string}[];onSource:(source:ChunkSource,tab?:'passage'|'indexed')=>void}){
  if(!details)return null;
  const trace=details.retrieval;
  const candidates=trace?[...trace.candidates].sort((a,b)=>(a.ranks.rerank??Infinity)-(b.ranks.rerank??Infinity)||(a.ranks.fusion??Infinity)-(b.ranks.fusion??Infinity)):[];
  const mode=details.intent?.mode;
  return <details className="execution-details"><summary><FileSearch size={15}/><span>{mode==='knowledge'?'检索详情':'问答过程'}</span><small>{mode?modeNames[mode]:'意图未完成'}{details.total_ms!==null?` · ${duration(details.total_ms)}`:''}</small><ChevronDown size={15} className="details-chevron"/></summary><div className="execution-content"><div className="execution-overview"><span>本轮路径 <strong>{mode?modeNames[mode]:'未完成'}</strong></span><span>{outcomes[details.outcome]??details.outcome}</span></div>{details.intent?.decision==='evidence_guard'&&<p className="execution-note">本轮涉及企业内部事实，已要求使用文档依据。</p>}{details.intent?.query&&<div className="execution-query"><span>实际检索问题</span><p>{details.intent.query}</p></div>}<StageList stages={details.stages}/>{warnings.map((warning,i)=><p className="execution-warning" role="status" key={`${warning.code}-${i}`}>{warning.message}</p>)}{details.web&&<WebSearchDetails web={details.web}/>} {trace&&<><div className="retrieval-counts"><span>检索范围 <b>{trace.counts.documents}</b> 份文档</span><span>关键词 <b>{trace.counts.bm25}</b></span><span>向量 <b>{trace.counts.vector}</b></span><span>融合 <b>{trace.counts.fusion}</b></span><span>参与重排 <b>{trace.counts.rerank_input}</b></span><span>检索返回 <b>{trace.counts.returned}</b></span></div><StageList stages={trace.stages}/>{trace.graph&&<GraphPaths graph={trace.graph} onSource={onSource}/>}<p className="execution-note score-explanation">分数表示检索相关性，不是答案正确率。↑ 越高越相关，↓ 越低越相关；未命中或未执行的阶段不填分数。</p>{candidates.length?<><p className="candidate-count">展示 {candidates.length} 个融合候选 · 最终引用 {candidates.filter(c=>c.used_in_answer).length} 个</p>{candidates.slice(0,6).map(candidate=><Candidate key={candidate.source.id} candidate={candidate} trace={trace} onSource={onSource}/>)}{candidates.length>6&&<details className="remaining-candidates"><summary>其余 {candidates.length-6} 个融合候选<ChevronDown size={14}/></summary>{candidates.slice(6).map(candidate=><Candidate key={candidate.source.id} candidate={candidate} trace={trace} onSource={onSource}/>)}</details>}</>:<p className="execution-note">本轮没有可展示的候选切块。</p>}</>}{details.trace_id&&<p className="execution-note trace-id">LangSmith Trace ID：<code>{details.trace_id}</code></p>}<p className="execution-footnote"><Clock3 size={12}/>本轮执行记录已保存，展开详情不会重新检索。</p></div></details>;
}

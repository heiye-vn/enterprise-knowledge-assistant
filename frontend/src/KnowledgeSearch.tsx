import {useEffect, useRef, useState} from 'react';
import {ArrowUpRight, FileSearch, LoaderCircle, Search} from 'lucide-react';
import {searchKnowledge} from './api';
import type {ChunkSource, KnowledgeDocument, SearchResponse} from './document-types';

export default function KnowledgeSearch({documents,onSource}: {documents:KnowledgeDocument[];onSource:(source:ChunkSource)=>void}) {
  const [question,setQuestion] = useState('');
  const [scope,setScope] = useState('all');
  const [result,setResult] = useState<SearchResponse | null>(null);
  const [submitted,setSubmitted] = useState('');
  const [error,setError] = useState('');
  const [loading,setLoading] = useState(false);
  const pending = useRef<AbortController | null>(null);
  useEffect(() => () => pending.current?.abort(),[]);
  function changed() {pending.current?.abort();setLoading(false);setResult(null);setError('');setSubmitted('');}
  async function submit(event:React.SubmitEvent<HTMLFormElement>) {
    event.preventDefault();
    const query = question.trim();
    if (query.length < 2 || loading) return;
    pending.current?.abort();
    const controller = new AbortController();pending.current = controller;
    setLoading(true);setError('');setResult(null);setSubmitted(query);
    try {const response = await searchKnowledge(query,scope === 'all' ? null : [scope],controller.signal);if (!controller.signal.aborted) setResult(response);}
    catch (failure) {if (!controller.signal.aborted) setError(failure instanceof Error ? failure.message : '检索暂时不可用');}
    finally {if (!controller.signal.aborted) setLoading(false);}
  }
  return <section className="knowledge-search" aria-label="原文检索">
    <form onSubmit={submit} className="knowledge-search-form">
      <label className="search-input"><Search size={17}/><input aria-label="检索文档正文" placeholder="例如：超过 5000 元的报销由谁审批？" maxLength={1000} value={question} onChange={e => {changed();setQuestion(e.target.value);}}/></label>
      <label className="retrieval-scope"><span className="sr-only">检索范围</span><select aria-label="检索范围" value={scope} onChange={e => {changed();setScope(e.target.value);}}><option value="all">全部可检索文档</option>{documents.filter(d => d.canQuery).map(d => <option key={d.id} value={d.id}>{d.title}</option>)}</select></label>
      <button className="primary-button" disabled={loading || question.trim().length < 2}>{loading ? <LoaderCircle size={16} className="spinning"/> : <Search size={16}/>}检索原文</button>
    </form>
    <p className="retrieval-hint">按含义和关键词查找原文依据，点击结果核对章节与原件。</p>
    {loading && <p role="status" className="empty-note">正在查找与问题相关的原文…</p>}
    {error && <p role="alert" className="form-error">{error}</p>}
    {result && <><div className="retrieval-summary" role="status">“{submitted}” · {result.items.length} 条原文 · 本次范围 {result.snapshot.documents.length} 份文档</div>
      {result.warnings.map((warning,i) => <p key={i} role="status" className="retrieval-warning">{warning.message}</p>)}
      <div className="retrieval-results">{result.items.map((source,index) => <button className="retrieval-card" key={source.id} onClick={() => onSource(source)}><span className="retrieval-card-title"><span><b>{index + 1}</b>{source.document_title}</span><ArrowUpRight size={17}/></span><span className="retrieval-location">版本 {source.version_no} · {source.heading_path.join(' / ') || '正文'}{source.page_start !== null ? ` · 第 ${source.page_start}${source.page_end !== source.page_start ? `–${source.page_end}` : ''} 页` : ' · 按章节定位'}</span><span className="retrieval-excerpt">{source.content}</span><span className="retrieval-open">查看完整切片与来源</span></button>)}</div>
      {!result.items.length && <div className="library-empty"><FileSearch size={28}/><h3>未找到相关原文</h3><p>试试更具体的词语，或确认所选文档已完成索引。</p></div>}
    </>}
  </section>;
}

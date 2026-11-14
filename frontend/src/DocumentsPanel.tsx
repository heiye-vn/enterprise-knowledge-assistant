import { useEffect, useState } from 'react';
import { ChevronLeft, ChevronRight, CircleAlert, CircleCheck, FileSearch, FileText, LoaderCircle, Plus, Search, X } from 'lucide-react';
import { fileSize, statusNames } from './demo';
import type { KnowledgeDocument } from './demo';
import type { DocumentFilters } from './workspace';

type Props = { documents: KnowledgeDocument[]; filters: DocumentFilters; onFilters: (filters: DocumentFilters) => void; onDocument: (doc: KnowledgeDocument) => void; onUpload: () => void };
const statusLabels = { all: '全部状态', ready: '处理完成', processing: '处理中', failed: '处理失败' };

export default function DocumentsPanel({ documents, filters, onFilters, onDocument, onUpload }: Props) {
  const [search, setSearch] = useState('');
  const [requestedPage, setRequestedPage] = useState(1);
  const [pageSize, setPageSize] = useState(10);
  useEffect(() => { setRequestedPage(1); }, [filters.category, filters.status]);
  const filtered = documents.filter(doc => (!filters.category || doc.category === filters.category)
    && (filters.status === 'all' || (filters.status === 'processing' ? !['ready', 'failed'].includes(doc.status) : doc.status === filters.status))
    && `${doc.title} ${doc.category} ${doc.filename}`.toLowerCase().includes(search.trim().toLowerCase()));
  const pageCount = Math.max(1, Math.ceil(filtered.length / pageSize));
  const currentPage = Math.min(requestedPage, pageCount);
  const visible = filtered.slice((currentPage - 1) * pageSize, currentPage * pageSize);
  return <div className="documents-view">
    <div className="section-intro"><div><span className="eyebrow">YOUR KNOWLEDGE LIBRARY</span><h2>把分散的制度，变成可查阅的知识。</h2><p>集中管理资料，按分类、状态或关键词快速定位。</p></div><button className="primary-button" onClick={onUpload}><Plus size={16} />上传文档</button></div>
    <div className="library-toolbar"><label className="search-input"><Search size={16} aria-hidden="true" /><input aria-label="搜索文档" placeholder="搜索文档名称、分类或文件名" value={search} onChange={e => { setSearch(e.target.value); setRequestedPage(1); }} /></label>{search && <button className="text-button" onClick={() => { setSearch(''); setRequestedPage(1); }}>清空搜索</button>}</div>
    {(filters.category || filters.status !== 'all') && <div className="active-filters"><span>当前筛选</span>{filters.category && <button onClick={() => onFilters({ ...filters, category: null })} aria-label={`移除分类筛选：${filters.category}`}>{filters.category}<X size={12} /></button>}{filters.status !== 'all' && <button onClick={() => onFilters({ ...filters, status: 'all' })} aria-label="移除状态筛选">{statusLabels[filters.status]}<X size={12} /></button>}<button className="text-button" onClick={() => onFilters({ category: null, status: 'all' })}>重置筛选</button></div>}
    <div className="library-caption"><span>{filters.category ?? '全部文档'} <strong>{filtered.length}</strong></span><span>共 {documents.length} 份资料</span></div>
    <div className="documents-table"><div className="table-heading"><span>文档名称</span><span>格式 / 大小</span><span>状态</span><span /></div>{visible.map(doc => <button className="table-row" key={doc.id} onClick={() => onDocument(doc)}><span className="table-document"><span className="file-icon"><FileText size={21} /></span><span><strong title={doc.title}>{doc.title}</strong><small>{doc.demoUpload ? '交互演示 · 文件未实际解析' : `${doc.category} · ${doc.pages.length} 页 · 制度版本 ${doc.version}`}</small></span></span><span className="file-meta">{doc.filename.split('.').pop()?.toUpperCase()}<small>{fileSize(doc.size)}</small></span><span className={`status-badge ${doc.status === 'ready' ? 'ready' : doc.status === 'failed' ? 'failed' : 'processing'}`}>{doc.status === 'ready' ? <CircleCheck size={13} /> : doc.status === 'failed' ? <CircleAlert size={13} /> : <LoaderCircle size={13} className="spinning" />}{doc.demoUpload && doc.status === 'ready' ? '演示完成' : statusNames[doc.status]}</span><ChevronRight size={16} /></button>)}</div>
    {!filtered.length && <div className="library-empty"><FileSearch size={30} /><h3>没有找到符合条件的文档</h3><p>试试其他关键词，或调整左侧分类与状态。</p><button className="secondary-button" onClick={() => { setSearch(''); onFilters({ category: null, status: 'all' }); setRequestedPage(1); }}>清除全部条件</button></div>}
    <div className="list-pagination"><span>{filtered.length ? `${(currentPage - 1) * pageSize + 1}–${Math.min(currentPage * pageSize, filtered.length)}` : '0'} / {filtered.length} 份</span><div><label><span className="sr-only">每页文档数</span><select aria-label="每页文档数" value={pageSize} onChange={e => { setPageSize(Number(e.target.value)); setRequestedPage(1); }}><option value={10}>10 条 / 页</option><option value={20}>20 条 / 页</option><option value={50}>50 条 / 页</option></select></label><button className="icon-button" aria-label="上一页文档" disabled={currentPage === 1} onClick={() => setRequestedPage(currentPage - 1)}><ChevronLeft size={16} /></button><span>{currentPage} / {pageCount}</span><button className="icon-button" aria-label="下一页文档" disabled={currentPage === pageCount} onClick={() => setRequestedPage(currentPage + 1)}><ChevronRight size={16} /></button></div></div>
    <div className="library-note"><FileSearch size={17} /><span>点击文档查看原文。新上传文件仅演示处理状态。</span></div>
  </div>;
}

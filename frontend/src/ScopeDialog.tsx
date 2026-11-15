import { useEffect, useRef, useState } from 'react';
import { ChevronLeft, ChevronRight, FileText, Search, X } from 'lucide-react';
import type { KnowledgeDocument } from './document-types';

type Props = { open: boolean; documents: KnowledgeDocument[]; selectedIds: string[] | null; onClose: () => void; onApply: (ids: string[] | null) => void };

export default function ScopeDialog({ open, documents, selectedIds, onClose, onApply }: Props) {
  const dialog = useRef<HTMLDialogElement>(null);
  const [mode, setMode] = useState<'all' | 'custom'>('all');
  const [ids, setIds] = useState<string[]>([]);
  const [search, setSearch] = useState('');
  const [category, setCategory] = useState('');
  const [requestedPage, setRequestedPage] = useState(1);
  const available = documents.filter(doc => doc.canQuery);
  useEffect(() => {
    if (open && !dialog.current?.open) {
      setMode(selectedIds === null ? 'all' : 'custom');
      setIds(selectedIds ?? documents.filter(d => d.canQuery).map(d => d.id));
      setSearch(''); setCategory(''); setRequestedPage(1); dialog.current?.showModal();
    } else if (!open) dialog.current?.close();
  }, [open, selectedIds, documents]);
  const selectedAvailableIds = ids.filter(id => available.some(doc => doc.id === id));
  const matches = available.filter(doc => (!category || doc.category === category) && `${doc.title} ${doc.category}`.toLowerCase().includes(search.trim().toLowerCase()));
  const pageCount = Math.max(1, Math.ceil(matches.length / 8));
  const page = Math.min(requestedPage, pageCount);
  return <dialog ref={dialog} className="upload-dialog scope-dialog" aria-labelledby="scope-title" onCancel={onClose} onClick={e => { if (e.target === dialog.current) onClose(); }}>
    <div className="dialog-header"><div><span className="eyebrow">当前会话</span><h2 id="scope-title">问答范围</h2></div><button className="icon-button" aria-label="关闭问答范围" onClick={onClose}><X size={19} /></button></div>
    <p className="dialog-description">默认使用全部知识库，需要时再限定资料。</p>
    <div className="scope-mode"><label className={mode === 'all' ? 'active' : ''}><input type="radio" name="scope-mode" value="all" checked={mode === 'all'} onChange={() => setMode('all')} /><span><strong>全部知识库</strong><small>使用当前可用于问答的全部文档</small></span></label><label className={mode === 'custom' ? 'active' : ''}><input type="radio" name="scope-mode" value="custom" checked={mode === 'custom'} onChange={() => setMode('custom')} /><span><strong>指定文档</strong><small>只从选中的资料中查找答案</small></span></label></div>
    {mode === 'custom' && <>
      <div className="scope-search"><label className="search-input"><Search size={15} /><input aria-label="搜索问答范围文档" placeholder="搜索文档" value={search} onChange={e => { setSearch(e.target.value); setRequestedPage(1); }} /></label><select aria-label="筛选问答范围分类" value={category} onChange={e => { setCategory(e.target.value); setRequestedPage(1); }}><option value="">全部分类</option>{[...new Set(available.map(d => d.category))].map(c => <option key={c}>{c}</option>)}</select></div>
      <div className="scope-selection-summary"><span>已选 {selectedAvailableIds.length} 份</span><button className="text-button" onClick={() => setIds(available.map(d => d.id))}>全选可用文档</button><button className="text-button" onClick={() => setIds([])}>清空</button></div>
      <div className="scope-document-list">{matches.slice((page - 1) * 8, page * 8).map(doc => <label key={doc.id}><input type="checkbox" checked={ids.includes(doc.id)} onChange={e => setIds(previous => e.target.checked ? [...previous, doc.id] : previous.filter(id => id !== doc.id))} /><FileText size={17} /><span><strong>{doc.title}</strong><small>{doc.category}</small></span></label>)}{!matches.length && <p className="empty-note">没有匹配的可用文档</p>}</div>
      <div className="list-pagination"><span>共 {matches.length} 份匹配资料</span><div><button className="icon-button" aria-label="上一页范围文档" disabled={page === 1} onClick={() => setRequestedPage(page - 1)}><ChevronLeft size={16} /></button><span>{page} / {pageCount}</span><button className="icon-button" aria-label="下一页范围文档" disabled={page === pageCount} onClick={() => setRequestedPage(page + 1)}><ChevronRight size={16} /></button></div></div>
    </>}
    <div className="dialog-actions"><button className="secondary-button" onClick={onClose}>取消</button><button className="primary-button" disabled={mode === 'custom' && !selectedAvailableIds.length} onClick={() => { onApply(mode === 'all' ? null : selectedAvailableIds); onClose(); }}>应用范围</button></div>
  </dialog>;
}

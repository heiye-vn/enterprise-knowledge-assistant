import { useState } from 'react';
import { CircleCheck, Clock3, FileText, FolderClosed, GitBranch, Layers3, MessageSquare, Network, Plus, Search, X } from 'lucide-react';
import type { KnowledgeDocument } from './demo';
import { graphScenarios, sidebarLabels } from './workspace';
import { graphKinds as kindOptions } from './graph-data';
import type { Conversation, DocumentFilters, DocumentStatusFilter, GraphNodeKind, GraphScenario, View } from './workspace';

type Props = {
  view: View; open: boolean; onClose: () => void;
  conversations: Conversation[]; activeConversationId: string; onNewChat: () => void; onConversation: (id: string) => void;
  documents: KnowledgeDocument[]; filters: DocumentFilters; onFilters: (filters: DocumentFilters) => void;
  graphScenario: GraphScenario; onGraphScenario: (id: GraphScenario) => void;
  graphSearch: string; onGraphSearch: (query: string) => void;
  graphKinds: GraphNodeKind[]; onGraphKinds: (kinds: GraphNodeKind[]) => void;
};

export default function WorkspaceSidebar(props: Props) {
  const [historySearch, setHistorySearch] = useState('');
  const [categorySearch, setCategorySearch] = useState('');
  const { view, documents, filters, onFilters } = props;
  const categories = [...new Set(documents.map(doc => doc.category))];
  const categoryDocuments = documents.filter(doc => !filters.category || doc.category === filters.category);
  const histories = props.conversations.filter(c => `${c.title} ${c.messages.filter(m => m.role === 'user').map(m => m.text).join(' ')}`.toLowerCase().includes(historySearch.trim().toLowerCase())).sort((a, b) => b.updatedAt - a.updatedAt);
  const statusOptions: { id: DocumentStatusFilter; label: string; count: number }[] = [
    { id: 'all', label: '全部状态', count: categoryDocuments.length },
    { id: 'ready', label: '处理完成', count: categoryDocuments.filter(d => d.status === 'ready').length },
    { id: 'processing', label: '处理中', count: categoryDocuments.filter(d => !['ready', 'failed'].includes(d.status)).length },
    { id: 'failed', label: '处理失败', count: categoryDocuments.filter(d => d.status === 'failed').length },
  ];
  const scenario = graphScenarios.find(s => s.id === props.graphScenario)!;
  const matchCount = scenario.graph.nodes.filter(s => props.graphKinds.includes(s.kind) && `${s.title} ${s.detail}`.toLowerCase().includes(props.graphSearch.trim().toLowerCase())).length;

  return <aside className={`sidebar contextual-sidebar ${props.open ? 'mobile-open' : ''}`} aria-label={sidebarLabels[view]}>
    <div className="space-label">
      <span className="eyebrow">KNOWLEDGE SPACE</span>
      <h2>企业制度知识库</h2><p>云岚科技 · 示例制度</p>
      <button className="icon-button sidebar-close" aria-label="关闭侧栏" onClick={props.onClose}><X size={18} /></button>
    </div>

    {view === 'chat' && <>
      <button className="primary-button new-chat" onClick={() => { setHistorySearch(''); props.onNewChat(); }}><Plus size={18} />新建会话</button>
      <label className="search-input"><Search size={15} aria-hidden="true" /><input placeholder="搜索历史会话" aria-label="搜索历史会话" value={historySearch} onChange={e => setHistorySearch(e.target.value)} /></label>
      <div className="sidebar-section-title"><span>历史会话 <small>{props.conversations.length}</small></span><Clock3 size={14} /></div>
      <div className="sidebar-scroll history-list">
        {histories.map(conversation => <button key={conversation.id} className={`history-item ${conversation.id === props.activeConversationId ? 'active' : ''}`} aria-current={conversation.id === props.activeConversationId ? 'true' : undefined} title={conversation.title} onClick={() => props.onConversation(conversation.id)}><MessageSquare size={16} aria-hidden="true" /><span>{conversation.title}</span></button>)}
        {!histories.length && <p className="empty-note">没有匹配的会话</p>}
      </div>
      <div className="sidebar-context-note"><MessageSquare size={17} /><p>从问题开始，沿着引用核对答案。<span>会话记录仅保留在本次页面中。</span></p></div>
    </>}

    {view === 'documents' && <>
      <div className="sidebar-page-heading"><FolderClosed size={18} /><h3>文档目录</h3></div>
      <button className={`sidebar-filter ${filters.category === null ? 'active' : ''}`} aria-pressed={filters.category === null} onClick={() => onFilters({ ...filters, category: null })}><Layers3 size={16} aria-hidden="true" /><span>全部文档</span><small>{documents.length}</small></button>
      <div className="sidebar-section-title"><span>文档分类</span></div>
      <label className="search-input"><Search size={15} aria-hidden="true" /><input aria-label="搜索文档分类" placeholder="查找分类" value={categorySearch} onChange={e => setCategorySearch(e.target.value)} /></label>
      <div className="sidebar-scroll category-list">
        {categories.filter(category => category.toLowerCase().includes(categorySearch.trim().toLowerCase())).map(category => <button key={category} className={`sidebar-filter ${filters.category === category ? 'active' : ''}`} aria-pressed={filters.category === category} onClick={() => onFilters({ ...filters, category })}><FolderClosed size={16} aria-hidden="true" /><span>{category}</span><small>{documents.filter(d => d.category === category).length}</small></button>)}
        {!categories.some(c => c.toLowerCase().includes(categorySearch.trim().toLowerCase())) && <p className="empty-note">没有匹配的分类</p>}
      </div>
      <div className="sidebar-divider" />
      <div className="sidebar-section-title"><span>处理状态</span></div>
      <div className="status-filters">{statusOptions.map(option => <button key={option.id} className={`sidebar-filter ${filters.status === option.id ? 'active' : ''}`} aria-pressed={filters.status === option.id} onClick={() => onFilters({ ...filters, status: option.id })}><span className={`filter-status-dot ${option.id}`} /><span>{option.label}</span><small>{option.count}</small></button>)}</div>
      <div className="sidebar-context-note"><FileText size={17} /><p>按分类与状态定位资料。<span>搜索、上传与原文查看在右侧进行。</span></p></div>
    </>}

    {view === 'graph' && <>
      <div className="sidebar-page-heading"><Network size={18} /><h3>图谱探索</h3></div>
      <label className="search-input"><Search size={15} aria-hidden="true" /><input aria-label="搜索图谱节点" placeholder="搜索当前图谱节点" value={props.graphSearch} onChange={e => props.onGraphSearch(e.target.value)} /></label>
      <div className="sidebar-section-title"><span>关联场景</span><small>示例</small></div>
      <div className="sidebar-scroll scenario-list">{graphScenarios.map(s => <button key={s.id} className={`scenario-item ${s.id === props.graphScenario ? 'active' : ''}`} aria-pressed={s.id === props.graphScenario} onClick={() => props.onGraphScenario(s.id)}><GitBranch size={17} aria-hidden="true" /><span><strong>{s.title}</strong><small>{s.description}</small></span>{s.id === props.graphScenario && <CircleCheck size={15} aria-hidden="true" />}</button>)}</div>
      <div className="sidebar-divider" />
      <div className="sidebar-section-title"><span>节点类型</span></div>
      <div className="graph-kind-filters">{kindOptions.map(kind => <label key={kind.id}><input type="checkbox" checked={props.graphKinds.includes(kind.id)} onChange={e => props.onGraphKinds(e.target.checked ? [...props.graphKinds, kind.id] : props.graphKinds.filter(k => k !== kind.id))} /><span className="graph-kind-dot" style={{ backgroundColor: kind.color }} /><span>{kind.label}</span><small>{scenario.graph.nodes.filter(s => s.kind === kind.id).length}</small></label>)}</div>
      <p className="graph-match-count" role="status">{props.graphSearch.trim() ? '匹配' : '当前主题共'} {matchCount} 个节点</p>
      <button className="text-button graph-reset" onClick={() => { props.onGraphSearch(''); props.onGraphKinds(kindOptions.map(kind => kind.id)); }}>重置节点筛选</button>
      <div className="sidebar-context-note"><Network size={17} /><p>从关联关系追溯制度依据。<span>选中节点后可逐层展开关联，并核对来源条款。</span></p></div>
    </>}
  </aside>;
}

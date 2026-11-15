import {useState} from 'react';
import {BookOpen,Clock3,FileText,FolderClosed,MessageSquare,Plus,Search,Trash2,X} from 'lucide-react';
import {isProcessing} from './document-types';
import type {KnowledgeDocument} from './document-types';
import type {Conversation,DocumentFilters,DocumentStatusFilter,View} from './workspace';
import {sidebarLabels} from './workspace';

type Props={view:View;open:boolean;onClose:()=>void;conversations:Conversation[];activeConversationId:string;onNewChat:()=>void;onConversation:(id:string)=>void;onDeleteConversation:(id:string,title:string)=>void;documents:KnowledgeDocument[];filters:DocumentFilters;onFilters:(filters:DocumentFilters)=>void};
export default function WorkspaceSidebar({view,open,onClose,conversations,activeConversationId,onNewChat,onConversation,onDeleteConversation,documents,filters,onFilters}:Props){
  const [search,setSearch]=useState('');
  const statuses:{id:DocumentStatusFilter;label:string;count:number}[]=[
    {id:'all',label:'全部文档',count:documents.length},
    {id:'ready',label:'可检索',count:documents.filter(d=>d.canQuery).length},
    {id:'processing',label:'处理中',count:documents.filter(isProcessing).length},
    {id:'failed',label:'处理失败',count:documents.filter(d=>d.status==='failed').length},
  ];
  return <aside className={`sidebar contextual-sidebar ${open?'mobile-open':''}`} aria-label={sidebarLabels[view]}><div className="space-label"><span className="eyebrow">KNOWLEDGE SPACE</span><h2>企业知识库</h2><p>对话与知识问答</p><button className="icon-button sidebar-close" aria-label="关闭侧栏" onClick={onClose}><X size={18}/></button></div>
    {view==='chat'?<><button className="primary-button new-chat" onClick={onNewChat}><Plus size={18}/>新建会话</button><label className="search-input"><Search size={15}/><input aria-label="搜索历史会话" placeholder="搜索历史会话" value={search} onChange={e=>setSearch(e.target.value)}/></label><div className="sidebar-section-title"><span>历史会话 <small>{conversations.length}</small></span><Clock3 size={14}/></div><div className="sidebar-scroll history-list">{conversations.filter(c=>c.title.toLowerCase().includes(search.toLowerCase())).map(c=><div className={`history-entry ${c.id===activeConversationId?'active':''}`} key={c.id} data-session-id={c.id}><button className={`history-item ${c.id===activeConversationId?'active':''}`} aria-current={c.id===activeConversationId?'true':undefined} onClick={()=>onConversation(c.id)}><MessageSquare size={16}/><span>{c.title}</span></button><button className="icon-button history-delete" title="删除会话" aria-label={`删除会话：${c.title}`} onClick={()=>onDeleteConversation(c.id,c.title)}><Trash2 size={15}/></button></div>)}{!conversations.length && <p className="empty-note">还没有会话，直接在右侧提问即可。</p>}</div><div className="sidebar-context-note"><BookOpen size={17}/><p>通用问题可以直接对话。<span>企业制度找不到依据时明确说明。</span></p></div></>:<><div className="sidebar-page-heading"><FolderClosed size={18}/><h3>知识文档</h3></div><div className="status-filters">{statuses.map(s=><button key={s.id} className={`sidebar-filter ${s.id===filters.status?'active':''}`} aria-pressed={s.id===filters.status} onClick={()=>onFilters({category:null,status:s.id})}><span className={`filter-status-dot ${s.id}`}/><span>{s.label}</span><small>{s.count}</small></button>)}</div><div className="sidebar-context-note"><FileText size={17}/><p>上传后自动处理。<span>就绪后即可在问答中引用。</span></p></div></>}
  </aside>;
}

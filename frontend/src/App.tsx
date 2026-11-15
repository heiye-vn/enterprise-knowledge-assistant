import {lazy,Suspense,useCallback,useEffect,useRef,useState} from 'react';
import {BookOpen,ChevronLeft,ChevronRight,CircleAlert,CircleCheck,Info,ExternalLink,FileSearch,FileText,FolderClosed,Menu,MessageSquare,Network,PanelRightClose,PanelRightOpen,X} from 'lucide-react';
import WorkspaceSidebar from './WorkspaceSidebar';
import DocumentsPanel from './DocumentsPanel';
import ChatPanel from './ChatPanel';
import UploadDialog from './UploadDialog';
import TextOriginal from './TextOriginal';
import ImageOriginal from './ImageOriginal';
import IndexedChunks from './IndexedChunks';
import ParsedView from './ParsedView';
import {useParsedVersion} from './useParsedVersion';
import {deleteChatSession,deleteDocument,listChatSessions,listDocuments,retryJob} from './api';
import {isProcessing,statusNames} from './document-types';
import type {ChunkSource,ImportAccepted,KnowledgeDocument} from './document-types';
import {sidebarLabels} from './workspace';
import type {Conversation,DocumentFilters,View} from './workspace';

const PdfView=lazy(()=>import('./PdfView'));
const DocxOriginal=lazy(()=>import('./DocxOriginal'));
const GraphPanel=lazy(()=>import('./GraphPanel'));
type SourceTab='passage'|'original'|'indexed';
export default function App(){
  const [view,setView]=useState<View>('chat');
  const [documents,setDocuments]=useState<KnowledgeDocument[]>([]);
  const [loading,setLoading]=useState(true);
  const [loadError,setLoadError]=useState('');
  const [conversations,setConversations]=useState<Conversation[]>([]);
  const [activeConversationId,setActiveConversationId]=useState('');
  const [documentFilters,setDocumentFilters]=useState<DocumentFilters>({category:null,status:'all'});
  const [sourceOpen,setSourceOpen]=useState(false);
  const [documentId,setDocumentId]=useState('');
  const [sourceTab,setSourceTab]=useState<SourceTab>('passage');
  const [readerSource,setReaderSource]=useState<ChunkSource | null>(null);
  const [focusBlockId,setFocusBlockId]=useState<string | null>(null);
  const [readerRevision,setReaderRevision]=useState(0);
  const [page,setPage]=useState(1);
  const [pdfPageCount,setPdfPageCount]=useState<number | null>(null);
  const [uploadOpen,setUploadOpen]=useState(false);
  const [sidebarOpen,setSidebarOpen]=useState(false);
  const [chatBusy,setChatBusy]=useState(false);
  const [notice,setNotice]=useState<{message:string;tone:'success'|'error'|'info'} | null>(null);
  const toast=notice?.message ?? '';
  function setToast(message:string,tone:'success'|'error'|'info'='info'){setNotice(message?{message,tone}:null);}
  const [retrying,setRetrying]=useState(false);
  const loadGeneration=useRef(0);
  const conversationGeneration=useRef(0);
  const deleteDialog=useRef<HTMLDialogElement>(null);
  const [deleteTarget,setDeleteTarget]=useState<{id:string;title:string} | null>(null);
  const [deleting,setDeleting]=useState(false);
  const currentDoc=documents.find(d=>d.id===documentId);
  const fileUrl=readerSource?.file_url ?? currentDoc?.fileUrl;
  const format=readerSource?.format ?? currentDoc?.format ?? '';
  const formatLabel=format==='md'?'Markdown':format.toUpperCase();
  const selectedVersionId=sourceOpen?readerSource?.version_id ?? currentDoc?.versionId ?? null:null;
  const parsed=useParsedVersion(selectedVersionId,readerRevision,readerSource?.job_id);
  const latest=parsed.data?.latest_processing;
  const selectedStatus=latest?.display_status ?? currentDoc?.status;
  const processingSelected=['queued','running'].includes(latest?.status ?? '');
  const refreshDocuments=useCallback(async(signal?:AbortSignal)=>{
    const generation=++loadGeneration.current;
    try{const values=await listDocuments(signal);if(generation===loadGeneration.current && !signal?.aborted){setDocuments(values);setLoadError('');}return values;}
    catch{if(generation===loadGeneration.current && !signal?.aborted)setLoadError('文档列表暂时无法读取，请重试。');return [];}
    finally{if(generation===loadGeneration.current && !signal?.aborted)setLoading(false);}
  },[]);
  const refreshConversations=useCallback(async(signal?:AbortSignal)=>{
    const generation=++conversationGeneration.current;
    try{const values=await listChatSessions(signal);if(!signal?.aborted && generation===conversationGeneration.current)setConversations(values.map(v=>({id:v.id,title:v.title,messages:[],documentIds:null,updatedAt:Date.parse(v.updated_at)})));}
    catch{if(!signal?.aborted)setToast('会话列表暂时无法读取，请稍后重试。','error');}
  },[]);
  useEffect(()=>{
    const controller=new AbortController();let timer:ReturnType<typeof setTimeout>;
    async function refresh(){const items=await refreshDocuments(controller.signal);if(!controller.signal.aborted)timer=setTimeout(refresh,items.some(isProcessing)?2000:10000);}
    void refresh();void refreshConversations(controller.signal);
    return ()=>{controller.abort();clearTimeout(timer);};
  },[refreshDocuments,refreshConversations]);
  useEffect(()=>{if(deleteTarget)deleteDialog.current?.showModal();else deleteDialog.current?.close();},[deleteTarget]);
  useEffect(()=>{if(!toast)return;const timer=setTimeout(()=>setToast(''),4000);return ()=>clearTimeout(timer);},[notice]);
  useEffect(()=>{setPage(readerSource?.page_start ?? 1);setPdfPageCount(null);},[fileUrl,readerSource?.page_start]);
  function changeView(next:View){setView(next);setSidebarOpen(false);setSourceOpen(false);}
  function openDocument(doc:KnowledgeDocument){setDocumentId(doc.id);setReaderSource(null);setFocusBlockId(null);setSourceTab('passage');setSourceOpen(true);setSidebarOpen(false);setReaderRevision(n=>n+1);}
  function openSource(source:ChunkSource,tab:'passage'|'indexed'='passage'){setDocumentId(source.document_id);setReaderSource(source);setFocusBlockId(source.locators[0]?.block_id ?? null);setSourceTab(tab);setSourceOpen(true);setSidebarOpen(false);setReaderRevision(n=>n+1);}
  async function imported(values:ImportAccepted[]){await refreshDocuments();setToast(values.some(v=>!v.duplicate)?'文档已上传，正在自动处理。':'文档已存在，已跳过重复上传。','success');}
  async function removeDocument(doc:KnowledgeDocument){
    await deleteDocument(doc.id);
    setDocuments(previous=>previous.filter(item=>item.id!==doc.id));
    if(documentId===doc.id)setSourceOpen(false);
    await refreshDocuments();
    setToast('文档已删除，后续问答不再检索该文档。','success');
  }
  async function retryProcessing(){if(!latest || retrying)return;setRetrying(true);try{await retryJob(latest.job_id);parsed.refresh();await refreshDocuments();setToast('已重新加入处理队列。','success');}catch(error){setToast(error instanceof Error?error.message:'暂时无法重试。','error');}finally{setRetrying(false);}}
  async function createConversation():Promise<string>{
    const identity=crypto.randomUUID();setActiveConversationId(identity);return identity;
  }
  function newChat(){
    if(chatBusy){setToast('请等待当前回答完成。');return;}
    if(!activeConversationId && view==='chat'){setToast('已经是新会话');return;}
    setActiveConversationId('');changeView('chat');
  }
  async function confirmDeleteConversation(){
    if(!deleteTarget || deleting)return;
    const identity=deleteTarget.id;setDeleting(true);
    try{
      await deleteChatSession(identity);++conversationGeneration.current;
      setConversations(previous=>previous.filter(c=>c.id!==identity));
      if(activeConversationId===identity){setActiveConversationId('');setSourceOpen(false);}
      setDeleteTarget(null);setToast('会话已删除','success');
    }catch(error){setToast(error instanceof Error?error.message:'暂时无法删除会话。','error');}
    finally{setDeleting(false);}
  }
  return <div className="app-shell"><header className="topbar"><div className="brand"><span className="brand-mark"><BookOpen size={21}/></span><span>企业知识助理<small>让知识有据可循</small></span></div><nav className="main-nav" aria-label="主要导航">{([['chat',MessageSquare,'问答工作台'],['documents',FolderClosed,'文档管理'],['graph',Network,'知识图谱']] as const).map(([id,Icon,name])=><button key={id} aria-label={name} className={view===id?'active':''} aria-current={view===id?'page':undefined} onClick={()=>changeView(id)}><Icon size={17}/><span>{name}</span></button>)}</nav><div className="topbar-right"><span className="workspace-label"><span className="green-dot"/>本地工作空间</span></div></header>
    <div className="workspace">{sidebarOpen && <button className="mobile-scrim sidebar-scrim" aria-label="收起侧栏" onClick={()=>setSidebarOpen(false)}/>}
      {view!=='graph'&&<WorkspaceSidebar view={view} open={sidebarOpen} onClose={()=>setSidebarOpen(false)} conversations={conversations} activeConversationId={activeConversationId} onDeleteConversation={(id,title)=>setDeleteTarget({id,title})} onNewChat={()=>{void newChat();}} onConversation={id=>{if(chatBusy){setToast('请等待当前回答完成。');return;}setActiveConversationId(id);changeView('chat');}} documents={documents} filters={documentFilters} onFilters={setDocumentFilters}/>}
      <main className={`main-panel ${view==='chat'?'chat-view':view==='graph'?'graph-main-panel':''}`}><div className="workspace-header"><div className="workspace-title"><button className="icon-button mobile-menu" aria-label={`打开${sidebarLabels[view]}`} onClick={()=>setSidebarOpen(true)}><Menu size={20}/></button><div><h1>{view==='chat'?'对话工作台':view==='graph'?'知识图谱':'知识文档'}</h1><p>{view==='chat'?'通用问题直接聊，企业制度有据可查。':view==='graph'?'查看制度关联，核对适用条件与原文依据。':'上传后自动处理，就绪后即可问答。'}</p></div></div>{(currentDoc || readerSource) && <button className="icon-button" aria-label={sourceOpen?'收起原文面板':'打开原文面板'} onClick={()=>setSourceOpen(!sourceOpen)}>{sourceOpen?<PanelRightClose size={19}/>:<PanelRightOpen size={19}/>}</button>}</div>
        {view==='graph'?<Suspense fallback={<p className="empty-note">正在加载知识图谱…</p>}><GraphPanel documents={documents} onSource={openSource}/></Suspense>:view==='documents'?<DocumentsPanel onDelete={removeDocument} documents={documents} filters={documentFilters} onDocument={openDocument} onUpload={()=>setUploadOpen(true)} loading={loading} error={loadError} onReload={()=>{setLoading(true);void refreshDocuments();}}/>:<ChatPanel sessionId={activeConversationId} ensureSession={createConversation} onUpdated={()=>{void refreshConversations();}} onSource={openSource} onUpload={()=>setUploadOpen(true)} onBusy={setChatBusy}/>}
      </main>
      {sourceOpen && (currentDoc || readerSource) && <><button className="mobile-scrim source-scrim" aria-label="关闭原文面板" onClick={()=>setSourceOpen(false)}/><aside className="source-panel" aria-label="原文溯源"><div className="source-header"><span><FileSearch size={17}/><strong>原文溯源</strong></span><button className="icon-button" aria-label="关闭原文" onClick={()=>setSourceOpen(false)}><X size={17}/></button></div><div className="source-document"><span className="file-icon"><FileText size={23}/></span><div><strong>{readerSource?.document_title ?? currentDoc?.title}</strong><span>{formatLabel}{readerSource?.page_start!==null && readerSource?.page_start!==undefined?` · 第 ${readerSource.page_start} 页`:''}</span></div>{fileUrl && <a className="icon-button" aria-label="在新窗口打开原件" title="在新窗口打开原件" href={fileUrl} target="_blank" rel="noreferrer"><ExternalLink size={17}/></a>}</div>
        <div className="processing-details" role="status"><strong>{parsed.data?.document_removed?'已从知识库移除':selectedStatus?statusNames[selectedStatus]:'正在读取文档…'}</strong><p>{parsed.data?.document_removed?'当前展示历史回答引用的原文。':latest?.error?.message ?? (processingSelected?'文档正在自动处理，稍后即可用于问答。':'点击回答中的来源，可核对对应正文与原件。')}</p>{latest?.status==='failed' && latest.error?.retryable && latest.attempt_no<latest.max_attempts && <button className="secondary-button" disabled={retrying} onClick={()=>{void retryProcessing();}}>{retrying?'正在重试…':'重试处理'}</button>}</div>
        <div className="source-tabs" role="tablist" aria-label="文档展示方式">{([['passage','文档正文'],['original','文档原件'],['indexed','文档切块']] as const).map(([id,label])=><button key={id} role="tab" aria-selected={sourceTab===id} onClick={()=>setSourceTab(id)}>{label}</button>)}</div>
        <div className="source-scroll">{sourceTab==='indexed' && selectedVersionId?<IndexedChunks key={`${selectedVersionId}:${readerSource?.job_id ?? ''}`} versionId={selectedVersionId} jobId={readerSource?.job_id ?? null} revision={readerRevision+(latest?.status==='ready'?1:0)} focusId={readerSource?.id ?? null} focusOrdinal={readerSource?.ordinal ?? 0} onBlock={(id,source)=>{setReaderSource(source);setFocusBlockId(id);setSourceTab('passage');}} onPage={(value,source)=>{setReaderSource(source);setPage(value);setSourceTab('original');}}/>:sourceTab==='passage'?<ParsedView result={parsed.data?.result ?? null} loading={!parsed.data && !parsed.error} error={parsed.error} blocks={false} focusBlockId={focusBlockId} onPage={value=>{setPage(value);setSourceTab('original');}} onReload={parsed.refresh}/>:!fileUrl?<p className="empty-note">文档原件暂不可用。</p>:format==='pdf'?<Suspense fallback={<p className="empty-note">正在加载 PDF 阅读器…</p>}><PdfView key={fileUrl} url={fileUrl} page={page} onPageCount={setPdfPageCount}/></Suspense>:format==='md'?<TextOriginal key={fileUrl} url={fileUrl}/>:format==='docx'?<Suspense fallback={<p className="empty-note">正在加载 Word 阅读器…</p>}><DocxOriginal key={fileUrl} url={fileUrl}/></Suspense>:['png','jpg'].includes(format)?<ImageOriginal key={fileUrl} url={fileUrl} title={readerSource?.document_title??currentDoc?.title??'文档'}/>:<div className="source-empty"><FileText size={29}/><h3>{formatLabel} 原件</h3><p>可在“文档正文”查看内容，或使用右上角按钮打开原件。</p></div>}</div>
        {sourceTab==='original' && format==='pdf' && pdfPageCount!==null && <div className="page-controls"><span>文档原件</span><div><button className="icon-button" aria-label="上一页" disabled={page<=1} onClick={()=>setPage(p=>p-1)}><ChevronLeft size={15}/></button><span>{page} <small>/ {pdfPageCount}</small></span><button className="icon-button" aria-label="下一页" disabled={page>=pdfPageCount} onClick={()=>setPage(p=>p+1)}><ChevronRight size={15}/></button></div></div>}</aside></>}
    </div><dialog ref={deleteDialog} className="upload-dialog delete-chat-dialog" aria-labelledby="delete-chat-title" onCancel={event=>{event.preventDefault();if(!deleting)setDeleteTarget(null);}}><div className="dialog-header"><h2 id="delete-chat-title">删除会话</h2><button className="icon-button" aria-label="关闭删除会话" disabled={deleting} onClick={()=>setDeleteTarget(null)}><X size={18}/></button></div><p className="dialog-description">确定删除“{deleteTarget?.title}”吗？删除后将从历史记录中移除。</p><div className="dialog-actions"><button className="secondary-button" disabled={deleting} onClick={()=>setDeleteTarget(null)}>取消</button><button className="primary-button danger-button" disabled={deleting} onClick={()=>{void confirmDeleteConversation();}}>{deleting?'正在删除…':'删除'}</button></div></dialog><UploadDialog open={uploadOpen} documents={documents} onClose={()=>setUploadOpen(false)} onImported={imported} onViewDocument={openDocument}/>{toast && <div className={`toast toast-${notice?.tone}`} role={notice?.tone==='error'?'alert':'status'}>{notice?.tone==='error'?<CircleAlert size={18}/>:notice?.tone==='success'?<CircleCheck size={18}/>:<Info size={18}/>}<span>{toast}</span><button className="icon-button" aria-label="关闭提示" onClick={()=>setToast('')}><X size={15}/></button></div>}
  </div>;
}

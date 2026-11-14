import { lazy, Suspense, useEffect, useRef, useState } from 'react';
import type { FormEvent, ReactNode } from 'react';
import {
  ArrowDownToLine, ArrowRight, ArrowUp, BookOpen, Check, CheckCheck,
  ChevronDown, ChevronLeft, ChevronRight, CircleCheck, Copy, FileSearch, FileText,
  FolderClosed, Layers3, Link2, LoaderCircle, Menu, MessageSquare, Network,
  PanelRightClose, PanelRightOpen, ShieldCheck, Sparkles, Square, Upload, X,
} from 'lucide-react';
import {
  fileSize, getDemoAnswer, initialDocuments, initialMessages, openingQuestion,
  sources, suggestedQuestions,
} from './demo';
import type { Answer, ImportStatus, KnowledgeDocument, Message } from './demo';
import WorkspaceSidebar from './WorkspaceSidebar';
import DocumentsPanel from './DocumentsPanel';
import ScopeDialog from './ScopeDialog';
import { sidebarLabels } from './workspace';
import type { Conversation, DocumentFilters, GraphNodeKind, GraphScenario, View } from './workspace';

const PdfView = lazy(() => import('./PdfView'));
const GraphPanel = lazy(() => import('./GraphPanel'));
type SourceTab = 'passage' | 'pdf' | 'chunks';

const initialConversations: Conversation[] = [
  { id: 'leave-demo', title: '请假审批与制度依据', messages: initialMessages, documentIds: null, updatedAt: Date.now() },
  { id: 'invoice-demo', title: '电子发票与报销要求', messages: [
    { id: 'invoice-question', role: 'user', text: '电子发票截图可以报销吗？' },
    { id: 'invoice-answer', role: 'assistant', answer: getDemoAnswer('电子发票截图可以报销吗？', []) },
  ], documentIds: null, updatedAt: Date.now() - 1 },
];

function IconButton({ label, children, onClick, className = '' }: { label: string; children: ReactNode; onClick: () => void; className?: string }) {
  return <button type="button" className={`icon-button ${className}`} title={label} aria-label={label} onClick={onClick}>{children}</button>;
}

function UploadDialog({ open, onClose, onUpload }: { open: boolean; onClose: () => void; onUpload: (files: File[]) => void }) {
  const dialog = useRef<HTMLDialogElement>(null);
  const input = useRef<HTMLInputElement>(null);
  const [files, setFiles] = useState<File[]>([]);
  const [error, setError] = useState('');
  const [dragging, setDragging] = useState(false);
  useEffect(() => {
    if (open) { setFiles([]); setError(''); dialog.current?.showModal(); }
    else dialog.current?.close();
  }, [open]);
  function choose(list: File[]) {
    const invalid = list.find(f => !/\.(pdf|docx|md)$/i.test(f.name) || f.size === 0 || f.size > 20 * 1024 * 1024);
    if (invalid) { setError(`“${invalid.name}”不符合要求，请选择非空且不超过 20 MB 的 PDF、DOCX 或 MD。`); return; }
    setError(''); setFiles(list);
  }
  return <dialog ref={dialog} className="upload-dialog" aria-labelledby="upload-title" onCancel={onClose} onClick={e => { if (e.target === dialog.current) onClose(); }}>
    <div className="dialog-header"><div><span className="eyebrow">知识库 / 文档导入</span><h2 id="upload-title">添加知识文档</h2></div><IconButton label="关闭上传弹窗" onClick={onClose}><X size={19} /></IconButton></div>
    <p className="dialog-description">将制度放在一起，让每次提问都有据可依。</p>
    <button type="button" className={`dropzone ${dragging ? 'dragging' : ''}`} onClick={() => input.current?.click()}
      onDragOver={e => { e.preventDefault(); setDragging(true); }} onDragLeave={() => setDragging(false)}
      onDrop={e => { e.preventDefault(); setDragging(false); choose(Array.from(e.dataTransfer.files)); }}>
      <span className="upload-glyph"><Upload size={25} /></span><strong>{files.length ? `已选择 ${files.length} 个文件` : '点击选择，或将文档拖到这里'}</strong><span>PDF、DOCX、Markdown · 单个文件最大 20 MB</span>
    </button>
    <input ref={input} className="sr-only" aria-label="选择知识文档" type="file" multiple accept=".pdf,.docx,.md" onChange={e => choose(Array.from(e.target.files ?? []))} />
    {files.length > 0 && <div className="selected-files">{files.map((file, i) => <div key={`${file.name}-${i}`}><FileText size={17} /><span>{file.name}</span><small>{fileSize(file.size)}</small></div>)}</div>}
    {error && <p role="alert" className="form-error">{error}</p>}
    <div className="demo-notice"><ShieldCheck size={18} /><p>交互演示：只展示处理状态，文件不会上传服务器，也不会参与真实检索。</p></div>
    <div className="dialog-actions"><button className="secondary-button" onClick={onClose}>取消</button><button className="primary-button" disabled={!files.length} onClick={() => { onUpload(files); onClose(); }}><Upload size={16} />开始导入演示</button></div>
  </dialog>;
}

function CitationText({ text, answer, onSource }: { text: string; answer: Answer; onSource: (id: string) => void }) {
  return <>{text.split(/(\[[a-z]+\])/g).map((part, i) => {
    const id = part.match(/^\[([a-z]+)\]$/)?.[1];
    const source = id ? sources[id] : undefined;
    return source && id ? <button key={i} className="inline-citation" title={`查看${source.clause}`} aria-label={`查看来源 ${answer.sources.indexOf(id) + 1}：${source.clause}`} onClick={() => onSource(id)}>{answer.sources.indexOf(id) + 1}</button> : <span key={i}>{part}</span>;
  })}</>;
}

export default function App() {
  const [view, setView] = useState<View>('chat');
  const [documents, setDocuments] = useState(initialDocuments);
  const [conversations, setConversations] = useState(initialConversations);
  const [activeConversationId, setActiveConversationId] = useState('leave-demo');
  const [question, setQuestion] = useState('');
  const [documentFilters, setDocumentFilters] = useState<DocumentFilters>({ category: null, status: 'all' });
  const [graphScenario, setGraphScenario] = useState<GraphScenario>('leave');
  const [graphSearch, setGraphSearch] = useState('');
  const [graphKinds, setGraphKinds] = useState<GraphNodeKind[]>(['document', 'matter', 'rule', 'role', 'material']);
  const [scopeOpen, setScopeOpen] = useState(false);
  const [sourceOpen, setSourceOpen] = useState(() => window.innerWidth >= 1180);
  const [activeSource, setActiveSource] = useState<string | null>('leave');
  const [documentId, setDocumentId] = useState('hr');
  const [sourceTab, setSourceTab] = useState<SourceTab>('passage');
  const [page, setPage] = useState(sources.leave.page);
  const [uploadOpen, setUploadOpen] = useState(false);
  const [sidebarOpen, setSidebarOpen] = useState(false);
  const [responding, setResponding] = useState(false);
  const [toast, setToast] = useState('');
  const [copied, setCopied] = useState<string | null>(null);
  const replyTimer = useRef<ReturnType<typeof setTimeout> | null>(null);
  const chatBody = useRef<HTMLDivElement>(null);
  const composer = useRef<HTMLTextAreaElement>(null);
  const activeView = useRef<View>('chat');
  const conversation = conversations.find(c => c.id === activeConversationId)!;
  const messages = conversation.messages;
  const selectedDocs = conversation.documentIds ?? documents.filter(d => d.status === 'ready' && !d.demoUpload).map(d => d.id);
  const pending = documents.some(d => !['ready', 'failed'].includes(d.status));
  const currentDoc = documents.find(d => d.id === documentId) ?? documents[0];
  const currentSource = activeSource ? sources[activeSource] : undefined;

  useEffect(() => {
    if (!pending) return;
    const steps: ImportStatus[] = ['queued', 'parsing', 'chunking', 'embedding', 'ready'];
    const timer = setInterval(() => setDocuments(docs => docs.map(doc => {
      const index = steps.indexOf(doc.status);
      return doc.demoUpload && index >= 0 && index < steps.length - 1 ? { ...doc, status: steps[index + 1] } : doc;
    })), 1400);
    return () => clearInterval(timer);
  }, [pending]);
  useEffect(() => {
    if (!toast) return;
    const timer = setTimeout(() => setToast(''), 3200); return () => clearTimeout(timer);
  }, [toast]);
  useEffect(() => {
    chatBody.current?.scrollTo({ top: chatBody.current.scrollHeight, behavior: 'smooth' });
  }, [messages, responding]);
  useEffect(() => () => { if (replyTimer.current) clearTimeout(replyTimer.current); }, []);
  useEffect(() => {
    function escape(e: KeyboardEvent) { if (e.key === 'Escape') { setSidebarOpen(false); if (window.innerWidth < 1180) setSourceOpen(false); } }
    window.addEventListener('keydown', escape); return () => window.removeEventListener('keydown', escape);
  }, []);

  function openSource(id: string) {
    const source = sources[id];
    if (!source) return;
    setActiveSource(id); setDocumentId(source.documentId); setPage(source.page); setSourceTab('passage'); setSourceOpen(true); setSidebarOpen(false);
  }
  function openDocument(doc: KnowledgeDocument) {
    setDocumentId(doc.id); setActiveSource(null); setPage(1); setSourceTab('passage'); setSourceOpen(true); setSidebarOpen(false);
  }
  function setMessages(update: Message[] | ((previous: Message[]) => Message[])) {
    setConversations(previous => previous.map(c => {
      if (c.id !== activeConversationId) return c;
      const next = typeof update === 'function' ? update(c.messages) : update;
      return { ...c, messages: next, title: next.find(m => m.role === 'user')?.text ?? '新会话', updatedAt: Date.now() };
    }));
  }
  function switchView(next: View) {
    if (next !== view) setSourceOpen(false);
    setView(next); activeView.current = next; setSidebarOpen(false);
  }
  function selectConversation(id: string) {
    if (id === activeConversationId) { setSidebarOpen(false); return; }
    if (responding) stopAnswer();
    setActiveConversationId(id); setQuestion(''); setSidebarOpen(false); setSourceOpen(false);
    switchView('chat');
    const lastSource = conversations.find(c => c.id === id)?.messages.filter(m => m.answer?.sources.length).at(-1)?.answer?.sources.at(-1);
    if (lastSource && window.innerWidth >= 1180) openSource(lastSource);
  }
  function newChat() {
    if (responding) stopAnswer();
    if (conversation.messages.length) {
      const id = crypto.randomUUID();
      setConversations(previous => [{ id, title: '新会话', messages: [], documentIds: null, updatedAt: Date.now() }, ...previous]);
      setActiveConversationId(id);
    }
    setQuestion(''); switchView('chat'); setSourceOpen(false);
    setTimeout(() => composer.current?.focus(), 0);
  }
  function send(text: string) {
    const value = text.trim();
    if (!value || responding) return;
    if (!selectedDocs.length) { setScopeOpen(true); setToast('请在问答范围中选择至少一份可用文档。'); return; }
    const answer = getDemoAnswer(value, messages);
    const unavailable = answer.sources.some(id => !selectedDocs.includes(sources[id].documentId));
    const safeAnswer = unavailable ? { title: '当前问答范围不包含这个示例需要的制度。', paragraphs: ['请点击输入框下方的“问答范围”，选择相关制度或切换为“全部知识库”后重试。'], sources: [] } : answer;
    setMessages(previous => [...previous, { id: crypto.randomUUID(), role: 'user', text: value }]);
    setQuestion(''); setResponding(true); switchView('chat');
    replyTimer.current = setTimeout(() => {
      setMessages(previous => [...previous, { id: crypto.randomUUID(), role: 'assistant', answer: safeAnswer }]);
      setResponding(false); replyTimer.current = null;
      if (safeAnswer.sources.length && activeView.current === 'chat') openSource(safeAnswer.sources[safeAnswer.sources.length - 1]);
    }, 650);
  }
  function stopAnswer() {
    if (replyTimer.current) clearTimeout(replyTimer.current);
    replyTimer.current = null; setResponding(false);
    setMessages(previous => [...previous, { id: crypto.randomUUID(), role: 'assistant', text: '已停止本次示例回答。' }]);
  }
  function upload(files: File[]) {
    setDocuments(previous => [...previous, ...files.map(file => ({ id: crypto.randomUUID(), title: file.name.replace(/\.[^.]+$/, ''), filename: file.name, category: '新导入文档', size: file.size, version: '', pages: [], status: 'queued' as const, demoUpload: true }))]);
    setToast(`已添加 ${files.length} 份文档，正在演示异步处理状态。`);
  }
  async function copyMessage(message: Message) {
    const answer = message.answer;
    const content = answer ? [answer.title, ...answer.paragraphs.map(p => p.replace(/\[[a-z]+\]/g, '')), answer.note ?? ''].filter(Boolean).join('\n\n') : message.text ?? '';
    try { await navigator.clipboard.writeText(content); setCopied(message.id); setTimeout(() => setCopied(null), 1800); }
    catch { setToast('浏览器暂时不允许复制，请选择回答文本后复制。'); }
  }
  function submit(e: FormEvent) { e.preventDefault(); send(question); }

  return <div className="app-shell">
    <header className="topbar">
      <div className="brand"><span className="brand-mark"><BookOpen size={21} strokeWidth={2} /></span><span>企业知识助理<small>让知识有据可循</small></span></div>
      <nav className="main-nav" aria-label="主要导航">{([
        ['chat', MessageSquare, '问答工作台'], ['documents', FolderClosed, '文档管理'], ['graph', Network, '知识图谱'],
      ] as const).map(([id, Icon, name]) => <button key={id} aria-label={name} className={view === id ? 'active' : ''} aria-current={view === id ? 'page' : undefined} onClick={() => switchView(id)}><Icon size={17} /><span>{name}</span></button>)}</nav>
      <div className="topbar-right"><span className="prototype-label">交互原型 · 示例数据</span><span className="workspace-label"><span className="green-dot" />本地工作空间</span></div>
    </header>

    <div className="workspace">
      {sidebarOpen && <button className="mobile-scrim sidebar-scrim" aria-label="收起侧栏" onClick={() => setSidebarOpen(false)} />}
      <WorkspaceSidebar view={view} open={sidebarOpen} onClose={() => setSidebarOpen(false)} conversations={conversations} activeConversationId={activeConversationId} onNewChat={newChat} onConversation={selectConversation} documents={documents} filters={documentFilters} onFilters={setDocumentFilters} graphScenario={graphScenario} onGraphScenario={id => { setGraphScenario(id); setGraphSearch(''); setSourceOpen(false); }} graphSearch={graphSearch} onGraphSearch={setGraphSearch} graphKinds={graphKinds} onGraphKinds={setGraphKinds} />

      <main className={`main-panel ${view === 'chat' ? 'chat-view' : ''}`}>
        <div className="workspace-header"><div className="workspace-title"><IconButton className="mobile-menu" label={`打开${sidebarLabels[view]}`} onClick={() => setSidebarOpen(true)}><Menu size={20} /></IconButton><div><h1>{view === 'chat' ? '制度问答' : view === 'documents' ? '知识文档' : '知识关联'}</h1><p>{view === 'chat' ? '从问题出发，回到原文。' : view === 'documents' ? '让知识清晰、有序，也可追溯。' : '沿着关系，找到每一步的制度依据。'}</p></div></div><div className="workspace-actions"><IconButton label={sourceOpen ? '收起原文面板' : '打开原文面板'} onClick={() => setSourceOpen(!sourceOpen)}>{sourceOpen ? <PanelRightClose size={19} /> : <PanelRightOpen size={19} />}</IconButton></div></div>

        {view === 'chat' && <>
          <div ref={chatBody} className="chat-body" aria-live="polite" aria-busy={responding}>
            <div className="conversation-date"><span />制度知识问答<span /></div>
            {messages.length === 0 && <div className="welcome"><span className="welcome-icon"><BookOpen size={31} /></span><span className="eyebrow">YOUR KNOWLEDGE, WITH SOURCES</span><h2>工作中的疑问，<br />在制度里找到答案。</h2><p>询问请假、报销、采购与员工规范，<br />每个回答都可以回到对应原文。</p><button className="welcome-question" onClick={() => send(openingQuestion)}><MessageSquare size={17} /><span>{openingQuestion}</span><ArrowRight size={17} /></button></div>}
            {messages.map(message => message.role === 'user' ? <div className="user-message" key={message.id}><span className="user-label">你</span><p>{message.text}</p></div> : <section className="assistant-message" key={message.id}>
              <div className="assistant-identity"><span className="assistant-avatar"><Sparkles size={16} /></span><strong>知识助理</strong><span>示例回答</span></div>
              {message.answer ? <div className="answer-content"><h2>{message.answer.title}</h2>{message.answer.paragraphs.map((paragraph, i) => <p key={i}><CitationText text={paragraph} answer={message.answer!} onSource={openSource} /></p>)}{message.answer.note && <div className="answer-note"><ShieldCheck size={16} /><span>{message.answer.note}</span></div>}
                {message.answer.sources.length > 0 && <div className="answer-sources"><span className="sources-caption"><Link2 size={13} />原文依据</span>{message.answer.sources.map((id, index) => <button key={id} className={`source-pill ${activeSource === id && sourceOpen ? 'active' : ''}`} onClick={() => openSource(id)}><span className="source-number">{index + 1}</span><FileText size={13} />{documents.find(d => d.id === sources[id].documentId)?.title}<span className="source-page">P{sources[id].page}</span><ChevronRight size={13} /></button>)}</div>}
              </div> : <p className="answer-content">{message.text}</p>}
              <div className="message-actions"><IconButton label={copied === message.id ? '已复制回答' : '复制回答'} onClick={() => void copyMessage(message)}>{copied === message.id ? <CheckCheck size={15} /> : <Copy size={15} />}</IconButton>{message.answer && message.answer.sources.length > 0 && <span><Check size={12} />附 {message.answer.sources.length} 处条款依据</span>}</div>
            </section>)}
            {responding && <div className="responding"><LoaderCircle className="spinning" size={16} />正在展示示例回答…</div>}
          </div>
          <div className="composer-area"><div className="suggestions">{suggestedQuestions.map(text => <button key={text} onClick={() => send(text)} disabled={responding}>{text}<ArrowRight size={12} /></button>)}</div><form className="composer" onSubmit={submit}><label className="sr-only" htmlFor="question">输入制度问题</label><textarea ref={composer} id="question" placeholder="询问企业制度，或继续追问…" value={question} rows={2} onChange={e => setQuestion(e.target.value)} onKeyDown={e => { if (e.key === 'Enter' && !e.shiftKey && !e.nativeEvent.isComposing) { e.preventDefault(); send(question); } }} /><div className="composer-toolbar"><button type="button" className="scope-selector" onClick={() => setScopeOpen(true)} aria-haspopup="dialog"><Layers3 size={14} /><span>问答范围：{conversation.documentIds === null ? '全部知识库' : `已选 ${selectedDocs.length} 份文档`}</span><ChevronDown size={13} /></button><div><small>Enter 发送</small>{responding ? <button type="button" className="send-button" aria-label="停止示例回答" onClick={stopAnswer}><Square size={15} fill="currentColor" /></button> : <button type="submit" className="send-button" aria-label="发送问题" disabled={!question.trim()}><ArrowUp size={20} /></button>}</div></div></form><p className="composer-disclaimer">当前为交互原型，示例回答不代表真实模型输出。请结合适用条件核对原文。</p></div>
        </>}

        {view === 'documents' && <DocumentsPanel documents={documents} filters={documentFilters} onFilters={setDocumentFilters} onDocument={openDocument} onUpload={() => setUploadOpen(true)} />}

        {view === 'graph' && <Suspense fallback={<p className="empty-note">正在打开知识关联视图…</p>}><GraphPanel key={graphScenario} scenario={graphScenario} search={graphSearch} kinds={graphKinds} onSource={openSource} onReset={() => { setGraphSearch(''); setGraphKinds(['document', 'matter', 'rule', 'role', 'material']); }} /></Suspense>}
      </main>

      {sourceOpen && <>
        <button className="mobile-scrim source-scrim" aria-label="关闭原文面板" onClick={() => setSourceOpen(false)} />
        <aside className="source-panel" aria-label="原文溯源">
          <div className="source-header"><span><FileSearch size={17} /><strong>原文溯源</strong></span><IconButton label="关闭原文" onClick={() => setSourceOpen(false)}><X size={17} /></IconButton></div>
          <div className="source-document"><span className="file-icon"><FileText size={23} /></span><div><strong>{currentDoc.title}</strong><span>{currentDoc.demoUpload ? '上传状态演示' : `${currentDoc.category} · PDF · ${currentDoc.pages.length} 页`}</span></div>{currentDoc.fileUrl && <a className="icon-button" title="打开 PDF 原件" aria-label="打开 PDF 原件" href={currentDoc.fileUrl} target="_blank" rel="noreferrer"><ArrowDownToLine size={17} /></a>}</div>
          <div className="source-tabs" role="tablist" aria-label="原文展示方式">{([['passage', '条款原文'], ['pdf', 'PDF 原件'], ['chunks', '解析片段']] as const).map(([id, label]) => <button key={id} role="tab" aria-selected={sourceTab === id} onClick={() => setSourceTab(id)}>{label}</button>)}</div>
          <div className="source-scroll">
            {currentDoc.demoUpload ? <div className="source-empty"><FileSearch size={29} /><h3>文档尚未实际解析</h3><p>这里演示上传和任务状态。接入解析服务后，将展示真实正文、切片与原文。</p></div> : sourceTab === 'pdf' && currentDoc.fileUrl ? <Suspense fallback={<p className="empty-note">正在加载 PDF 阅读器…</p>}><PdfView url={currentDoc.fileUrl} page={page} /></Suspense> : sourceTab === 'chunks' ? <div className="chunks-list"><span className="eyebrow">原型示例片段 · 非解析服务产物</span>{Object.values(sources).filter(s => s.documentId === currentDoc.id).map(source => <button key={source.id} className="chunk-card" onClick={() => openSource(source.id)}><span><Layers3 size={14} />第 {source.page} 页<ChevronRight size={14} /></span><h3>{source.clause}</h3><p>{source.quote}</p></button>)}{Object.values(sources).every(s => s.documentId !== currentDoc.id) && <p className="empty-note">本原型未预置此文档的条款片段，可在“条款原文”或“PDF 原件”中阅读。</p>}</div> : currentSource ? <div className="source-passage"><div className="source-location"><span className="blue-dot" />已定位引用条款<span>第 {currentSource.page} 页</span></div><article className="paper-card"><div className="paper-kicker">云岚科技 / 内部制度</div><h2>{currentDoc.title}</h2><div className="paper-rule" /><p className="chapter-label">{currentSource.chapter}</p><h3>{currentSource.clause}</h3><blockquote>{currentSource.quote}</blockquote>{currentSource.table && <table className="policy-table"><thead><tr>{currentSource.table[0].map(c => <th key={c}>{c}</th>)}</tr></thead><tbody>{currentSource.table.slice(1).map((row, i) => <tr key={i}>{row.map((c, j) => <td key={j}>{c}</td>)}</tr>)}</tbody></table>}<div className="paper-footer">制度版本 {currentDoc.version}<span>第 {currentSource.page} 页</span></div></article><div className="source-hint"><Link2 size={15} /><span>条款依据来自实际制度。切换 PDF 原件可核对完整上下文。</span></div></div> : <article className="full-page-text"><span className="eyebrow">原文文本 · 第 {page} 页</span><h2>{currentDoc.title}</h2><div className="parsed-text">{currentDoc.pages[page - 1]}</div></article>}
          </div>
          {!currentDoc.demoUpload && <div className="page-controls"><span>{sourceTab === 'pdf' ? 'PDF 原件' : '文档位置'}</span><div><IconButton label="上一页" onClick={() => { setPage(p => Math.max(1, p - 1)); setActiveSource(null); }}><ChevronLeft size={15} /></IconButton><span>{page} <small>/ {currentDoc.pages.length}</small></span><IconButton label="下一页" onClick={() => { setPage(p => Math.min(currentDoc.pages.length, p + 1)); setActiveSource(null); }}><ChevronRight size={15} /></IconButton></div></div>}
        </aside>
      </>}
    </div>
    <ScopeDialog open={scopeOpen} documents={documents} selectedIds={conversation.documentIds} onClose={() => setScopeOpen(false)} onApply={ids => setConversations(previous => previous.map(c => c.id === activeConversationId ? { ...c, documentIds: ids } : c))} />
    <UploadDialog open={uploadOpen} onClose={() => setUploadOpen(false)} onUpload={upload} />
    {toast && <div className="toast" role="status"><CircleCheck size={17} />{toast}</div>}
  </div>;
}

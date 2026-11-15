import {useEffect,useRef,useState} from 'react';
import {ChevronRight,CircleAlert,CircleCheck,FileSearch,FileText,LoaderCircle,Plus,Search,Trash2,X} from 'lucide-react';
import {fileSize,isProcessing,statusNames} from './document-types';
import type {KnowledgeDocument} from './document-types';
import type {DocumentFilters} from './workspace';

type Props={documents:KnowledgeDocument[];filters:DocumentFilters;onDocument:(doc:KnowledgeDocument)=>void;onUpload:()=>void;loading:boolean;error:string;onReload:()=>void;onDelete:(doc:KnowledgeDocument)=>Promise<void>};
export default function DocumentsPanel({documents,filters,onDocument,onUpload,loading,error,onReload,onDelete}:Props){
  const [search,setSearch]=useState('');
  const [deleteTarget,setDeleteTarget]=useState<KnowledgeDocument|null>(null);
  const [deleting,setDeleting]=useState(false);
  const [deleteError,setDeleteError]=useState('');
  const deleteDialog=useRef<HTMLDialogElement>(null);
  useEffect(()=>{if(deleteTarget)deleteDialog.current?.showModal();else deleteDialog.current?.close();},[deleteTarget]);
  async function confirmDelete(){
    if(!deleteTarget||deleting)return;
    setDeleting(true);setDeleteError('');
    try{await onDelete(deleteTarget);setDeleteTarget(null);}
    catch(error){setDeleteError(error instanceof Error?error.message:'暂时无法删除文档。');}
    finally{setDeleting(false);}
  }
  const matches=documents.filter(d=>(filters.status==='all' || (filters.status==='processing'?isProcessing(d):d.status===filters.status)) && `${d.title} ${d.filename}`.toLowerCase().includes(search.trim().toLowerCase()));
  return <div className={`documents-view ${documents.length?'has-documents':''}`}>{!documents.length&&<div className="section-intro"><div><span className="eyebrow">YOUR KNOWLEDGE LIBRARY</span><h2>上传制度文档，开始有据问答。</h2><p>文档自动处理，回答可随时回到原文核对。</p></div><button className="primary-button" onClick={onUpload}><Plus size={16}/>上传文档</button></div>}<div className="library-toolbar"><label className="search-input"><Search size={16}/><input aria-label="搜索文档" placeholder="搜索文档名称或文件名" value={search} onChange={e=>setSearch(e.target.value)}/></label>{documents.length>0&&<button className="primary-button" onClick={onUpload}><Plus size={16}/>上传文档</button>}</div>
    {loading && <p role="status" className="empty-note">正在读取文档…</p>}{error && <div role="alert" className="form-error">{error}<button className="secondary-button" onClick={onReload}>重新加载</button></div>}
    <div className="library-caption"><span>文档 <strong>{matches.length}</strong></span><span>共 {documents.length} 份资料</span></div><div className="documents-table"><div className="table-heading"><span>文档名称</span><span>格式 / 大小</span><span>状态</span><span/></div>{matches.map(doc=><div className="document-entry" key={doc.id}><button className="table-row" onClick={()=>onDocument(doc)}><span className="table-document"><span className="file-icon"><FileText size={21}/></span><span><strong>{doc.title}</strong><small>{doc.pageCount?`${doc.pageCount} 页`:doc.filename}</small></span></span><span className="file-meta">{doc.format.toUpperCase()}<small>{fileSize(doc.size)}</small></span><span className={`status-badge ${doc.canQuery?'ready':doc.status==='failed'?'failed':'processing'}`}>{doc.canQuery?<CircleCheck size={13}/>:doc.status==='failed'?<CircleAlert size={13}/>:isProcessing(doc)?<LoaderCircle size={13} className="spinning"/>:<FileText size={13}/>} {statusNames[doc.status]}</span><ChevronRight size={16}/></button><button className="icon-button document-delete" aria-label={`删除文档：${doc.title}`} title={isProcessing(doc)?'文档正在处理，请完成后再删除':'删除文档'} disabled={isProcessing(doc)} onClick={()=>{setDeleteError('');setDeleteTarget(doc);}}><Trash2 size={15}/></button></div>)}</div>
    {!loading && !error && !matches.length && <div className="library-empty"><FileSearch size={30}/><h3>{documents.length?'没有匹配的文档':'还没有知识文档'}</h3><p>{documents.length?'试试其他名称或状态。':'可以先开始对话，上传文档后再回答具体制度问题。'}</p></div>}
    <dialog ref={deleteDialog} className="upload-dialog delete-document-dialog" aria-labelledby="delete-document-title" onCancel={event=>{event.preventDefault();if(!deleting)setDeleteTarget(null);}}><div className="dialog-header"><h2 id="delete-document-title">删除文档</h2><button className="icon-button" aria-label="关闭删除文档" disabled={deleting} onClick={()=>setDeleteTarget(null)}><X size={18}/></button></div><p className="dialog-description">确定删除“{deleteTarget?.title}”吗？该文档将从知识库移除，不再参与后续检索；已有回答的引用原文仍可查看。</p>{deleteError&&<p role="alert" className="form-error">{deleteError}</p>}<div className="dialog-actions"><button className="secondary-button" disabled={deleting} onClick={()=>setDeleteTarget(null)}>取消</button><button className="primary-button danger-button" disabled={deleting} onClick={()=>{void confirmDelete();}}>{deleting?'正在删除…':'删除'}</button></div></dialog>
  </div>;
}

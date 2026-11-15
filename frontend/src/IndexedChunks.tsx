import {useEffect, useRef, useState} from 'react';
import {ChevronLeft, ChevronRight, FileSearch} from 'lucide-react';
import {listChunks} from './api';
import {InlineMarkdown} from './MarkdownContent';
import type {ChunkSource} from './document-types';

export default function IndexedChunks({versionId,jobId,revision,focusId,focusOrdinal,onBlock,onPage}: {
  versionId:string;jobId:string | null;revision:number;focusId:string | null;focusOrdinal:number;
  onBlock:(blockId:string,source:ChunkSource)=>void;onPage:(page:number,source:ChunkSource)=>void;
}) {
  const [offset,setOffset] = useState(Math.floor(focusOrdinal/50)*50);
  const [retry,setRetry] = useState(0);
  const [value,setValue] = useState<{items:ChunkSource[];total:number} | null>(null);
  const [error,setError] = useState('');
  const container = useRef<HTMLDivElement>(null);
  useEffect(() => {setOffset(Math.floor(focusOrdinal/50)*50);},[versionId,jobId,focusOrdinal]);
  useEffect(() => {
    const controller = new AbortController();setValue(null);setError('');
    listChunks(versionId,jobId,offset,controller.signal).then(data => {if (!controller.signal.aborted) setValue(data);}).catch(failure => {if (!controller.signal.aborted) setError(failure instanceof Error ? failure.message : '切片暂时无法读取');});
    return () => controller.abort();
  },[versionId,jobId,offset,revision,retry]);
  useEffect(() => {if (value && focusId) container.current?.querySelector(`[data-chunk-id="${CSS.escape(focusId)}"]`)?.scrollIntoView({block:'start'});},[value,focusId]);
  return <div ref={container} className="indexed-chunks">
    {error ? <div role="alert" className="source-empty"><p>{error}</p><button className="secondary-button" onClick={() => setRetry(n => n+1)}>重新加载</button></div> : !value ? <p role="status" className="empty-note">正在读取文档切块…</p> : !value.total ? <div className="source-empty"><FileSearch size={28}/><h3>文档切块尚未生成</h3><p>处理完成后会自动显示文档切块。</p></div> : <>
      <p className="parsed-result-note">共 {value.total} 个切块 · 当前 {offset+1}–{offset+value.items.length}</p>
      {value.items.map(chunk => <section key={chunk.id} data-chunk-id={chunk.id} className={`indexed-chunk ${focusId === chunk.id ? 'source-focused' : ''}`}><div className="block-location"><strong>切块 {chunk.ordinal+1}</strong><span>{chunk.page_start !== null ? `第 ${chunk.page_start}${chunk.page_end !== chunk.page_start ? `–${chunk.page_end}` : ''} 页` : '按章节定位'}</span></div><h3><InlineMarkdown text={chunk.heading_path.join(' / ') || '正文'}/></h3><p className="indexed-content">{chunk.content}</p><div className="chunk-links">{chunk.locators[0] && <button className="text-button" onClick={() => onBlock(chunk.locators[0].block_id,chunk)}>定位解析正文</button>}{chunk.page_start !== null && <button className="text-button" onClick={() => onPage(chunk.page_start!,chunk)}>原件第 {chunk.page_start}{chunk.page_end !== chunk.page_start ? `–${chunk.page_end}` : ''} 页</button>}</div></section>)}
      <div className="list-pagination"><span>{Math.floor(offset/50)+1} / {Math.ceil(value.total/50)}</span><div><button className="icon-button" aria-label="上一页切块" disabled={offset === 0} onClick={() => setOffset(n => n-50)}><ChevronLeft size={16}/></button><button className="icon-button" aria-label="下一页切块" disabled={offset+50 >= value.total} onClick={() => setOffset(n => n+50)}><ChevronRight size={16}/></button></div></div>
    </>}
  </div>;
}

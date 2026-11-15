import {useEffect, useRef} from 'react';
import {FileSearch} from 'lucide-react';
import MarkdownContent, {InlineMarkdown} from './MarkdownContent';
import type {ParsedBlock, ParsedResult} from './document-types';

function Body({block}: {block:ParsedBlock}) {
  if (block.type === 'heading') {
    return block.level === 1 ? <h2><InlineMarkdown text={block.text}/></h2> : <h3><InlineMarkdown text={block.text}/></h3>;
  }
  if (block.type === 'table' && block.rows?.length) return <>
    {block.captions?.map((text,i) => <p className="parsed-caption" key={i}>{text}</p>)}
    <div className="parsed-table-scroll"><table><tbody>{block.rows.map((row,i) => <tr key={i}>{row.map((cell,j) => cell.header
      ? <th key={j} colSpan={cell.colspan} rowSpan={cell.rowspan}><InlineMarkdown text={cell.text}/></th>
      : <td key={j} colSpan={cell.colspan} rowSpan={cell.rowspan}><InlineMarkdown text={cell.text}/></td>)}</tr>)}</tbody></table></div>
    {block.footnotes?.map((text,i) => <p className="parsed-footnote" key={i}>{text}</p>)}
  </>;
  if (block.type === 'image') return <figure>{block.asset_url
    ? <img src={block.asset_url} alt={block.text || '文档中的图片'} loading="lazy"/>
    : <p className="empty-note">图片资源未提供</p>}{block.text && <figcaption>{block.text}</figcaption>}</figure>;
  if (block.type === 'code' || block.type === 'formula') return <pre><code>{block.text}</code></pre>;
  return <MarkdownContent text={block.text}/>;
}

export default function ParsedView({result,loading,error,blocks,onPage,onReload,focusBlockId}: {
  result:ParsedResult | null; loading:boolean; error:string; blocks:boolean;
  onPage:(page:number)=>void; onReload:()=>void; focusBlockId?:string | null;
}) {
  const container = useRef<HTMLDivElement>(null);
  useEffect(() => {
    if (focusBlockId && result) container.current?.querySelector(`[data-block-id="${CSS.escape(focusBlockId)}"]`)?.scrollIntoView({block:'start'});
  },[focusBlockId,result?.job_id]);
  if (error && !result) return <div className="source-empty" role="alert"><p>{error}</p><button className="secondary-button" onClick={onReload}>重新加载</button></div>;
  if (!result) return <div className="source-empty"><FileSearch size={29}/><h3>{loading ? '正在读取解析结果…' : '解析结果尚未生成'}</h3><p>可以先查看文档原件，处理完成后会自动显示正文。</p></div>;
  return <div ref={container} className={`parsed-view ${blocks ? 'parsed-blocks' : ''}`}>
    <p className="parsed-result-note">正文已解析{result.page_count !== null ? ` · ${result.page_count} 页` : ' · 按章节定位'}</p>
    {error && <p className="form-error" role="alert">{error} · 当前显示已保存的结果</p>}
    {result.blocks.map((block,index) => <section className={`parsed-block ${block.type} ${focusBlockId === block.block_id ? 'source-focused' : ''}`} key={block.block_id} data-block-id={block.block_id}>
      {blocks && <div className="block-location"><span>{block.block_id} · {block.type}</span><span>{block.heading_path.join(' / ') || '正文'}</span></div>}
      <Body block={block}/>
      {block.page_start !== null && (blocks || index === 0 || result.blocks[index-1].page_end !== block.page_start) && <button className="parsed-page-link" onClick={() => onPage(block.page_start!)}>查看原件第 {block.page_start}{block.page_end !== block.page_start ? `–${block.page_end}` : ''} 页</button>}
    </section>)}
  </div>;
}

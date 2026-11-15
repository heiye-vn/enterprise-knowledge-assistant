import {safeWebHref} from './WebSources';
import type {WebSource} from './retrieval-types';
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import type {ChatCitation} from './api';
import type {ChunkSource} from './document-types';

type MarkdownNode = {type:string;value?:string;url?:string;children?:MarkdownNode[]};

// Citation markers become links in prose; code and existing links retain their literal text.
function citationLinks() {
  return (tree:MarkdownNode) => {
    function visit(node:MarkdownNode) {
      if (!node.children || ['link','linkReference','code','inlineCode','image','html'].includes(node.type)) return;
      node.children = node.children.flatMap(child => {
        if (child.type !== 'text' || !child.value) {visit(child);return [child];}
        const parts:MarkdownNode[]=[];
        let start=0;
        for (const match of child.value.matchAll(/\[(\d+)\]/g)) {
          if (match.index > start) parts.push({type:'text',value:child.value.slice(start,match.index)});
          parts.push({type:'link',url:`#kb-citation-${match[1]}`,children:[{type:'text',value:match[1]}]});
          start=match.index+match[0].length;
        }
        if (!parts.length) return [child];
        if (start < child.value.length) parts.push({type:'text',value:child.value.slice(start)});
        return parts;
      });
    }
    visit(tree);
  };
}

export function InlineMarkdown({text}:{text:string}) {
  return <ReactMarkdown skipHtml allowedElements={['strong','em','code','del','br']} unwrapDisallowed>{text}</ReactMarkdown>;
}

export default function MarkdownContent({text,citations=[],webSources=[],onSource,className='',allowLinks=true}:{
  text:string;citations?:ChatCitation[];webSources?:WebSource[];onSource?:(source:ChunkSource)=>void;className?:string;allowLinks?:boolean;
}) {
  return <div className={`markdown-content ${className}`}><ReactMarkdown skipHtml remarkPlugins={[remarkGfm,citationLinks]} components={{
    a:({href,children}) => {
      const marker=/^#kb-citation-(\d+)$/.exec(href ?? '');
      if (marker) {
        const number=Number(marker[1]);
        if(!allowLinks)return <span>[{number}]</span>;
        const citation=citations.find(item=>item.citation_no===number);
        const web=webSources.find(item=>item.number===number);
        const href=web&&safeWebHref(web.url);
        if(href)return <a className="inline-citation web-inline-citation" aria-label={`查看网页来源 ${number}`} href={href} target="_blank" rel="noopener noreferrer">{number}</a>;
        return citation && onSource
          ? <button type="button" className="inline-citation" aria-label={`查看来源 ${number}`} onClick={()=>onSource(citation.source)}>{number}</button>
          : <span>[{number}]</span>;
      }
      return allowLinks && href && /^(https?:\/\/|mailto:)/i.test(href)
        ? <a href={href} target="_blank" rel="noreferrer noopener">{children}</a>
        : <span>{children}</span>;
    },
    table:({children})=><div className="markdown-table-scroll" tabIndex={0} role="region" aria-label="表格内容，可横向滚动"><table>{children}</table></div>,
    img:({alt})=><span className="markdown-image-label">{alt || '图片'}</span>,
  }}>{text}</ReactMarkdown></div>;
}

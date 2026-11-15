import {ExternalLink,Globe} from 'lucide-react';
import type {WebSearchTrace,WebSource} from './retrieval-types';

export function safeWebHref(value:string){
  try{
    const url=new URL(value);
    if(!['https:','http:'].includes(url.protocol)||url.username||url.password||!url.hostname.includes('.')||/^(localhost|127\.|10\.|192\.168\.|169\.254\.|0\.)/i.test(url.hostname)||/\.(local|localhost)$/i.test(url.hostname))return null;
    return url.href;
  }catch{return null;}
}
export default function WebSources({sources}:{sources:WebSource[]}){
  const valid=sources.filter(source=>safeWebHref(source.url));
  if(!valid.length)return null;
  return <div className="answer-web-sources"><span className="sources-caption"><Globe size={13}/>网页来源</span>{valid.map(source=><a key={source.number} className="web-source-link" href={safeWebHref(source.url)!} target="_blank" rel="noopener noreferrer"><span className="source-number">{source.number}</span><span>{source.title}<small>{new URL(source.url).hostname}</small></span><ExternalLink size={13}/></a>)}</div>;
}
export function WebSearchDetails({web}:{web:WebSearchTrace}){
  if(web.status==='skipped')return <p className="execution-note">本轮涉及企业制度，联网查询已跳过，继续核对知识库依据。</p>;
  return <section className="web-search-details" aria-label="联网查询详情"><strong>Tavily 联网查询</strong>{web.query&&<p>搜索问题：{web.query}</p>}<p>{web.status==='failed'?'搜索未完成':web.status==='running'?'正在查询公开网页':`返回 ${web.results.length} 条公开网页`}{web.queried_at?` · ${new Date(web.queried_at).toLocaleString('zh-CN')}`:''}</p>{web.results.map(source=>safeWebHref(source.url)&&<div key={source.number} className="web-result-row"><a href={safeWebHref(source.url)!} target="_blank" rel="noopener noreferrer">[{source.number}] {source.title}</a><small>{web.used_numbers?.includes(source.number)?'最终引用':'搜索返回'}</small></div>)}<p className="execution-note">网页用于公共信息查询，企业内部制度仍以知识库原文为准。</p></section>;
}

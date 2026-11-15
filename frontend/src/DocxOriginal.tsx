import {useEffect,useRef,useState} from 'react';
import {renderAsync} from 'docx-preview';
import {Minus,Plus,Scan} from 'lucide-react';

export default function DocxOriginal({url}:{url:string}) {
  const host=useRef<HTMLDivElement>(null);
  const [loading,setLoading]=useState(true);
  const [error,setError]=useState('');
  const [zoom,setZoom]=useState(1);
  const zoomValue=useRef(1);
  const refit=useRef<()=>void>(()=>{});
  useEffect(()=>{zoomValue.current=zoom;refit.current();},[zoom]);
  useEffect(()=>{
    const controller=new AbortController();
    const element=host.current;
    if(!element)return;
    const shadow=element.shadowRoot??element.attachShadow({mode:'open'});
    const stage=document.createElement('div');
    const style=document.createElement('style');
    style.textContent='.eka-docx-wrapper{padding:12px!important;background:#edf2f8!important}.eka-docx-wrapper>section.eka-docx{margin-bottom:14px!important;box-shadow:0 1px 7px #233b5720!important}';
    shadow.replaceChildren(style,stage);
    setLoading(true);setError('');
    const fit=()=>{
      const page=stage.querySelector<HTMLElement>('section.eka-docx');
      if(page&&element.clientWidth>0)stage.style.zoom=String(Math.min(1,(element.clientWidth-24)/page.offsetWidth)*zoomValue.current);
    };
    refit.current=fit;
    const observer=new ResizeObserver(fit);observer.observe(element);
    async function load(){
      try{
        const response=await fetch(url,{signal:controller.signal});
        if(!response.ok)throw new Error();
        const buffer=await response.arrayBuffer();
        if(controller.signal.aborted)return;
        await renderAsync(buffer,stage,stage,{className:'eka-docx',ignoreFonts:true,useBase64URL:true,renderAltChunks:false,renderComments:false,breakPages:true});
        if(controller.signal.aborted)return;
        for(const link of stage.querySelectorAll<HTMLAnchorElement>('a[href]')){
          const href=(link.getAttribute('href')??'').trim();
          if(href.startsWith('#'))continue;
          if(!/^(https?:|mailto:)/i.test(href))link.removeAttribute('href');
          else{link.target='_blank';link.rel='noopener noreferrer';}
        }
        fit();setLoading(false);
      }catch{
        if(!controller.signal.aborted){setLoading(false);setError('Word 原件暂时无法预览，可查看文档正文或在新窗口打开原件。');}
      }
    }
    void load();
    return()=>{controller.abort();observer.disconnect();stage.remove();refit.current=()=>{};};
  },[url]);
  return <div className="docx-original"><p className="original-preview-note">Word 原件预览，分页和字体可能与编辑器略有差异。</p><div className="image-original-tools"><span>Word 原件</span><button className="icon-button" aria-label="缩小 Word 原件" disabled={zoom<=1||loading} onClick={()=>setZoom(value=>Math.max(1,value-0.25))}><Minus size={16}/></button><button className="icon-button" aria-label="放大 Word 原件" disabled={zoom>=3||loading} onClick={()=>setZoom(value=>Math.min(3,value+0.25))}><Plus size={16}/></button><button className="icon-button" aria-label="Word 原件适应宽度" onClick={()=>setZoom(1)}><Scan size={16}/></button></div>{loading&&<p role="status" className="empty-note">正在加载 Word 原件…</p>}{error&&<p role="alert" className="form-error">{error}</p>}<div className="docx-original-content" ref={host} aria-label="Word 原件内容"/></div>;
}

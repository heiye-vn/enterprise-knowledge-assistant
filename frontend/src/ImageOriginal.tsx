import {useState} from 'react';
import {Minus,Plus,Scan} from 'lucide-react';

export default function ImageOriginal({url,title}:{url:string;title:string}){
  const [scale,setScale]=useState(1);
  const [loaded,setLoaded]=useState(false);
  const [error,setError]=useState(false);
  return <div className="image-original"><div className="image-original-tools"><span>图片原件</span><button className="icon-button" aria-label="缩小原图" disabled={scale<=1} onClick={()=>setScale(value=>Math.max(1,value-0.25))}><Minus size={16}/></button><button className="icon-button" aria-label="放大原图" disabled={scale>=3} onClick={()=>setScale(value=>Math.min(3,value+0.25))}><Plus size={16}/></button><button className="icon-button" aria-label="原图适应宽度" onClick={()=>setScale(1)}><Scan size={16}/></button></div>{!loaded&&!error&&<p role="status" className="empty-note">正在加载图片原件…</p>}{error?<p role="alert" className="form-error">原图暂时无法读取，请在新窗口打开原件。</p>:<div className="image-original-viewport"><img src={url} alt={title+'的制度原图'} style={{width:`${scale*100}%`,maxWidth:'none'}} onLoad={()=>setLoaded(true)} onError={()=>setError(true)}/></div>}</div>;
}

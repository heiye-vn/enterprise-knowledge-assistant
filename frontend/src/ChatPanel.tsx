import {useEffect,useRef,useState} from 'react';
import {BookOpen,Globe,LoaderCircle,Send,Square,Upload} from 'lucide-react';
import {getChatSession,stopChat,streamChat} from './api';
import type {ChatMessageDto} from './api';
import type {ChatPair} from './chat-stream';
import type {ChunkSource} from './document-types';
import ChatMessageView from './ChatMessageView';

type RequestInfo={sessionId:string;text:string;id:string;attempt:number;webSearch:boolean};
const terminal=(status:string)=>['completed','stopped','failed'].includes(status);
function mergePair(items:ChatMessageDto[],reply:ChatPair,requestId:string){
  const next=items.filter(message=>message.id!==`pending-${requestId}`);
  for(const message of [reply.user,reply.assistant]){
    const index=next.findIndex(item=>item.id===message.id);
    if(index<0)next.push(message);
    else if((next[index].attempt_no??1)<=(message.attempt_no??1))next[index]=message;
  }
  return next;
}

export default function ChatPanel({sessionId,ensureSession,onUpdated,onSource,onUpload,onBusy}:{sessionId:string;ensureSession:()=>Promise<string>;onUpdated:()=>void;onSource:(source:ChunkSource,tab?:'passage'|'indexed')=>void;onUpload:()=>void;onBusy:(busy:boolean)=>void}){
  const [items,setItems]=useState<ChatMessageDto[]>([]);
  const [text,setText]=useState('');
  const [webEnabled,setWebEnabled]=useState(false);
  const [busy,setBusy]=useState(false);
  const [stopping,setStopping]=useState(false);
  const [loading,setLoading]=useState(false);
  const [error,setError]=useState('');
  const active=useRef(sessionId);active.current=sessionId;
  const sending=useRef(false);
  const pending=useRef<RequestInfo|null>(null);
  const current=useRef<RequestInfo|null>(null);
  const requestAbort=useRef<AbortController|null>(null);
  const stopAcknowledged=useRef(false);
  const end=useRef<HTMLDivElement>(null);
  const follow=useRef(true);
  const generation=useRef(0);
  const hasPendingAnswer=items.some(message=>message.role==='assistant'&&!terminal(message.status));
  const working=busy||hasPendingAnswer;
  useEffect(()=>{
    const revision=++generation.current;
    if(sending.current)return;
    setItems([]);setError('');setLoading(!!sessionId);setText('');setWebEnabled(false);
    if(!sessionId)return;
    const controller=new AbortController();
    getChatSession(sessionId,controller.signal).then(data=>{if(!controller.signal.aborted&&revision===generation.current)setItems(data.messages);}).catch(failure=>{if(!controller.signal.aborted)setError(failure instanceof Error?failure.message:'会话暂时无法读取');}).finally(()=>{if(!controller.signal.aborted)setLoading(false);});
    return()=>controller.abort();
  },[sessionId]);
  useEffect(()=>{onBusy(working);},[working,onBusy]);
  useEffect(()=>()=>{requestAbort.current?.abort();onBusy(false);},[onBusy]);
  useEffect(()=>{
    if(!sessionId||busy||!hasPendingAnswer)return;
    const timer=setTimeout(()=>{void getChatSession(sessionId).then(data=>{if(active.current===sessionId){setItems(data.messages);if(terminal(data.messages.at(-1)?.status??''))setError('');}}).catch(()=>setError('暂时无法读取回答状态，请稍后刷新。'));},1500);
    return()=>clearTimeout(timer);
  },[sessionId,busy,hasPendingAnswer,items]);
  useEffect(()=>{if(follow.current&&(items.length||busy))end.current?.scrollIntoView({block:'end'});},[items,busy]);

  async function execute(request:RequestInfo){
    const controller=new AbortController();
    current.current=request;requestAbort.current=controller;stopAcknowledged.current=false;
    sending.current=true;setBusy(true);setError('');follow.current=true;
    let assistantId='';
    const visible=()=>current.current===request&&(!active.current||active.current===request.sessionId);
    try{
      await streamChat(request.sessionId,request.id,request.text,event=>{
        if(!visible())return;
        if(event.event==='start'||event.event==='done'){
          assistantId=event.data.assistant.id;
          setItems(previous=>mergePair(previous,event.data,request.id));
          if(event.event==='done')pending.current=null;
        }else if(event.event==='phase'){
          setItems(previous=>previous.map(message=>message.id===assistantId&&!terminal(message.status)?{...message,stream_phase:event.data.phase,answer_mode:event.data.mode??message.answer_mode,status:['generating','validating'].includes(event.data.phase)?'generating':'retrieving'}:message));
        }else if(event.event==='delta'&&!stopAcknowledged.current){
          setItems(previous=>previous.map(message=>message.id===assistantId&&!terminal(message.status)?{...message,content:message.content+event.data.text}:message));
        }
      },controller.signal,request.attempt>1?request.attempt:undefined,request.webSearch);
    }catch(failure){
      if(!stopAcknowledged.current&&visible()){
        setError(failure instanceof Error?failure.message:'回答连接中断，正在确认已保存的内容。');
        if(typeof failure==='object'&&failure&&'status' in failure)pending.current=null;
        try{
          const saved=await getChatSession(request.sessionId);
          if(visible()){
            setItems(saved.messages);
            const last=saved.messages.at(-1);
            if(last?.client_request_id===request.id){setText('');if(terminal(last.status)){pending.current=null;setError('');}}
            else setText(request.text);
          }
        }catch{if(visible())setError('连接已中断，请刷新查看已保存的内容。');}
      }
    }finally{
      if(current.current===request){current.current=null;requestAbort.current=null;sending.current=false;setBusy(false);setLoading(false);}
      onUpdated();
    }
  }
  async function submit(event:React.SubmitEvent<HTMLFormElement>){
    event.preventDefault();const question=text.trim();if(!question||sending.current||hasPendingAnswer)return;
    sending.current=true;setBusy(true);setError('');++generation.current;
    let started=false;
    try{
      const identity=sessionId||await ensureSession();
      const request=pending.current?.sessionId===identity&&pending.current.text===question?pending.current:{sessionId:identity,text:question,id:crypto.randomUUID(),attempt:1,webSearch:webEnabled};
      pending.current=request;
      const user:ChatMessageDto={id:`pending-${request.id}`,role:'user',content:question,status:'completed',answer_kind:null,citations:[],error:null};
      setItems(previous=>[...previous.filter(message=>message.id!==user.id),user]);setText('');
      started=true;await execute(request);
    }catch(failure){setError(failure instanceof Error?failure.message:'暂时无法创建会话。');setText(question);}
    finally{if(!started){sending.current=false;setBusy(false);setLoading(false);}}
  }
  function requestFor(message:ChatMessageDto):RequestInfo|null{
    const index=items.findIndex(item=>item.id===message.id);
    const question=items.slice(0,index).reverse().find(item=>item.role==='user')?.content;
    return sessionId&&question&&message.client_request_id?{sessionId,text:question,id:message.client_request_id,attempt:message.attempt_no??1,webSearch:message.web_search_requested??false}:null;
  }
  async function retryAnswer(message:ChatMessageDto){
    const previous=requestFor(message);if(sending.current||!previous||previous.attempt>=3)return;
    const request={...previous,attempt:previous.attempt+1};pending.current=request;setWebEnabled(request.webSearch);
    setItems(items=>items.map(item=>item.id===message.id?{...item,status:'retrieving',content:'',error:null,details:null,warnings:[],citations:[],web_sources:[],attempt_no:request.attempt}:item));
    await execute(request);
  }
  async function stopAnswer(){
    const message=[...items].reverse().find(item=>item.role==='assistant'&&!terminal(item.status));
    const request=current.current??(message?requestFor(message):null);
    if(!request||stopping)return;
    setStopping(true);setError('');
    try{
      const result=await stopChat(request.sessionId,request.id,request.text,request.attempt,request.webSearch);
      if(!active.current||active.current===request.sessionId){
        if(!current.current||current.current===request){
          stopAcknowledged.current=true;pending.current=null;
          setItems(previous=>mergePair(previous,result,request.id));
          if(current.current===request)requestAbort.current?.abort();
        }
      }
    }catch(failure){setError(failure instanceof Error?failure.message:'暂时无法确认停止状态，请重试。');}
    finally{setStopping(false);onUpdated();}
  }
  return <>
    <div className={`chat-body ${!loading&&!items.length?'chat-body-empty':''}`} aria-live="polite" onScroll={event=>{const area=event.currentTarget;follow.current=area.scrollHeight-area.scrollTop-area.clientHeight<90;}}>
      {loading&&<p role="status" className="empty-note">正在读取会话…</p>}
      {!loading&&!items.length&&<div className="welcome"><span className="welcome-icon"><BookOpen size={31}/></span><span className="eyebrow">YOUR KNOWLEDGE, WITH SOURCES</span><h2>有什么想了解的？</h2><p>通用问题直接聊，企业制度有据可查。<br/>从一个问题开始，或上传文档补充知识库。</p><button className="secondary-button" onClick={onUpload}><Upload size={16}/>上传知识文档</button></div>}
      {items.map(message=><ChatMessageView key={message.id} message={message} isLast={message.id===items.at(-1)?.id} busy={working} onRetry={message=>{void retryAnswer(message);}} onSource={onSource}/>)}
      {busy&&!hasPendingAnswer&&<p role="status" className="responding"><LoaderCircle size={16} className="spinning"/>正在连接回答…</p>}
      <div ref={end} className="chat-end"/>
    </div>
    <div className="composer-area"><form className="composer" onSubmit={submit}><label className="sr-only" htmlFor="question">输入问题</label><textarea id="question" value={text} maxLength={2000} disabled={working} placeholder="直接提问，例如：请假四天需要谁审批？" rows={2} onChange={event=>setText(event.target.value)} onKeyDown={event=>{if(event.key==='Enter'&&!event.shiftKey&&!event.nativeEvent.isComposing){event.preventDefault();event.currentTarget.form?.requestSubmit();}}}/><div className="composer-toolbar"><div className="composer-options"><span>通用对话 · 知识库问答</span><label className={`web-search-toggle ${webEnabled?'is-enabled':''}`}><input type="checkbox" role="switch" aria-label="联网查询" checked={webEnabled} disabled={working} onChange={event=>setWebEnabled(event.target.checked)}/><Globe size={14}/><span>联网查询</span></label></div>{working?<button type="button" className="secondary-button stop-answer-button" aria-label="停止生成" disabled={stopping||(!current.current&&!hasPendingAnswer)} onClick={()=>{void stopAnswer();}}><Square size={15}/>{stopping?'正在停止…':'停止生成'}</button>:<button type="submit" className="primary-button" aria-label="发送问题" disabled={loading||!text.trim()}><Send size={16}/>发送</button>}</div></form>{error&&<p role="alert" className="chat-send-error">{error}</p>}<p className="composer-disclaimer">{webEnabled?'联网仅查询公开信息；企业制度仍以知识库原文为准。':'通用回答来自模型；企业制度以知识库原文为准。'}</p></div>
  </>;
}

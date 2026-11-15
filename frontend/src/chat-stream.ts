import type {ChatMessageDto} from './api.ts';

export type ChatPair={user:ChatMessageDto;assistant:ChatMessageDto};
export type ChatStreamEvent=
  | {event:'start'|'done';data:ChatPair}
  | {event:'phase';data:{phase:string;mode?:'general'|'knowledge'|'clarify'|'web'|null}}
  | {event:'delta';data:{text:string}};

function pair(value:unknown):value is ChatPair {
  if(!value||typeof value!=='object'||!('user' in value)||!('assistant' in value))return false;
  const data=value as ChatPair;
  return typeof data.user?.id==='string'&&data.user.role==='user'&&typeof data.assistant?.id==='string'&&data.assistant.role==='assistant'&&typeof data.assistant.content==='string';
}

export async function consumeChatStream(response:Response,onEvent:(event:ChatStreamEvent)=>void):Promise<ChatPair>{
  if(!response.body||!response.headers.get('Content-Type')?.includes('text/event-stream'))throw new Error('回答流协议异常，请刷新查看会话。');
  const reader=response.body.getReader();
  const decoder=new TextDecoder('utf-8',{fatal:true});
  let buffer='',name='',data:string[]=[],eventSize=0,started=false;
  try{
    while(true){
      const block=await reader.read();
      if(block.done)break;
      buffer+=decoder.decode(block.value,{stream:true});
      if(buffer.length>2_000_000)throw new Error('回答流超出内容限制。');
      let end:number;
      while((end=buffer.indexOf('\n'))>=0){
        const line=buffer.slice(0,end).replace(/\r$/,'');buffer=buffer.slice(end+1);
        if(line.startsWith(':'))continue;
        if(line.startsWith('event:')){name=line.slice(6).trim();continue;}
        if(line.startsWith('data:')){data.push(line.slice(5).trimStart());eventSize+=line.length;if(eventSize>2_000_000)throw new Error('回答流超出内容限制。');continue;}
        if(line||!data.length)continue;
        const value:unknown=JSON.parse(data.join('\n'));data=[];eventSize=0;
        if(name==='error')throw new Error(typeof value==='object'&&value&&'message' in value?String(value.message):'回答连接中断，请刷新查看。');
        if(name==='start'){
          if(started||!pair(value))throw new Error('回答流协议异常。');
          started=true;onEvent({event:'start',data:value});
        }else if(name==='done'){
          if(!started||!pair(value)||!['completed','stopped','failed'].includes(value.assistant.status))throw new Error('回答结束状态异常，请刷新查看。');
          onEvent({event:'done',data:value});return value;
        }else if(name==='delta'){
          if(!started||!value||typeof value!=='object'||!('text' in value)||typeof value.text!=='string')throw new Error('回答流协议异常。');
          onEvent({event:'delta',data:{text:value.text}});
        }else if(name==='phase'){
          if(!started||!value||typeof value!=='object'||!('phase' in value)||typeof value.phase!=='string')throw new Error('回答流协议异常。');
          onEvent({event:'phase',data:value as {phase:string;mode?:'general'|'knowledge'|'clarify'|'web'|null}});
        }else throw new Error('回答流协议异常。');
        name='';
      }
    }
    throw new Error('回答连接提前中断，正在确认已保存的内容。');
  }finally{
    await reader.cancel().catch(()=>{});reader.releaseLock();
  }
}

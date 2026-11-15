import assert from 'node:assert/strict';
import test from 'node:test';
import {consumeChatStream} from '../src/chat-stream.ts';

const user={id:'u',role:'user',content:'问题',status:'completed'};
const assistant={id:'a',role:'assistant',content:'',status:'generating'};
const pair={user,assistant};
function event(name:string,data:unknown){return `event: ${name}\r\ndata: ${JSON.stringify(data)}\r\n\r\n`;}
function response(parts:Uint8Array[]){return new Response(new ReadableStream({start(controller){for(const part of parts)controller.enqueue(part);controller.close();}}),{headers:{'Content-Type':'text/event-stream'}});}

test('SSE reads Chinese UTF-8 across arbitrary chunks and comments without leaking protocol',async()=>{
  const wire=': heartbeat\r\n\r\n'+event('start',pair)+event('phase',{phase:'generating',mode:'knowledge'})+event('delta',{text:'中文😀[1]'})+event('done',{user,assistant:{...assistant,content:'中文😀[1]',status:'completed'}});
  const bytes=new TextEncoder().encode(wire);const seen:string[]=[];
  const result=await consumeChatStream(response(Array.from(bytes,value=>new Uint8Array([value]))),value=>{if(value.event==='delta')seen.push(value.data.text);});
  assert.deepEqual(seen,['中文😀[1]']);assert.equal(result.assistant.status,'completed');
});

test('delta callback fires before the network response has finished',async()=>{
  let network!:ReadableStreamDefaultController<Uint8Array>;
  let accept!:()=>void;const received=new Promise<void>(resolve=>{accept=resolve;});
  const stream=new ReadableStream<Uint8Array>({start(controller){network=controller;}});
  let finished=false;
  const result=consumeChatStream(new Response(stream,{headers:{'Content-Type':'text/event-stream'}}),value=>{if(value.event==='delta')accept();}).then(value=>{finished=true;return value;});
  network.enqueue(new TextEncoder().encode(event('start',pair)+event('delta',{text:'第一段'})));
  await received;assert.equal(finished,false);
  network.enqueue(new TextEncoder().encode(event('done',{user,assistant:{...assistant,status:'stopped',content:'第一段'}})));network.close();
  assert.equal((await result).assistant.status,'stopped');
});

test('missing terminal event and a false completed envelope are rejected',async()=>{
  const encode=(text:string)=>new TextEncoder().encode(text);
  await assert.rejects(consumeChatStream(response([encode(event('start',pair)+event('delta',{text:'草稿'}))]),()=>{}),/中断|结束/);
  await assert.rejects(consumeChatStream(response([encode(event('start',pair)+event('done',pair))]),()=>{}),/状态|协议/);
});

import assert from 'node:assert/strict';
import test from 'node:test';
import React from 'react';
import {renderToStaticMarkup} from 'react-dom/server';
import ChatMessageView from '../src/ChatMessageView.tsx';
import type {ChatMessageDto} from '../src/api.ts';

const message={id:'a',role:'assistant',status:'generating',content:'已收到的草稿[1]',answer_mode:'knowledge',answer_kind:null,error:null,client_request_id:'r',attempt_no:1,citations:[{citation_no:1,source:{document_title:'制度'},quote:'原文'}]} as ChatMessageDto;
function render(value:ChatMessageDto){return renderToStaticMarkup(<ChatMessageView message={value} isLast busy={false} onRetry={()=>{}} onSource={()=>{}}/>);}
test('streaming and stopped drafts never expose unverified source links',()=>{
  for(const status of ['generating','stopped']){
    const html=render({...message,status});
    assert.ok(html.replace(/<[^>]+>/g,'').includes('已收到的草稿[1]'));
    assert.ok(!html.includes('查看来源 1')&&!html.includes('回答依据'));
  }
  const stopped=render({...message,status:'stopped'});
  assert.ok(stopped.includes('已停止')&&stopped.includes('重新生成'));
});
test('only completed answers publish citation controls',()=>{
  const html=render({...message,status:'completed',answer_kind:'answered'});
  assert.ok(html.includes('查看来源 1')&&html.includes('回答依据'));
});
test('failed streaming answers retain the draft and a clear incomplete state',()=>{
  const html=render({...message,status:'failed',error:{code:'model_stream_incomplete',message:'连接中断',retryable:true}});
  assert.ok(html.includes('已收到的草稿')&&html.includes('连接中断')&&html.includes('重试回答'));
  assert.ok(!html.includes('查看来源 1'));
});

test('web links are published only after completion and unsafe sources stay inert',()=>{
  const web={...message,answer_mode:'web',content:'公开事实[1]',citations:[],web_sources:[{number:1,title:'官方发布',url:'https://www.python.org/a',content:'release'}]} as ChatMessageDto;
  for(const status of ['generating','stopped','failed'])assert.ok(!render({...web,status}).includes('https://www.python.org/a'));
  const complete=render({...web,status:'completed'});
  assert.ok(complete.includes('https://www.python.org/a')&&complete.includes('网页来源')&&!complete.includes('回答依据'));
  const unsafe=render({...web,status:'completed',web_sources:[{...web.web_sources![0],url:'javascript:alert(1)'}]});
  assert.ok(!unsafe.includes('javascript:')&&!unsafe.includes('href="javascript'));
});

test('unfinished answers format Markdown while citations and links remain inactive',()=>{
  for(const status of ['generating','stopped','failed']){
    const html=render({...message,status,content:'## 实时说明\n\n- **审批角色**[1]\n- 第二项\n\n[外部链接](https://example.com)\n\n```js\nconst value = 1;\n```'});
    assert.ok(html.includes('<h2>实时说明</h2>'));
    assert.ok(html.includes('<ul>')&&html.includes('<strong>审批角色</strong>')&&html.includes('<pre>'));
    assert.ok(html.includes('[1]')&&!html.includes('<a ')&&!html.includes('查看来源 1'));
  }
});

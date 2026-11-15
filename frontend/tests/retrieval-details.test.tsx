import assert from 'node:assert/strict';
import test from 'node:test';
import React from 'react';
import {renderToStaticMarkup} from 'react-dom/server';
import RetrievalDetails from '../src/RetrievalDetails.tsx';
import type {ExecutionDetails} from '../src/retrieval-types.ts';
import type {ChunkSource} from '../src/document-types.ts';

const source={id:'a',document_title:'费用制度',ordinal:2,heading_path:['审批'],content:'真实原文摘要',page_start:1} as ChunkSource;
const details:ExecutionDetails={version:1,intent:{mode:'knowledge',decision:'model',query:'6000元报销审批'},outcome:'answered',total_ms:1200,stages:[{key:'intent',status:'completed',duration_ms:100},{key:'retrieval',status:'completed',duration_ms:500},{key:'answer',status:'completed',duration_ms:600}],retrieval:{query:'6000元报销审批',stages:[{key:'rerank',status:'completed',duration_ms:200}],counts:{documents:1,bm25:2,vector:3,fusion:3,rerank_input:3,returned:2},candidates:[
  {source,scores:{bm25:-0.2,vector_distance:0.1,rrf:0.0325,rerank:0.93},ranks:{bm25:2,vector:1,fusion:2,rerank:1},selected:true,sent_to_model:true,used_in_answer:true,citation_no:1},
  {source:{...source,id:'b'},scores:{bm25:null,vector_distance:0.4,rrf:0.016,rerank:0.72},ranks:{bm25:null,vector:2,fusion:3,rerank:2},selected:true,sent_to_model:true,used_in_answer:false,citation_no:null},
  {source:{...source,id:'c'},scores:{bm25:1.1,vector_distance:null,rrf:0.015,rerank:0.2},ranks:{bm25:1,vector:null,fusion:1,rerank:3},selected:false,sent_to_model:false,used_in_answer:false,citation_no:null},
]}};
function render(value:ExecutionDetails|null){return renderToStaticMarkup(<RetrievalDetails details={value} warnings={[]} onSource={()=>{}}/>);}

test('graph paths retain source evidence and distinguish expansion from final citations',()=>{
  const value=structuredClone(details);
  value.retrieval!.graph={enabled:true,status:'completed',reason:null,seed_count:1,added_count:1,candidate_ids:['b'],paths:[{nodes:['员工手册','考勤制度','请假审批'],relations:['引用制度','包含规则'],from:{source,quote:'按考勤制度申请。',conditions:[]},to:{source:{...source,id:'b'},quote:'人力资源部仅备案，不替代业务审批。',conditions:['超过3个工作日']},used_in_answer:false}]};
  value.retrieval!.candidates[1].graph_expanded=true;
  value.retrieval!.candidates[1].scores.rrf=null;
  value.retrieval!.candidates[1].ranks.fusion=null;
  const html=render(value);
  for(const text of ['图谱证据路径','员工手册 → 考勤制度 → 请假审批','人力资源部仅备案','未作最终引用','图谱补充','未参与融合'])assert.ok(html.includes(text),text);
  assert.ok(!html.includes('融合 #null'));
});

test('old messages never receive invented retrieval details',()=>{assert.equal(render(null),'');});
test('scores retain their scale and missing routes never display zero scores',()=>{
  const html=render(details);
  for(const value of ['6000元报销审批','-0.2000','0.1000','0.032500','0.9300','未命中'])assert.ok(html.includes(value),value);
  assert.ok(!html.includes('93%'));
  assert.ok(html.includes('查看切块')&&html.includes('查看原文'));
  assert.ok(!html.includes('<details class="execution-details" open'));
});
test('candidates, submitted evidence and final citations stay distinguishable',()=>{
  const html=render(details);
  assert.equal((html.match(/实际引用 \[1\]/g)??[]).length,1);
  assert.ok(html.includes('已送入回答')&&html.includes('召回候选'));
  assert.ok(html.includes('融合 #2')&&html.includes('重排 #1'));
});
test('failed rerank is explicitly unavailable rather than a low numeric score',()=>{
  const value=structuredClone(details);
  value.retrieval!.stages=[{key:'rerank',status:'failed',duration_ms:200}];
  value.retrieval!.candidates.forEach(c=>{c.scores.rerank=null;c.ranks.rerank=null;});
  const html=render(value);
  assert.ok(html.includes('未完成')&&!html.includes('0.0000'));
});
test('clarification shows skipped retrieval without fabricated candidate panels',()=>{
  const html=render({...details,intent:{mode:'clarify',decision:'model',query:null},retrieval:null,outcome:'clarify',stages:[{key:'intent',status:'completed',duration_ms:100},{key:'retrieval',status:'skipped',duration_ms:null},{key:'answer',status:'skipped',duration_ms:null,note:'included_in_intent'}]});
  assert.ok(html.includes('需要澄清')&&html.includes('未执行'));
  assert.ok(!html.includes('召回候选')&&!html.includes('BM25'));
});

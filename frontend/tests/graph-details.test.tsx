import assert from 'node:assert/strict';
import test from 'node:test';
import React from 'react';
import {renderToStaticMarkup} from 'react-dom/server';
import {GraphEvidence,GraphJobList} from '../src/GraphDetails.tsx';
import type {GraphJob,GraphEvidenceDto} from '../src/graph-api-types.ts';
import type {ChunkSource} from '../src/document-types.ts';

const job:GraphJob={id:'g1',document_id:'d1',title:'考勤制度',status:'ready',stage:'done',attempt_no:1,max_attempts:3,error:null,processed_units:20,total_units:20,rule_count:12,relation_count:18,rejected_count:2,unit_limit_reached:false,has_previous:false,needs_update:false,source_job_id:'i1'};
function jobs(values:GraphJob[]){return renderToStaticMarkup(<GraphJobList jobs={values} busy={false} onRetry={()=>{}} onDocument={()=>{}}/>);}

test('a partially validated graph does not claim complete coverage',()=>{
  const html=jobs([job]);assert.ok(html.includes('未通过校验')&&html.includes('2'));
  assert.ok(html.includes('12')&&html.includes('18'));
});
test('failed update retains prior graph and offers only bounded retry',()=>{
  const failed={...job,status:'failed',has_previous:true,error:{code:'graph_projection_unavailable',message:'图谱服务暂不可用',retryable:true}};
  assert.ok(jobs([failed]).includes('上次结果'));
  assert.ok(jobs([failed]).includes('重试生成'));
  assert.ok(!jobs([{...failed,attempt_no:3}]).includes('重试生成'));
});
test('unprocessed sources never appear as a finished graph',()=>{
  const html=jobs([{...job,id:null,status:'not_generated',rule_count:0,relation_count:0}]);
  assert.ok(html.includes('尚未生成'));
});
test('source evidence keeps exact conditions and both source navigation actions',()=>{
  const evidence:GraphEvidenceDto={source:{id:'c1',document_title:'考勤制度',heading_path:['审批流程'],ordinal:1,page_start:null} as ChunkSource,quote:'超过3天，主管审批，人力资源部备案。',scope:'超过3天',conditions:['人力资源部备案不替代审批。']};
  const html=renderToStaticMarkup(<GraphEvidence ids={['s1']} sources={{s1:evidence}} onSource={()=>{}}/>);
  for(const text of ['超过3天','人力资源部备案不替代审批。','查看原文','查看切块'])assert.ok(html.includes(text),text);
});
test('missing evidence is not replaced with a made-up source',()=>{
  const html=renderToStaticMarkup(<GraphEvidence ids={['missing']} sources={{}} onSource={()=>{}}/>);
  assert.ok(!html.includes('查看原文')&&!html.includes('查看切块'));
});

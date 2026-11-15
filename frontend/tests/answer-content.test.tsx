import assert from 'node:assert/strict';
import test from 'node:test';
import React from 'react';
import {renderToStaticMarkup} from 'react-dom/server';
import MarkdownContent, {InlineMarkdown} from '../src/MarkdownContent.tsx';
import type {ChatCitation} from '../src/api.ts';

const citation={citation_no:1,quote:'报销应提供发票。',source:{id:'chunk-1',document_title:'费用制度'}} as ChatCitation;
function render(text:string){return renderToStaticMarkup(<MarkdownContent text={text} citations={[citation]} onSource={()=>{}}/>);}

test('answers render headings, lists, tables and code as structured content',()=>{
  const html=render('## 报销要求\n\n1. 提供 **发票**\n2. 附审批记录\n\n| 金额 | 审批 |\n| --- | --- |\n| 6000元 | 财务经理 |\n\n```python\nprint("ok")\n```');
  for(const tag of ['<h2>','<ol>','<li>','<strong>发票</strong>','<table>','<th>金额</th>','<pre>','language-python'])assert.ok(html.includes(tag),tag);
});

test('only valid source numbers turn into citation buttons outside code and links',()=>{
  const html=render('应提供发票。[1] 未知编号[9]\n\n`示例[1]`\n\n[网页[1]](https://example.com)');
  assert.equal((html.match(/aria-label="查看来源 1"/g)??[]).length,1);
  assert.ok(html.replace(/<[^>]*>/g,'').includes('未知编号[9]'));
  assert.ok(html.includes('<code>示例[1]</code>'));
  assert.ok(html.includes('target="_blank"') && html.includes('rel="noreferrer noopener"'));
});

test('raw html, script URLs and remote images never become executable or external loads',()=>{
  const html=render('<script>alert(1)</script>\n\n<img src="https://tracker.test/image" onerror="alert(1)"/>\n\n[恶意链接](javascript:alert%281%29)\n\n![图片](https://tracker.test/image)');
  assert.ok(!html.includes('<script') && !html.includes('<img'));
  assert.ok(!html.includes('href="javascript:') && !html.includes('src="https://tracker.test'));
  assert.ok(html.includes('图片'));
});

test('inline source markup keeps emphasis without nesting block paragraphs',()=>{
  const html=renderToStaticMarkup(<h2><InlineMarkdown text="**员工手册**"/></h2>);
  assert.ok(html.includes('<strong>员工手册</strong>') && !html.includes('<p>'));
});

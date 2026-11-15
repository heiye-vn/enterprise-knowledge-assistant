import assert from 'node:assert/strict';
import test from 'node:test';
import { documentFromApi, reprocessVersion, uploadDocument } from '../src/api.ts';

test('uploaded metadata keeps unknown page count and cannot become queryable', () => {
  const doc = documentFromApi({
    id: 'd1', title: '制度', category: '未分类', filename: '制度.md', size_bytes: 10,
    version_id: 'v1', version_label: null, version_no: 1, format: 'md', page_count: null,
    file_url: '/api/document-versions/v1/file', status: 'failed', can_query: false,
    latest_processing: { job_id: 'j1', version_id: 'v1', status: 'failed', stage: 'parsing',
      error: {code: 'parser_not_configured', message: '原件已保存，解析功能尚未接入', retryable: false},
      attempt_no: 1, max_attempts: 3 },
  });
  assert.equal(doc.pageCount, null);
  assert.equal(doc.canQuery, false);
  assert.equal(doc.status, 'stored');
  assert.equal(doc.fileUrl, '/api/document-versions/v1/file');
  assert.deepEqual(doc.pages, []);
});

test('canceled jobs remain canceled and do not appear to be processing', () => {
  const doc = documentFromApi({id:'d', title:'制度', category:'未分类', filename:'制度.pdf',
    size_bytes:10, version_id:'v', version_no:1, format:'pdf', page_count:null, status:'canceled',
    can_query:false, file_url:'/api/document-versions/v/file', latest_processing:null});
  assert.equal(doc.status, 'canceled');
});

test('upload retry sends the same stable document id and actual file bytes', async () => {
  const file = new File(['# 原件'], '制度.md');
  const ids: FormDataEntryValue[] = [];
  let attempts = 0;
  const request = async (_url: string, init?: RequestInit) => {
    const form = init?.body as FormData;
    ids.push(form.get('document_id')!);
    assert.equal(await (form.get('file') as File).text(), '# 原件');
    if (++attempts === 1) return Response.json({detail:'暂时不可用'}, {status:503});
    return Response.json({document_id:'stable',version_id:'v',job_id:'j',duplicate:false}, {status:202});
  };
  await assert.rejects(uploadDocument(file,'stable',undefined,request), /暂时不可用/);
  assert.equal((await uploadDocument(file,'stable',undefined,request)).version_id, 'v');
  assert.deepEqual(ids, ['stable','stable']);
});

test('parsed metadata remains unavailable for questions', () => {
  const doc = documentFromApi({id:'d',title:'制度',category:'未分类',filename:'制度.pdf',size_bytes:10,
    version_id:'v',version_no:1,format:'pdf',page_count:3,status:'parsed',can_query:false,latest_processing:null});
  assert.equal(doc.status,'parsed');
  assert.equal(doc.canQuery,false);
  assert.equal(doc.pageCount,3);
});

test('reprocess retry uses the same request identity and a fixed version', async () => {
  const calls: [string, RequestInit | undefined][] = [];
  const request = async (url:string, init?:RequestInit) => {
    calls.push([url,init]);
    return Response.json({job_id:'stable',version_id:'old-version'},{status:202});
  };
  await reprocessVersion('old-version','stable',request);
  await reprocessVersion('old-version','stable',request);
  assert.deepEqual(calls.map(([url,init]) => [url,JSON.parse(init?.body as string)]),[
    ['/api/document-versions/old-version/reprocess',{job_id:'stable'}],
    ['/api/document-versions/old-version/reprocess',{job_id:'stable'}],
  ]);
});

test('search keeps explicit scope and fixed source version and job', async () => {
  const api = await import('../src/api.ts');
  const calls: [string, RequestInit | undefined][] = [];
  const request = async (url:string, init?:RequestInit) => {
    calls.push([url,init]);
    return Response.json({items:[],snapshot:{documents:[]},warnings:[],degraded:false});
  };
  await api.searchKnowledge('报销审批', ['doc-one'], undefined, request);
  assert.deepEqual(JSON.parse(calls[0][1]?.body as string), {question:'报销审批',document_ids:['doc-one'],top_k:6});
  await api.getParsedVersion('old-version', undefined, 'old-job', request);
  await api.listChunks('old-version', 'old-job', 50, undefined, request);
  assert.equal(calls[1][0], '/api/document-versions/old-version/parsed?job_id=old-job');
  assert.equal(calls[2][0], '/api/document-versions/old-version/chunks?offset=50&limit=50&job_id=old-job');
});

test('reindex retry reuses request identity without reparsing', async () => {
  const {reindexVersion} = await import('../src/api.ts');
  const calls: string[] = [];
  const request = async (url:string, init?:RequestInit) => {
    calls.push(url);
    assert.deepEqual(JSON.parse(init?.body as string), {job_id:'stable-index'});
    return Response.json({job_id:'stable-index'},{status:202});
  };
  await reindexVersion('v-one','stable-index',request);
  await reindexVersion('v-one','stable-index',request);
  assert.deepEqual(calls, ['/api/document-versions/v-one/reindex','/api/document-versions/v-one/reindex']);
});

test('published document continues polling while a newer job runs', async () => {
  const {isProcessing,statusNames} = await import('../src/document-types.ts');
  const doc = documentFromApi({id:'d',title:'制度',category:'未分类',filename:'制度.pdf',size_bytes:10,
    version_id:'v',version_no:1,format:'pdf',page_count:3,status:'ready',can_query:true,
    latest_processing:{job_id:'new-job',version_id:'v',status:'running',stage:'embedding',error:null,attempt_no:1,max_attempts:3}});
  assert.equal(isProcessing(doc),true);
  assert.equal(statusNames.ready,'可检索');
});

test('chat can create an empty session and sends only the current question', async () => {
  const api=await import('../src/api.ts');
  const calls:[string,RequestInit | undefined][]=[];
  const request=async(url:string,init?:RequestInit)=>{calls.push([url,init]);return Response.json({id:'s',user:{id:'u'},assistant:{id:'a'}});};
  await api.createChatSession('s',request);
  await api.sendChat('s','r','报销怎么审批？',request);
  assert.deepEqual(calls.map(([url,init])=>[url,JSON.parse(init?.body as string)]),[
    ['/api/sessions',{id:'s'}],['/api/chat',{session_id:'s',client_request_id:'r',text:'报销怎么审批？'}],
  ]);
});

test('delete chat uses DELETE with the chosen session id', async () => {
  const {deleteChatSession}=await import('../src/api.ts');
  let call:unknown;
  await deleteChatSession('session-one',async(url,init)=>{call=[url,init?.method];return new Response(null,{status:204});});
  assert.deepEqual(call,['/api/sessions/session-one','DELETE']);
});

test('explicit chat retry preserves request identity and advances only its attempt', async () => {
  const {retryChat}=await import('../src/api.ts');
  const calls:unknown[]=[];
  const request=async(url:string,init?:RequestInit)=>{calls.push([url,JSON.parse(init?.body as string)]);return Response.json({user:{id:'same-user'},assistant:{id:'same-assistant'}});};
  await retryChat('session-one','request-one','原来的问题',2,request);
  await retryChat('session-one','request-one','原来的问题',2,request);
  assert.deepEqual(calls,[
    ['/api/chat',{session_id:'session-one',client_request_id:'request-one',text:'原来的问题',retry_attempt:2}],
    ['/api/chat',{session_id:'session-one',client_request_id:'request-one',text:'原来的问题',retry_attempt:2}],
  ]);
});

test('stream and stop preserve the explicitly selected web option',async()=>{
  const {streamChat,stopChat}=await import('../src/api.ts');
  const bodies:Record<string,unknown>[]=[];
  const pair={user:{id:'u',role:'user',content:'question',status:'completed'},assistant:{id:'a',role:'assistant',content:'done',status:'completed'}};
  const request=async(url:string,init?:RequestInit)=>{
    bodies.push(JSON.parse(init?.body as string));
    if(url.endsWith('/stop'))return new Response(JSON.stringify(pair),{headers:{'Content-Type':'application/json'}});
    return new Response(`event: start\ndata: ${JSON.stringify(pair)}\n\nevent: done\ndata: ${JSON.stringify(pair)}\n\n`,{headers:{'Content-Type':'text/event-stream'}});
  };
  await streamChat('s','r','question',()=>{},new AbortController().signal,2,true,request);
  await stopChat('s','r','question',2,true,request);
  assert.equal(bodies[0].web_search,true);assert.equal(bodies[0].retry_attempt,2);
  assert.equal(bodies[1].web_search,true);assert.equal(bodies[1].attempt_no,2);
});

test('document deletion targets one document and exposes processing errors',async()=>{
  const {deleteDocument}=await import('../src/api.ts');
  let called='';
  await deleteDocument('chosen',async(url,init)=>{called=url;assert.equal(init?.method,'DELETE');return new Response(null,{status:204});});
  assert.equal(called,'/api/documents/chosen');
  await assert.rejects(deleteDocument('chosen',async()=>new Response(JSON.stringify({detail:'文档正在处理'}),{status:409,headers:{'Content-Type':'application/json'}})),/正在处理/);
});

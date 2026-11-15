import type {GraphResponse, GraphJob} from './graph-api-types';
import type {AnswerMode, ExecutionDetails, WebSource} from './retrieval-types';
import type {DocumentVersion, ImportAccepted, ImportStatus, KnowledgeDocument, ParsedResponse, ProcessingInfo, ChunkSource, SearchResponse} from './document-types.ts';

type Fetcher = (url: string, init?: RequestInit) => Promise<Response>;
type DocumentDto = {
  id: string; title: string; category: string; filename: string | null; size_bytes: number | null;
  version_id: string | null; version_label?: string | null; version_no: number | null;
  format: string | null; page_count: number | null; file_url?: string | null;
  status: string; can_query: boolean; latest_processing: ProcessingInfo | null;
};

async function readResponse(response: Response) {
  let body;
  try { body = await response.json(); } catch { throw new Error('服务响应异常，请稍后重试。'); }
  if (!response.ok) {
    throw Object.assign(new Error(typeof body.detail === 'string' ? body.detail : body.detail?.message ?? '服务暂时不可用，请稍后重试。'),{status:response.status});
  }
  return body;
}

export function documentFromApi(value: DocumentDto): KnowledgeDocument {
  const status = value.latest_processing?.error?.code === 'parser_not_configured' && !value.can_query
    ? 'stored' : value.status as ImportStatus;
  return {
    id: value.id, title: value.title, category: value.category, filename: value.filename ?? '',
    size: value.size_bytes ?? 0, version: value.version_label ?? String(value.version_no ?? ''),
    versionNo: value.version_no, versionId: value.version_id, format: value.format ?? '',
    fileUrl: value.file_url ?? undefined, pageCount: value.page_count, pages: [], status,
    canQuery: value.can_query, latestProcessing: value.latest_processing,
  };
}

export async function listDocuments(signal?: AbortSignal): Promise<KnowledgeDocument[]> {
  const documents = new Map<string, KnowledgeDocument>();
  let offset = 0;
  let total = 1;
  while (offset < total) {
    const body = await readResponse(await fetch(`/api/documents?offset=${offset}&limit=100`, {signal}));
    if (!Array.isArray(body.items) || !Number.isInteger(body.total)) throw new Error('文档列表响应异常');
    for (const item of body.items) documents.set(item.id, documentFromApi(item));
    total = body.total;
    if (!body.items.length) break;
    offset += body.items.length;
  }
  return [...documents.values()];
}

export async function uploadDocument(file: File, documentId: string, versionTarget?: string, request: Fetcher = fetch): Promise<ImportAccepted> {
  const form = new FormData();
  form.append('file', file);
  if (!versionTarget) form.append('document_id', documentId);
  const path = versionTarget ? `/api/documents/${versionTarget}/versions` : '/api/documents';
  const body = await readResponse(await request(path, {method:'POST',body:form}));
  if (typeof body.document_id !== 'string' || typeof body.version_id !== 'string' || typeof body.duplicate !== 'boolean') {
    throw new Error('上传响应异常，请使用同一文件重试。');
  }
  return body;
}

export async function listVersions(documentId: string, signal?: AbortSignal): Promise<DocumentVersion[]> {
  return (await readResponse(await fetch(`/api/documents/${documentId}/versions`, {signal}))).items;
}

export async function retryJob(jobId: string) {
  return readResponse(await fetch(`/api/processing-jobs/${jobId}/retry`, {method:'POST'}));
}

export async function getParsedVersion(versionId: string, signal?: AbortSignal, jobId?: string | null, request: Fetcher = fetch): Promise<ParsedResponse> {
  return readResponse(await request(`/api/document-versions/${versionId}/parsed${jobId ? `?job_id=${encodeURIComponent(jobId)}` : ''}`, {signal}));
}

export async function reprocessVersion(versionId: string, jobId: string, request: Fetcher = fetch) {
  return readResponse(await request(`/api/document-versions/${versionId}/reprocess`, {
    method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify({job_id:jobId}),
  }));
}

export async function reindexVersion(versionId:string, jobId:string, request:Fetcher = fetch) {
  return readResponse(await request(`/api/document-versions/${versionId}/reindex`, {
    method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify({job_id:jobId}),
  }));
}

export async function searchKnowledge(question:string, documentIds:string[] | null, signal?:AbortSignal, request:Fetcher = fetch):Promise<SearchResponse> {
  return readResponse(await request('/api/search', {method:'POST', signal,
    headers:{'Content-Type':'application/json'},
    body:JSON.stringify({question,...(documentIds === null ? {} : {document_ids:documentIds}),top_k:6}),
  }));
}

export async function listChunks(versionId:string, jobId?:string | null, offset=0, signal?:AbortSignal, request:Fetcher = fetch):Promise<{items:ChunkSource[];total:number}> {
  const query = new URLSearchParams({offset:String(offset),limit:'50'});
  if (jobId) query.set('job_id',jobId);
  return readResponse(await request(`/api/document-versions/${versionId}/chunks?${query}`,{signal}));
}

export type ChatCitation = {citation_no:number;quote:string;source:ChunkSource};
export type ChatMessageDto = {id:string;role:'user'|'assistant';content:string;status:string;answer_kind:string | null;answer_mode?:AnswerMode;web_search_requested?:boolean;web_sources?:WebSource[];stream_phase?:string|null;stop_reason?:string|null;details?:ExecutionDetails|null;warnings?:{code:string;message:string}[];citations:ChatCitation[];error:{code:string;message:string;retryable?:boolean} | null;client_request_id?:string | null;attempt_no?:number;max_attempts?:number};
export type ChatSessionDto = {id:string;title:string;updated_at:string};
export async function createChatSession(id:string,request:Fetcher=fetch):Promise<ChatSessionDto> {
  return readResponse(await request('/api/sessions',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({id})}));
}
export async function listChatSessions(signal?:AbortSignal):Promise<ChatSessionDto[]> {
  return (await readResponse(await fetch('/api/sessions',{signal}))).items;
}
export async function getChatSession(id:string,signal?:AbortSignal):Promise<ChatSessionDto & {messages:ChatMessageDto[]}> {
  return readResponse(await fetch(`/api/sessions/${id}`,{signal}));
}
export async function sendChat(sessionId:string,requestId:string,text:string,request:Fetcher=fetch):Promise<{user:ChatMessageDto;assistant:ChatMessageDto}> {
  return readResponse(await request('/api/chat',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({session_id:sessionId,client_request_id:requestId,text})}));
}

export async function deleteChatSession(id:string,request:Fetcher=fetch):Promise<void> {
  const response=await request(`/api/sessions/${id}`,{method:'DELETE'});
  if(!response.ok)await readResponse(response);
}


export async function retryChat(sessionId:string,requestId:string,text:string,retryAttempt:number,request:Fetcher=fetch):Promise<{user:ChatMessageDto;assistant:ChatMessageDto}> {
  return readResponse(await request('/api/chat',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({session_id:sessionId,client_request_id:requestId,text,retry_attempt:retryAttempt})}));
}

export async function streamChat(sessionId:string,requestId:string,text:string,onEvent:(event:ChatStreamEvent)=>void,signal:AbortSignal,retryAttempt?:number,webSearch=false,request:Fetcher=fetch):Promise<ChatPair>{
  const response=await request('/api/chat/stream',{method:'POST',signal,headers:{'Content-Type':'application/json'},body:JSON.stringify({session_id:sessionId,client_request_id:requestId,text,web_search:webSearch,...(retryAttempt?{retry_attempt:retryAttempt}:{})})});
  if(!response.ok)await readResponse(response);
  return consumeChatStream(response,onEvent);
}
export async function stopChat(sessionId:string,requestId:string,text:string,attemptNo:number,webSearch=false,request:Fetcher=fetch):Promise<ChatPair>{
  return readResponse(await request('/api/chat/stop',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({session_id:sessionId,client_request_id:requestId,text,attempt_no:attemptNo,web_search:webSearch})}));
}

export async function getKnowledgeGraph(documentId:string|null,signal?:AbortSignal,request:Fetcher=fetch):Promise<GraphResponse> {
  return readResponse(await request(`/api/graph${documentId?`?document_id=${encodeURIComponent(documentId)}`:''}`,{signal}));
}
export async function buildKnowledgeGraph(documentIds:string[]|null,request:Fetcher=fetch):Promise<{jobs:GraphJob[];created:number}> {
  return readResponse(await request('/api/graph/build',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(documentIds?{document_ids:documentIds}:{})}));
}
import {consumeChatStream} from './chat-stream.ts';
import type {ChatPair,ChatStreamEvent} from './chat-stream.ts';

export async function deleteDocument(id:string,request:Fetcher=fetch):Promise<void> {
  const response=await request(`/api/documents/${id}`,{method:'DELETE'});
  if(!response.ok)await readResponse(response);
}

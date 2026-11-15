export type ImportStatus = 'queued' | 'parsing' | 'parsed' | 'chunking' | 'embedding' | 'ready' | 'failed' | 'canceled' | 'stored';
export type ProcessingInfo = {
  job_id: string; version_id: string; status: string; stage: string; display_status?: ImportStatus;
  error: {code: string; message: string; retryable: boolean} | null;
  attempt_no: number; max_attempts: number;
};
export type KnowledgeDocument = {
  id: string; title: string; filename: string; category: string; size: number; version: string;
  versionId: string | null; versionNo: number | null; format: string;
  pages: string[]; pageCount: number | null; fileUrl?: string; status: ImportStatus;
  canQuery: boolean; latestProcessing: ProcessingInfo | null; sha256?: string;
};
export type DocumentVersion = {id: string; version_no: number; filename: string; format: string; size_bytes: number; file_url: string};
export type ImportAccepted = {document_id: string; version_id: string; job_id: string | null; duplicate: boolean};
export type Source = {documentId: string; clause: string; chapter: string; page: number; quote: string; table?: string[][]};
export type Message = {id: string; role: 'user' | 'assistant'; text?: string};
export type ParsedBlock = {
  block_id: string; type: string; text: string; heading_path: string[];
  page_start: number | null; page_end: number | null; level?: number; asset_url?: string;
  rows?: {text: string; header: boolean; colspan: number; rowspan: number}[][];
  captions?: string[]; footnotes?: string[];
};
export type ParsedResult = {job_id: string; version_id: string; generation_no: number;
  markdown: string; blocks: ParsedBlock[]; page_count: number | null; created_at: string};
export type ParsedResponse = {document_removed?:boolean;result: ParsedResult | null; latest_processing: ProcessingInfo | null};

export const statusNames: Record<ImportStatus, string> = {
  queued: '等待处理', parsing: '解析文档', chunking: '生成切片', embedding: '建立索引',
  ready: '可检索', parsed: '解析完成', failed: '处理失败', canceled: '已取消', stored: '原件已保存',
};
export const isProcessing = (doc: KnowledgeDocument) => ['queued','parsing','chunking','embedding'].includes(doc.status) || ['queued','running'].includes(doc.latestProcessing?.status ?? '');
export function fileSize(bytes: number): string {
  return bytes < 1024 * 1024 ? `${Math.max(1, Math.round(bytes / 1024))} KB` : `${(bytes / 1024 / 1024).toFixed(1)} MB`;
}

export type ChunkSource = {
  id:string; document_id:string; document_title:string; version_id:string; version_no:number;
  job_id:string; generation_no:number; filename:string; format:string; ordinal:number;
  content:string; heading_path:string[]; page_start:number | null; page_end:number | null;
  locators:{block_id:string;start?:number;end?:number;row_start?:number;row_end?:number}[];
  file_url:string;
};
export type SearchResponse = {items:ChunkSource[];degraded:boolean;warnings:{code:string;message:string}[];
  snapshot:{documents:{document_id:string;version_id:string;job_id:string}[]}};

import type {ChunkSource} from './document-types';

export type AnswerMode='general'|'knowledge'|'clarify'|'web';
export type WebSource={number:number;title:string;url:string;content?:string;score?:number|null};
export type WebSearchTrace={provider:string;query?:string;queried_at?:string;status:'running'|'completed'|'failed'|'skipped';reason?:string;results:WebSource[];used_numbers?:number[]};
export type ExecutionStage={key:string;status:'completed'|'failed'|'skipped';duration_ms:number|null;note?:string};
export type RetrievalCandidate={
  source:ChunkSource;excerpt_truncated?:boolean;
  graph_expanded?:boolean;
  scores:{bm25:number|null;vector_distance:number|null;rrf:number|null;rerank:number|null};
  ranks:{bm25:number|null;vector:number|null;fusion:number|null;rerank:number|null};
  selected:boolean;sent_to_model?:boolean;used_in_answer?:boolean;citation_no?:number|null;
};
export type GraphPathEvidence={source:ChunkSource;quote:string;conditions:string[]};
export type GraphRetrievalTrace={enabled:boolean;status:'completed'|'skipped'|'failed';reason:string|null;seed_count:number;added_count:number;candidate_ids:string[];paths:{nodes:string[];relations:string[];from:GraphPathEvidence;to:GraphPathEvidence;used_in_answer?:boolean}[]};
export type RetrievalTrace={query:string;stages:ExecutionStage[];graph?:GraphRetrievalTrace;
  counts:{documents:number;bm25:number;vector:number;fusion:number;rerank_input:number;returned:number};
  candidates:RetrievalCandidate[]};
export type ExecutionDetails={version:number;intent:{mode:AnswerMode;decision:string;query:string|null}|null;
  stages:ExecutionStage[];retrieval:RetrievalTrace|null;outcome:string;total_ms:number|null;web?:WebSearchTrace;trace_id?:string};

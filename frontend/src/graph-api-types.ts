import type {KnowledgeGraph} from './graph-model';
import type {ChunkSource} from './document-types';
export type GraphJob={id:string|null;document_id:string;title:string;status:string;stage:string;
  attempt_no:number;max_attempts:number;error:{code:string;message:string;retryable:boolean}|null;
  processed_units:number;total_units:number;rule_count:number;relation_count:number;rejected_count:number;
  unit_limit_reached:boolean;has_previous:boolean;needs_update:boolean;source_job_id:string|null};
export type GraphEvidenceDto={source:ChunkSource;quote:string;scope:string;conditions:string[]};
export type GraphResponse=KnowledgeGraph&{root_ids:string[];sources:Record<string,GraphEvidenceDto>;
  jobs:GraphJob[];available:boolean;error:{code:string;message:string}|null;truncated:boolean;fingerprint:string};

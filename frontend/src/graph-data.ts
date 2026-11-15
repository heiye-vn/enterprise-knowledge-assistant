import type { GraphNodeKind, KnowledgeGraph } from './graph-model';

export type GraphScenario = string;
export const graphKinds: { id: GraphNodeKind; label: string; color: string; symbol: 'roundRect' | 'circle' | 'diamond' | 'triangle' | 'rect' }[] = [
  { id: 'document', label: '制度文档', color: '#3975db', symbol: 'roundRect' },
  { id: 'matter', label: '事项', color: '#9b6bce', symbol: 'circle' },
  { id: 'rule', label: '适用规则', color: '#15978a', symbol: 'diamond' },
  { id: 'role', label: '岗位 / 部门', color: '#ca872b', symbol: 'triangle' },
  { id: 'material', label: '证明 / 票据', color: '#697bb8', symbol: 'rect' },
];

export const graphScenarios: { id: GraphScenario; title: string; description: string; rootIds: string[]; graph: KnowledgeGraph }[] = [];

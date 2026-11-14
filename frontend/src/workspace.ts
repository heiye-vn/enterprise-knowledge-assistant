import type { Message } from './demo';

export type View = 'chat' | 'documents' | 'graph';
export type Conversation = {
  id: string;
  title: string;
  messages: Message[];
  documentIds: string[] | null;
  updatedAt: number;
};
export type DocumentStatusFilter = 'all' | 'ready' | 'processing' | 'failed';
export type DocumentFilters = { category: string | null; status: DocumentStatusFilter };
export type { GraphScenario } from './graph-data';
export type { GraphNodeKind } from './graph-model';
export { graphScenarios } from './graph-data';

export const sidebarLabels: Record<View, string> = {
  chat: '会话导航', documents: '文档分类与筛选', graph: '图谱探索与筛选',
};

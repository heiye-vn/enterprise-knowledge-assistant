import seed from './demo-documents.json';
import sourceSeed from './demo-sources.json';

export type ImportStatus = 'queued' | 'parsing' | 'chunking' | 'embedding' | 'ready' | 'failed';
export type KnowledgeDocument = {
  id: string; title: string; filename: string; category: string; size: number; version: string;
  pages: string[]; fileUrl?: string; status: ImportStatus; demoUpload?: boolean;
};
export type Source = {
  id: string; documentId: string; clause: string; chapter: string; page: number;
  quote: string; table?: string[][];
};
export type Answer = { title: string; paragraphs: string[]; sources: string[]; note?: string };
export type Message = { id: string; role: 'user' | 'assistant'; text?: string; answer?: Answer };

export const initialDocuments: KnowledgeDocument[] = seed.map(doc => ({ ...doc, status: 'ready' }));

export const sources: Record<string, Source> = sourceSeed;

export const openingQuestion = '员工请半天事假，应遵循哪份制度？由谁审批？';
export const leaveAnswer: Answer = {
  title: '半天事假，原则上由直属主管审批。',
  paragraphs: [
    '员工手册要求按照《考勤与休假管理制度》申请休假。[handbook]',
    '半天属于“不超过 1 个工作日”的情形，对应审批人为直属主管。申请时需在办公系统填写假期类型、起止时间、请假事由、工作交接人及必要附件。[leave]',
  ],
  sources: ['handbook', 'leave'],
  note: '请取得系统审批结果后，再按批准时间休假。',
};
export const initialMessages: Message[] = [
  { id: 'opening-question', role: 'user', text: openingQuestion },
  { id: 'opening-answer', role: 'assistant', answer: leaveAnswer },
];
export const suggestedQuestions = ['那四天事假呢？', '电子发票截图可以报销吗？', '外部培训费用按什么制度报销？'];

// 仅用于交互原型的固定场景，不执行检索、调用模型或评估用户文件。
export function getDemoAnswer(question: string, previous: Message[]): Answer {
  if (/截图|电子发票|OFD/i.test(question)) return {
    title: '截图不能替代原始电子票据。',
    paragraphs: ['报销时应上传电子发票的原始 PDF 或 OFD 文件。手机截图只能作为辅助说明，不能直接替代原件。[invoice]'],
    sources: ['invoice'],
  };
  if (/培训/.test(question)) return {
    title: '外部培训费用按《费用报销管理制度》及培训审批流程办理。',
    paragraphs: ['员工手册第二十三条明确引用了费用报销制度。[training]', '如提交电子发票，还应保留原始 PDF 或 OFD 文件，截图不能替代原始票据。[invoice]'],
    sources: ['training', 'invoice'],
  };
  if (/(四|4).*(天|日)/.test(question) && (/事假/.test(question) || previous.some(m => m.role === 'user' && /事假/.test(m.text ?? '')))) return {
    title: '四个工作日的事假，需直属主管与部门负责人审批。',
    paragraphs: ['沿用前文的事假情形，四个工作日属于“超过 3 个工作日”，流程为：直属主管 → 部门负责人 → 人力资源部备案。[leave]'],
    sources: ['leave'], note: '人力资源部在此流程中承担备案职责。',
  };
  if (/半天|请假.*审批/.test(question)) return leaveAnswer;
  return {
    title: '这个问题还没有接入真实问答服务。',
    paragraphs: ['当前是交互原型，仅提供请假审批、电子发票和外部培训三个固定示例。可以点击下方的示例问题体验；真实检索、拒答与模型生成将在后端接入后实现。'],
    sources: [],
  };
}

export const statusNames: Record<ImportStatus, string> = {
  queued: '等待处理', parsing: '解析文档', chunking: '生成切片', embedding: '建立索引', ready: '可问答', failed: '处理失败',
};

export function fileSize(bytes: number): string {
  return bytes < 1024 * 1024 ? `${Math.max(1, Math.round(bytes / 1024))} KB` : `${(bytes / 1024 / 1024).toFixed(1)} MB`;
}

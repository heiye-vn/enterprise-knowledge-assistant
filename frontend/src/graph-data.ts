import type { GraphNodeKind, KnowledgeGraph } from './graph-model';

export type GraphScenario = 'leave' | 'training';
export const graphKinds: { id: GraphNodeKind; label: string; color: string; symbol: 'roundRect' | 'circle' | 'diamond' | 'triangle' | 'rect' }[] = [
  { id: 'document', label: '制度文档', color: '#3975db', symbol: 'roundRect' },
  { id: 'matter', label: '事项', color: '#9b6bce', symbol: 'circle' },
  { id: 'rule', label: '适用规则', color: '#15978a', symbol: 'diamond' },
  { id: 'role', label: '岗位 / 部门', color: '#ca872b', symbol: 'triangle' },
  { id: 'material', label: '证明 / 票据', color: '#697bb8', symbol: 'rect' },
];
const leaveGraph: KnowledgeGraph = {
  nodes: [
    { id: 'leave-handbook', title: '员工手册', detail: '第九条 · 考勤与请假', kind: 'document', sources: ['handbook'] },
    { id: 'leave-policy', title: '考勤与休假管理制度', detail: '第十一条 · 申请审批流程', kind: 'document', sources: ['leave'] },
    { id: 'leave-short', title: '不超过 1 个工作日', detail: '请假时长 ≤ 1 个工作日，由直属主管审批。', kind: 'rule', sources: ['leave'] },
    { id: 'leave-medium', title: '超过 1 个且不超过 3 个工作日', detail: '1 < 请假时长 ≤ 3 个工作日，直属主管 → 部门负责人审批。', kind: 'rule', sources: ['leave'] },
    { id: 'leave-long', title: '超过 3 个工作日', detail: '请假时长 > 3 个工作日，直属主管 → 部门负责人审批 → 人力资源部备案。', kind: 'rule', sources: ['leave'] },
    { id: 'leave-supervisor', title: '直属主管', detail: '请假审批岗位，具体层级取决于请假时长。', kind: 'role', sources: ['leave'] },
    { id: 'leave-head', title: '部门负责人', detail: '超过 1 个工作日的请假，在直属主管之后审批。', kind: 'role', sources: ['leave'] },
    { id: 'leave-hr', title: '人力资源部', detail: '超过 3 个工作日的请假，经审批后由人力资源部备案。', kind: 'role', sources: ['leave'] },
  ],
  edges: [
    { id: 'leave-reference', source: 'leave-handbook', target: 'leave-policy', label: '引用制度', sources: ['handbook'] },
    ...['short', 'medium', 'long'].map(tier => ({ id: `leave-rule-${tier}`, source: 'leave-policy', target: `leave-${tier}`, label: '包含时长规则', sources: ['leave'] })),
    { id: 'leave-short-approve', source: 'leave-short', target: 'leave-supervisor', label: '主管审批', sources: ['leave'] },
    { id: 'leave-medium-first', source: 'leave-medium', target: 'leave-supervisor', label: '第 1 步审批', sources: ['leave'] },
    { id: 'leave-medium-second', source: 'leave-medium', target: 'leave-head', label: '第 2 步审批', sources: ['leave'] },
    { id: 'leave-long-first', source: 'leave-long', target: 'leave-supervisor', label: '第 1 步审批', sources: ['leave'] },
    { id: 'leave-long-second', source: 'leave-long', target: 'leave-head', label: '第 2 步审批', sources: ['leave'] },
    { id: 'leave-long-record', source: 'leave-long', target: 'leave-hr', label: '审批后备案', sources: ['leave'] },
  ],
};
const trainingGraph: KnowledgeGraph = {
  nodes: [
    { id: 'training-handbook', title: '员工手册', detail: '第二十三条 · 培训', kind: 'document', sources: ['training'] },
    { id: 'training-matter', title: '外部培训', detail: '事前批准、费用报销和课程采购分别遵循适用制度。', kind: 'matter', sources: ['training'] },
    { id: 'training-approval', title: '事前批准', detail: '外部培训应按公司培训审批流程事前批准。原文未明确该流程的具体审批岗位。', kind: 'rule', sources: ['training'] },
    { id: 'training-finance', title: '费用报销管理制度', detail: '培训费用按本制度的费用标准、审批和票据要求办理。', kind: 'document', sources: ['training', 'invoice'] },
    { id: 'training-procurement', title: '采购管理制度', detail: '涉及采购培训课程、培训服务或供应商服务时，履行采购审批、合同和验收流程。', kind: 'document', sources: ['training'] },
    { id: 'training-invoice', title: '电子发票', detail: '费用报销管理制度第十条 · 发票要求', kind: 'material', sources: ['invoice'] },
    { id: 'training-original', title: '原始 PDF / OFD', detail: '电子发票应上传原始 PDF 或 OFD 文件。', kind: 'material', sources: ['invoice'] },
    { id: 'training-screenshot', title: '截图仅用于辅助说明', detail: '截图不替代原始电子票据。', kind: 'rule', sources: ['invoice'] },
  ],
  edges: [
    { id: 'training-topic', source: 'training-handbook', target: 'training-matter', label: '涉及事项', sources: ['training'] },
    { id: 'training-before', source: 'training-matter', target: 'training-approval', label: '要求事前批准', sources: ['training'] },
    { id: 'training-expense', source: 'training-matter', target: 'training-finance', label: '费用报销遵循', sources: ['training'] },
    { id: 'training-purchase', source: 'training-matter', target: 'training-procurement', label: '采购课程或服务时适用', sources: ['training'] },
    { id: 'training-bill', source: 'training-finance', target: 'training-invoice', label: '规定票据要求', sources: ['invoice'] },
    { id: 'training-upload', source: 'training-invoice', target: 'training-original', label: '需上传原件', sources: ['invoice'] },
    { id: 'training-limit', source: 'training-invoice', target: 'training-screenshot', label: '使用限制', sources: ['invoice'] },
  ],
};

export const graphScenarios: { id: GraphScenario; title: string; description: string; rootIds: string[]; graph: KnowledgeGraph }[] = [
  { id: 'leave', title: '请假与审批规则', description: '制度引用 · 时长条件 · 审批岗位', rootIds: ['leave-policy'], graph: leaveGraph },
  { id: 'training', title: '外部培训与电子票据', description: '制度引用 · 事前批准 · 票据要求', rootIds: ['training-matter'], graph: trainingGraph },
];

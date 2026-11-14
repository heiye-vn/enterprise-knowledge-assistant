# 企业知识助理：首版设计与验收标准

日期：2026-11-13。交付窗口：2026-11-14 至 2026-11-15；面试题截止时间：2026-11-16 上午。

## 1. 目标与边界

开发独立的 Python + React 企业制度问答应用。原 Knowledge Hub 只作参考，业务代码、数据库、对象桶、队列和图数据库均属于新项目。

首版必须完成：PDF/DOCX/Markdown 上传、异步解析与索引、制度检索问答、原文溯源、无依据拒答、会话内追问、固定问题集评测。

加分项：四份制度的定向实体关系抽取、可溯源图谱、两个基于跨制度证据的多跳问答示例。核心问答与引用验收完成后再实现图谱。

本次不包含：登录注册、账号鉴权、长期个人记忆、联网搜索、自由生成 Cypher 的 Agent、通用审批系统、图谱社区发现。会话记录持久化属于历史恢复，不等同于长期记忆。

## 2. 项目位置与资料

- 项目根目录：本文件上一级的 `project/`；当前工作目录为 `/Users/shunpingzi/Desktop/AI-Agent/企业知识助理/project`。
- 选用语料：`../version_chatgpt/知识库语料` 中的四份制度，PDF 为首批验收输入；DOCX 同样属于支持的上传格式。
- 评测来源：`../version_chatgpt/独立评测集/RAG标准评测集.jsonl`，40 题，其中 34 题标记可回答、6 题标记不可直接回答。
- Gemini、Qwen 资料不混入同一知识库；可以借鉴题型，新增问题的答案必须重新依据选定制度标注。
- 评测问题、标准答案、证据摘要不得进入文档检索索引。
- 不修改三套原始资料。校准后的评测集放在项目 `eval/`，另存修改原因、依据和相似问题分组。

已确认需要校准：FIN-004 删除原文未明确的住宿例外原因和指定审批人；HB-003 删除原文未明确的事件报告材料和日志要求；MX-003 按实际证据修正跨文档标注。HR-005/MX-001、HB-008/NA-002 分别归为同组问法，避免跨开发集和验收集泄漏相似问题。

## 3. 技术栈与运行约束

| 部分 | 决策 |
| --- | --- |
| Python | 3.12，uv 管理与锁定依赖 |
| 后端 | FastAPI、Pydantic、SQLAlchemy 2、psycopg 3、Alembic |
| 数据 | PostgreSQL 16 + pgvector |
| 消息任务 | Celery + Redis；文档与图谱使用独立队列和 Worker |
| 对象存储 | RustFS，Python 使用 boto3 接入 S3 API |
| 解析 | MinerU 云端 API；Markdown 在本地读取 |
| 检索 | jieba + rank-bm25、pgvector、RRF、阿里 Rerank |
| 模型 | 聊天模型可选阿里或 OpenAI；Embedding/Rerank 使用阿里 |
| 图谱 | Neo4j + 官方 Python 驱动；受控 Cypher |
| 前端 | React、TypeScript、Vite、Vercel AI SDK |
| 界面 | Tailwind CSS、少量 shadcn/ui、Lucide |
| 阅读与图谱 | react-pdf、react-markdown、remark-gfm、Apache ECharts（graph 力导向关系图） |
| 验证 | pytest、Vitest、JSONL 真实链路评测 |
| 本地部署 | Docker Compose 启动 PostgreSQL、Redis、RustFS、Neo4j |

2026-11-13 选型复核：RustFS 官方已发布 [1.0.5 正式版本](https://github.com/rustfs/rustfs/releases/tag/1.0.5)，采用 Apache 2.0 许可证；其 [S3 兼容矩阵](https://github.com/rustfs/rustfs/blob/1.0.5/docs/architecture/s3-compatibility-matrix.md)列明对象上传、读取、删除、列表、HEAD 与 Range 读取的支持范围，不宣称覆盖所有 S3 行为。本项目选择单节点 Docker 部署和独立命名卷，使用 boto3 验证实际需要的接口；2026-11-14 已实际拉取 1.0.5，完成所需 S3 操作与重建持久化验证，并在 Compose 中锁定标签和 digest，记录见[后端基础验证](dev-notes/backend-foundation.md)。正式版本和活跃发布不能单独证明大规模企业部署成熟度。

FastAPI、PostgreSQL/pgvector、Celery/Redis、Neo4j 与 React/AI SDK 继续保留。jieba 是中文分词库，rank-bm25 是进程内关键词排序库，BM25 与向量仍构成双路检索；库的发版频率不能直接作为弃用依据。四份制度是首批验收样本，页面、接口和数据模型支持后续增加文档。此实现不具备完整搜索服务的多副本索引管理与大规模检索能力；首版不额外引入 Elasticsearch，生产扩容时依据实测重新评估。

全局约束：

- Python 使用 3.12；Node.js 使用 22；pnpm 使用 10。
- 使用 uv.lock 与 pnpm-lock.yaml；服务镜像在实际拉取验证后固定标签，不使用 latest。
- PostgreSQL 是文档、切片、向量、任务和会话的事实来源；Neo4j 是可重建的派生数据。
- 文档正文与列表元数据分开存储，列表接口不加载全文。
- PostgreSQL 内容与向量写入使用同库事务；RustFS、Redis、Neo4j 不伪装成同一事务。
- API Key 仅从环境配置读取；配置示例不包含真实凭证，不从参考项目自动复制密钥。
- 每个业务实体 ID 在接口中使用字符串；同一切片 ID 用于检索、引用和图谱来源关联。
- 数据模型、接口和 UI Message Stream 协议在首个真实安装版本下验证后锁定。
- Celery Worker 和 Beat 在 Linux 容器运行，避免依赖 Windows 原生 Worker 的进程池兼容性。

参考项目示例配置为 `qwen3.7-text-embedding-flash`、1024 维、`qwen3.7-text-rerank`。这些是候选配置，尚未在新项目实际调用；接入时验证账号可用性、返回维度和 API 协议。聊天模型名称由用户后续确定。

## 4. 服务与数据职责

| 存储 | 内容 |
| --- | --- |
| PostgreSQL | 8 张表：documents、document_versions、document_contents、chunks、processing_jobs、chat_sessions、chat_messages、message_citations。分类存文档字段，内容块/范围/请求快照存 JSONB，导入和图谱共用任务表 |
| RustFS | 上传原件、MinerU 解析原始归档、图片及其他解析资源 |
| Redis | Celery 消息代理；不作为任务业务状态或文档内容的唯一存储 |
| Neo4j | Document、Chunk、Matter、Rule、Role、Material 等节点及有来源的关系 |

同步 SQLAlchemy 仓储使用 psycopg 3；FastAPI 异步路由中的阻塞数据库与对象存储操作在线程池执行。Celery 在独立进程中建立连接，不跨进程或事件循环共享连接。

首版单知识库的名称与模型配置来自应用配置，不另建知识库表。字段、事务边界与服务校验详见[8 表设计](superpowers/specs/2026-11-14-database-design.md)及[评审用 DDL](superpowers/specs/2026-11-14-database-schema.sql)。精简存储后，接口继续提供原型需要的分类、状态、来源和图谱结构。

开发端口与旧项目隔离；Compose 使用新项目的网络、容器标识和数据卷。启动前检查冲突，禁止复用或清理旧 Knowledge Hub 的数据卷。

后端镜像供文档 Worker、图谱 Worker 和 Beat 复用；这三个进程在 Linux 容器内运行。原生运行的 FastAPI 使用本机映射端口，容器内 Worker 使用 Compose 服务名连接依赖，两种配置必须分别验证。

## 5. 文档导入与任务恢复

```mermaid
flowchart LR
    U[上传文件] --> O[RustFS 原件]
    O --> P[PG 文档、版本与统一任务行]
    P --> Q[Redis 文档队列]
    Q --> W[Celery 文档 Worker]
    W --> M[MinerU 云端 / MD 直读]
    M --> C[规范化、切片、Embedding]
    C --> V[PG 事务写正文、切片、向量]
    V --> R[文档可问答]
    R --> G[独立图谱队列与 Worker]
    G --> N[Neo4j]
```

上传校验文件扩展名、文件签名、大小和非空内容。新建使用稳定 document_id，更新走显式版本接口；同文档同 hash 复用既有版本。原件保存后，PG 事务创建文档、版本和 job_type=import 的 processing_jobs 行；该任务行也是待投递依据。投递器先更新 next_dispatch_at 和尝试次数再发送，失败或进程退出后由 Beat 扫描补发；Worker 按 job_id、状态和租约令牌幂等认领。

两种任务共用 `queued -> running -> ready` 状态，也可进入 failed/canceled。import 的 stage 为 parsing/chunking/embedding/publishing，graph 的 stage 为 extracting/validating/projecting；前端按类型与阶段显示进度。任务另存错误、可重试性、尝试次数、远端 MinerU 任务 ID、租约和产物位置。

- MinerU 已返回远端任务 ID 后，恢复执行应继续查询该任务。
- 提交请求结果不确定时，不盲目重发；记录明确状态，避免重复计费和重复解析。
- 轮询采用有截止时间的延后检查，不在 HTTP 上传请求中等待全流程。
- 网络、限流和服务端临时故障使用有上限的退避重试；格式错误、凭证缺失不无限重试。
- Worker 可能重复收到消息。租约、阶段检查和数据库唯一约束避免重复文档、切片和图谱关系；进程退出后可恢复过期租约。
- 文本索引已完成时，图谱失败不改变文档可问答状态。

MinerU 通过其云端上传协议接收文件，不依赖云端访问本机 RustFS 地址。保存返回归档，并解析有用的结构化产物，不能只保留 full.md。

## 6. 统一内容块与切片

规范化内容块至少包括：`block_id`、`type`、`text`、`heading_path`、`page_start/page_end`、可选 bbox、原始资源关联。PDF 页码来自真实解析产物；DOCX/MD 支持章节和内容块定位，无页码时返回 null，不伪造 PDF 页码。

应用对外页码统一为从 1 开始。针对 MinerU 实际版本验证其页码基准，在规范化层转换一次，避免阅读器跳错页。

按章、条、段落和表格边界切片。跨页条款保留页码范围；表格行与表头一起进入切片，超长表格按行拆分并重复表头。只有纯段落的过长内容需要再分段和少量重叠。上下文打包保留完整规则或表格，不任意截掉金额、例外条件和列名。

切片存 `id/job_id/version_id/ordinal/content/heading_path/page_start/page_end/content_sha256` 与向量配置；document_id 通过版本关联取得，接口可返回展示别名 chunk_id/pages。正文的 blocks 和切片的 locators 使用 JSONB，发布前验证定位。相同任务重试产生同一切片标识，staging 数据可 upsert；ready 数据不可覆盖，重建使用新 job，历史引用保留旧切片。

## 7. 问答、短期上下文与引用

```text
会话历史 + 本轮问题
  -> 独立检索问题 / 必要澄清
  -> 向量与 BM25 双路检索
  -> RRF 合并
  -> 可选图谱证据扩展与 PG 回查
  -> 阿里 Rerank
  -> 判断证据是否足以回答
  -> 生成带引用回答 / 部分回答 / 明确拒答
  -> AI SDK 流式输出与最终引用校验
```

短期上下文保留最近若干轮并限制 token 预算。历史仅用于消解指代与条件；历史中的助手制度结论不能替代本轮文档。条件未能消解时先澄清，例如“那四天呢”仍无法确定假期种类时不擅自补全。

每个新会话有独立 session_id，PG 保存消息与引用用于恢复。首版不抽取用户档案，不跨会话向量召回个人记忆，不自动引入摘要模型。

会话范围保存在 chat_sessions.scope；发送时固定实际文档、版本、导入/图谱任务和模型配置，写入助手消息的 request_snapshot。助手消息同时承载本轮状态与 client_request_id，不另建问答轮次表；最终正文、引用与 completed 同事务提交。停止和完成锁定同一助手消息处理；历史引用始终打开固定 version_id 的原件。

引用由后端建立本轮有效来源编号，编号映射到真实 chunk_id、文档、章节、页码范围和证据片段。最终引用列表仅包含回答实际使用的有效编号；缺失或越界编号视为引用校验失败，不回退把所有召回当作已引用来源。编号有效不能单独证明语义有依据，语义支持另由评测检查。

无相关依据返回“未找到相关依据”。只有部分依据时明确回答范围。服务故障返回可识别的错误，不能伪装成知识库无依据。知识库中的命令或提示语作为文档内容处理，不成为系统指令。

前端使用 useChat 与所锁定版本的 UI Message Stream；验证文本增量、结构化来源、完成、错误、停止与断开连接。推理过程不作为制度证据，也不要求模型输出内部思考过程。

## 8. 图谱范围与多跳证据

| 制度 | 优先抽取 |
| --- | --- |
| 采购 | 采购事项、含税总金额档位、审批步骤/岗位、供应商要求、验收与付款材料 |
| 考勤休假 | 假期类型、时长条件、审批岗位、提前申请期限、证明材料 |
| 费用报销 | 费用类型、审批档位、票据要求、报销材料、时限 |
| 员工手册 | 对专项制度的显式引用、培训报销、请假、利益冲突相关条款 |

固定关系集合：`REFERS_TO`、`APPLIES_TO`、`HAS_RULE`、`REQUIRES`、`APPROVED_BY`、`NEXT_STEP`、`SOURCED_FROM`。描述性企业文化段落不做自由实体堆砌。Rule 节点按文档及条款限定作用域，Role/Matter 按类型和规范名称关联。

抽取使用 Pydantic 校验，证据引文必须能在对应切片中核对。每条关系保留 source_chunk_ids、原始引文和适用条件；金额、时长、单位、上下界与含税口径不能省略。不能把“不超过一个工作日的请假由主管审批”压成无条件的“请假由主管审批”。无法规范化的条件保留原文并限制自动推断。

图谱任务存 processing_jobs，以 source_job_id 绑定已完成的导入结果。checkpoint 保存已校验的抽取结果与 manifest/hash，Neo4j 按 graph_job_id 幂等投影；投影失败重放原结果。页面使用 ECharts 展示局部图，每次最多 80 个节点，保留搜索、展开/收起和来源查看；不强制每份文档独占一张图。

图谱检索使用参数化、受控的 2～3 跳 Cypher；限制路径类型与候选数量。取得的来源切片回查 PG，合并基础检索候选后精排，再生成答案。金额和时长比较由程序执行；图谱路径长度不等于推理正确性。

两个首版演示：

1. 员工手册要求请假按哪份制度办理，半天事假由谁审批：手册第九条 -> 考勤制度第十一条 -> 时长条件 -> 直属主管。对应 MX-002。
2. 外部培训费用遵循哪份报销制度，电子发票截图能否代替原文件：手册第二十三条 -> 报销制度第十条 -> 原始 PDF/OFD 要求。由 MX-004 与 FIN-006 组合编写独立验证题。

两条链路必须引用各跳的实际原文。不存在的培训专项审批流程、统一假期天数或工资日期不得靠图谱补出。

## 9. 页面与最小接口

当前状态（2026-11-14）：前端原型已完成用户评审，作为后续界面与交互基准。FastAPI 基础工程、四项独立基础设施、8 表迁移和真实约束测试已完成，详见[后端基础记录](dev-notes/backend-foundation.md)及[数据库设计](superpowers/specs/2026-11-14-database-design.md)。公开 API 目前为健康检查；问答、上传处理和图谱页面继续使用演示数据，真实业务链路按后续任务接入。前端验证与局限见[原型记录](dev-notes/frontend-prototype.md)。

顶部导航区分问答工作台、文档管理和知识图谱，左侧随页面显示对应工具：问答使用新建会话与历史会话；文档管理使用分类与处理状态筛选，正文区集中搜索、上传和分页列表；图谱使用关联场景、节点搜索与类型筛选。问答范围在输入框底部按需选择，默认全部知识库。右侧为原文溯源，窄屏侧栏与来源面板改为抽屉。文档详情可查看原文和示例片段，图谱节点可打开对应证据。

| 接口 | 目的 |
| --- | --- |
| GET /api/health/live、/api/health/ready | 进程与依赖检查 |
| POST /api/documents | 新建上传，客户端沿用稳定 document_id；返回 document_id、version_id、job_id |
| POST /api/documents/{document_id}/versions | 显式上传新版本，同文档同 hash 复用既有版本 |
| GET /api/documents | 元数据列表，不返回全文 |
| GET /api/processing-jobs/{job_id} | 导入/图谱的处理阶段、状态、明确错误 |
| POST /api/processing-jobs/{job_id}/retry | 受控重试，检查状态和次数上限 |
| GET /api/documents/{document_id} | 文档元数据、正文与图谱状态 |
| PATCH /api/documents/{document_id}、DELETE /api/documents/{document_id} | 修改标题/分类、软删除 |
| GET /api/document-versions/{version_id}/file | 固定版本的原件预览或下载，历史引用使用此接口 |
| GET /api/processing-jobs/{job_id}/assets/{asset_id} | 固定导入结果的解析图片等资源 |
| GET /api/chunks/{chunk_id} | 引用正文与定位信息 |
| POST /api/sessions、GET /api/sessions | 新建与查询历史会话 |
| GET /api/sessions/{session_id} | 恢复会话消息和来源 |
| PATCH /api/sessions/{session_id}/scope | 修改范围，带 expected_scope_revision |
| POST /api/chat | AI SDK 流式问答，接收 session_id、client_request_id、scope_revision、text |
| POST /api/chat-messages/{message_id}/stop | 停止助手消息对应的生成请求 |
| GET /api/graph?document_id=... | 局部节点、关系、来源、fingerprint 与 has_more |

无账号体系；此版本按本地演示应用部署，不把 session_id 描述成身份认证。

## 10. 验证与两天安排

周六上午：依赖与基础设施、MinerU PDF/DOCX 真实解析、AI SDK 流式协议验收。周六下午：异步导入、切片、检索、问答、引用定位。

周日上午：短期追问、40 题回归、拒答与引用问题修复。核心闭环验收后，周日下午实现受控图谱与两个多跳示例，再整理交付资料。

必须验证：

- 文件上传后不阻塞等待解析，重试不会产生重复文档或切片。
- RustFS 通过 boto3 完成桶与对象的基本操作、HEAD、Range 内容核对；重新创建新项目容器后命名卷内原件仍可读取。官方兼容声明不替代本机集成验证。
- 四份 PDF 可进入 ready；一份 DOCX 和一份 MD 通过格式验收，页码缺失不造假。
- 表格的金额、条件、审批岗位在切片中可一起定位。
- “半天事假 -> 那四天呢”检索问题正确补全；不同会话不混入历史。
- 6 道不可直接回答题不编造数值、日期和流程；可回答题的关键事实与引用逐项核查。
- 40 题全部生成逐题报告；失败不能被静默跳过，不把模型自评分当作唯一正确性依据。
- 模型未配置、MinerU 失败、队列断开和图谱失败均有可区分状态。
- 最终引用只包含实际使用的有效来源；点击可打开对应原文。
- 图谱关系可溯源；两个多跳示例每一步有依据，图谱失败不破坏基本 RAG。
- 用相同问题、相同模型和检索预算比较基础 RAG 与图谱扩展的证据召回、答案、引用、耗时及调用量。不预设图谱必然提高分数。

最终交付：可运行源码、环境变量示例、锁文件、启动步骤、设计说明、校准后的评测集与逐题结果、3～5 分钟演示脚本。实际未运行的模型集成与未解决问题必须在结果中明确标注。

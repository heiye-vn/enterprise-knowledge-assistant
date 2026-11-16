# 企业知识助理：架构与处理规则

本文说明当前架构、入库恢复、问答与来源保留规则。启动步骤和后续待办见 [README](../README.md)，配置与专题说明见 [开发文档](dev-notes/README.md)，实际问答结果见 [验收报告](../eval/README.md)。

## 1. 目标与边界

Python + React 企业制度问答应用，覆盖上传、解析、索引、混合检索、流式回答、引用溯源、知识图谱和两跳证据扩展。

支持 PDF、DOCX、UTF-8 Markdown、PNG、JPG/JPEG；文档按单文件管理。前端不提供分类、版本管理、重新解析或重建索引入口，底层版本与处理代次用于保持固定来源。

本次不包含：登录注册、账号鉴权、长期个人记忆、自由生成 Cypher 的 Agent、通用审批系统、图谱社区发现。联网搜索已通过 Tavily 接入，MCP 暂缓。会话记录持久化属于历史恢复，不等同于长期记忆。

## 2. 项目位置与资料

- 项目根目录： `enterprise-knowledge-assistant/`，与 GitHub 仓库同名；以下资料路径均相对于仓库根目录。
- 选用语料：`test-data/version_chatgpt/知识库语料` 中的四份制度，PDF 为首批验收输入；DOCX 同样属于支持的上传格式。
- 评测来源：`test-data/version_chatgpt/独立评测集/RAG标准评测集.jsonl`，当前为 50 题，其中 43 题标记可回答、7 题标记不可直接回答。
- Gemini、Qwen 资料不混入同一知识库；可以借鉴题型，新增问题的答案必须重新依据选定制度标注。
- 评测问题、标准答案、证据摘要不得进入文档检索索引。
- 不修改四套原始资料。校准后的评测集放在项目 `eval/`，另存修改原因、依据和相似问题分组；各套资料的位置与用途见[测试资料使用说明](test-data.md)。

已确认需要校准：FIN-004 删除原文未明确的住宿例外原因和指定审批人；HB-003 删除原文未明确的事件报告材料和日志要求；MX-003 按实际证据修正跨文档标注。HR-005/MX-001、HB-008/NA-002 分别归为同组问法，避免跨开发集和验收集泄漏相似问题。

## 3. 技术栈与运行约束

| 部分 | 决策 |
| --- | --- |
| Python | 3.12，uv 管理与锁定依赖 |
| 后端 | FastAPI、Pydantic、SQLAlchemy 2、psycopg 3、Alembic |
| 数据 | PostgreSQL 16 + pgvector |
| 消息任务 | Celery + Redis；文档与图谱任务共用 documents 队列，maintenance 队列处理恢复和清理 |
| 对象存储 | RustFS，Python 使用 boto3 接入 S3 API |
| 解析 | MinerU 云端 API；Markdown 在本地读取 |
| 检索 | jieba + rank-bm25、pgvector、RRF、阿里 Rerank |
| 模型 | 聊天模型可选千问或第三方 OpenAI 兼容接口；Embedding/Rerank 使用阿里 |
| 图谱 | Neo4j + 官方 Python 驱动；受控 Cypher |
| 前端 | React、TypeScript、Vite，原生 fetch 读取 POST SSE |
| 界面 | CSS、Tailwind 构建插件、Lucide |
| 阅读与图谱 | react-pdf、docx-preview、react-markdown、remark-gfm、Apache ECharts |
| 验证 | pytest、Node test runner/tsx、JSONL 真实链路评测 |
| 本地部署 | Docker Compose 启动 PostgreSQL、Redis、RustFS、Neo4j |

RustFS 以单节点 Docker 部署，boto3 访问 S3 API，镜像版本固定在 Compose 中；不假定覆盖所有 S3 行为。PostgreSQL/pgvector 让业务状态与向量共用事务；jieba + rank-bm25 提供进程内中文关键词召回，当前不额外引入 Elasticsearch。四份制度是验收样本，不是文档数量上限；大规模检索和多副本索引管理需按实测重新评估。

全局约束：

- Python 使用 3.12；Node.js 使用 22；pnpm 使用 10。
- 使用 uv.lock 与 pnpm-lock.yaml；服务镜像在实际拉取验证后固定标签，不使用 latest。
- PostgreSQL 是文档、切片、向量、任务和会话的事实来源；Neo4j 是可重建的派生数据。
- 文档正文与列表元数据分开存储，列表接口不加载全文。
- PostgreSQL 内容与向量写入使用同库事务；RustFS、Redis、Neo4j 不伪装成同一事务。
- API Key 仅从环境配置读取；配置示例不包含真实凭证，不从参考项目自动复制密钥。
- 每个业务实体 ID 在接口中使用字符串；同一切片 ID 用于检索、引用和图谱来源关联。
- 数据模型、接口和 SSE 事件协议按真实流式验收结果锁定。
- Celery Worker 和 Beat 在 Linux 容器运行，避免依赖 Windows 原生 Worker 的进程池兼容性。

向量与重排使用阿里云百炼，默认 1024 维；回答模型可选择千问或第三方 OpenAI 兼容接口。模型名、区域、变量优先级和检查命令见 [模型配置](dev-notes/model-clients.md)，网络与代理见 [网络说明](dev-notes/model-network.md)。

## 4. 服务与数据职责

| 存储 | 内容 |
| --- | --- |
| PostgreSQL | 8 张表：documents、document_versions、document_contents、chunks、processing_jobs、chat_sessions、chat_messages、message_citations。分类存文档字段，内容块/范围/请求快照存 JSONB，导入和图谱共用任务表 |
| RustFS | 上传原件、MinerU 解析原始归档、图片及其他解析资源 |
| Redis | Celery 消息代理；不作为任务业务状态或文档内容的唯一存储 |
| Neo4j | Document、Matter、Rule、Role、Material 等节点及有来源的关系 |

同步 SQLAlchemy 仓储使用 psycopg 3；FastAPI 异步路由中的阻塞数据库与对象存储操作在线程池执行。Celery 在独立进程中建立连接，不跨进程或事件循环共享连接。

单知识库的名称与模型配置来自应用配置，不另建知识库表。字段、事务边界与服务校验详见 [8 表设计](superpowers/specs/2026-11-14-database-design.md)，精确结构以 [数据库迁移](../backend/migrations/versions/) 和 [ORM](../backend/app/models.py) 为准。

开发端口与旧项目隔离；Compose 使用新项目的网络、容器标识和数据卷。启动前检查冲突，禁止复用或清理旧 Knowledge Hub 的数据卷。

后端镜像供消费文档/图谱队列的 Worker 与 Beat 复用；这两个进程在 Linux 容器内运行。原生运行的 FastAPI 使用本机映射端口，容器内 Worker 使用 Compose 服务名连接依赖，两种配置必须分别验证。

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
    R --> G[用户按需触发图谱任务]
    G --> N[Neo4j]
```

上传校验文件扩展名、文件签名、大小和非空内容。新建使用稳定 document_id，更新走显式版本接口；同文档同 hash 复用既有版本。所有新建/新版本在上传前按 SHA-256 检查有效知识库的全部历史版本，命中则提示已有文档并跳过；同批重复只保留第一份。服务端正式接收文件时重新计算指纹并在同一 PG 事务中取得指纹锁、复查及登记，防止并发绕过去重；不按文件名或语义相似度判重。原件保存后，PG 事务创建文档、版本和 job_type=import 的 processing_jobs 行；该任务行也是待投递依据。投递器先更新 next_dispatch_at 和尝试次数再发送，失败或进程退出后由 Beat 扫描补发；Worker 按 job_id、状态和租约令牌幂等认领。

两种任务共用 `queued -> running -> ready` 状态，也可进入 failed/canceled。import 的 stage 为 parsing/chunking/embedding/publishing，graph 的 stage 为 extracting/validating/projecting；前端按类型与阶段显示进度。任务另存错误、可重试性、尝试次数、远端 MinerU 任务 ID、租约和产物位置。

- MinerU 已返回远端任务 ID 后，恢复执行应继续查询该任务。
- 提交请求结果不确定时，不盲目重发；记录明确状态，避免重复计费和重复解析。
- 轮询采用有截止时间的延后检查，不在 HTTP 上传请求中等待全流程。
- 网络、限流和服务端临时故障使用有上限的退避重试；格式错误、凭证缺失不无限重试。
- Worker 可能重复收到消息。租约、阶段检查和数据库唯一约束避免重复文档、切片和图谱关系；进程退出后可恢复过期租约。
- 文本索引已完成时，图谱失败不改变文档可问答状态。

MinerU 使用官方 v4 API 接收 PDF、DOCX 和图片；Markdown 本地解析。配置为 `KH_MINERU_API_TOKEN`、`KH_MINERU_MODEL=vlm`、`KH_MINERU_LANGUAGE=ch`，云端不需要访问本机 RustFS 地址。

### 上传与原件

- 原件上限 20 MB，服务端校验扩展名、签名、编码或真实图片解码结果。图片上限 4000 万像素，JPEG 统一存为 jpg。
- `POST /api/documents/check-duplicate` 接收 `file_sha256`，只做预检查；正式上传用实际字节重新计算 SHA-256，在 READ COMMITTED 事务中通过 `lock_and_check_file` 获取事务级 advisory lock，再查全库和登记。锁持有至提交或回滚。
- 去重覆盖有效文档的全部历史版本，包括尚未就绪的原件；已软删除文档不占用有效库指纹。同 ID 不同字节返回 409，重复上传不绕过任务尝试上限。
- 原件按固定 version_id 提供 GET、HEAD 和单范围 Range（206/416），保留正确 MIME 和 UTF-8 文件名。前端关闭已提交的上传窗口不等于撤销服务端任务。

### 解析检查点与资源

外部提交前保存 submitting 意图，拿到 batch_id 后先持久化再上传。恢复时沿用 batch；上传结果不确定时先查远端状态。无法确认提交结果时明确报错，不盲目新建远端任务。

正常轮询释放租约，由 Beat 延后投递，不消耗新的故障尝试；解析等待默认最多 30 分钟。远端 done 后单独保存 downloading 检查点，允许在 24 小时下载期限内继续取回原归档，不重新提交解析。

RustFS 保存原始 ZIP 和图片，按 job/lease_token 隔离。ZIP 仅在内存读取，默认压缩后不超过 50 MB、解压后不超过 100 MB、成员最多 2000 个；拒绝危险路径、重复成员、符号链接和加密成员。归档要求唯一的 full.md 与 *_content_list.json。

归档资源仅访问允许的 MinerU/OpenXLab/阿里云 HTTPS 域名，下载不携带 Bearer 头、不跟随重定向。资源接口只返回 manifest 中登记的资源，不把临时签名 URL 交给前端。固定解析结果通过 `GET /api/document-versions/{version_id}/parsed?job_id=...` 读取。

原件与解析对象仅在数据库没有引用、没有活动任务且保留超过 24 小时后清理；数据库查询失败时中止清理。历史版本和软删除文档仍有引用，不能当作孤儿对象清除。

### 删除与历史来源

`DELETE /api/documents/{document_id}` 复用 deleted_at，活跃导入或图谱任务返回 409，重复删除返回 204。删除后排除文档列表、新检索、图谱展示及有效库指纹检查；禁止继续重试或重新处理已删除资料。

原件、正文和历史切块保留。历史回答按固定的已就绪 import job 打开来源，界面标明“已从知识库移除”；默认读取已删除文档正文仍返回 404。

## 6. 统一内容块与切片

规范化内容块至少包括：`block_id`、`type`、`text`、`heading_path`、`page_start/page_end`、可选 bbox、原始资源关联。PDF 页码来自真实解析产物并用 pypdf 核对原件页数，单张图片按第 1 页定位；DOCX/MD 支持章节和内容块定位，无页码时返回 null，不伪造 PDF 页码。

应用对外页码统一为从 1 开始。MinerU page_idx 从 0-based 在规范化层转换一次，避免阅读器跳错页。

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
  -> POST SSE 流式输出与最终引用校验
```

短期上下文读取本会话最近完成的消息并限制轮数和文本长度。历史仅用于消解指代与条件；历史中的助手制度结论不能替代本轮文档。条件未能消解时先澄清，例如“那四天呢”仍无法确定假期种类时不擅自补全。

每个新会话有独立 session_id，PG 保存消息与引用用于恢复。首版不抽取用户档案，不跨会话向量召回个人记忆，不自动引入摘要模型。

chat_sessions.scope 保留底层兼容结构，当前聊天默认检索全部有效文档；检索时固定实际文档、版本、导入任务与向量 profile，写入助手消息的 request_snapshot。助手消息同时承载本轮状态与 client_request_id，不另建问答轮次表；最终正文、引用与 completed 同事务提交。停止和完成锁定同一助手消息处理；历史引用始终打开固定 version_id 的原件。

引用由后端建立本轮有效来源编号，编号映射到真实 chunk_id、文档、章节、页码范围和证据片段。最终引用列表仅包含回答实际使用的有效编号；缺失或越界编号视为引用校验失败，不回退把所有召回当作已引用来源。编号有效不能单独证明语义有依据，语义支持另由评测检查。

无相关依据返回“未找到相关依据”。只有部分依据时明确回答范围。服务故障返回可识别的错误，不能伪装成知识库无依据。知识库中的命令或提示语作为文档内容处理，不成为系统指令。

前端使用原生 fetch 读取 start/phase/delta/done 事件；已验证文本增量、结构化来源、完成、错误、停止与断开连接。推理过程不作为制度证据，也不要求模型输出内部思考过程。

## 8. 图谱范围与多跳证据

| 制度 | 优先抽取 |
| --- | --- |
| 采购 | 采购事项、含税总金额档位、审批步骤/岗位、供应商要求、验收与付款材料 |
| 考勤休假 | 假期类型、时长条件、审批岗位、提前申请期限、证明材料 |
| 费用报销 | 费用类型、审批档位、票据要求、报销材料、时限 |
| 员工手册 | 对专项制度的显式引用、培训报销、请假、利益冲突相关条款 |

固定业务关系为 approved_by（业务审批）、recorded_by（备案）、reviewed_by（审核）、notified_to（通知）、submitted_to（提交核查）、requires（所需材料）和 references（引用制度）。描述性企业文化段落不做自由实体堆砌。Rule 节点按文档及条款限定作用域，Role/Matter 按类型和规范名称关联。

抽取使用 Pydantic 校验，证据引文必须能在对应切片中核对。每条关系保留 source_chunk_ids、原始引文和适用条件；金额、时长、单位、上下界与含税口径不能省略。不能把“不超过一个工作日的请假由主管审批”压成无条件的“请假由主管审批”。无法规范化的条件保留原文并限制自动推断。

图谱任务存 processing_jobs，以 source_job_id 绑定已完成的导入结果。checkpoint 保存已校验的抽取结果与 manifest/hash，Neo4j 按包含任务身份和租约令牌的 projection_id 幂等投影；投影失败重放原结果。页面使用 ECharts 展示局部图，每次最多 80 个节点，保留搜索、展开/收起和来源查看；不强制每份文档独占一张图。

图谱检索使用参数化、受控的两跳 Cypher；限制路径类型与候选数量。取得的来源切片回查 PG，合并基础检索候选后精排，再生成答案。金额和时长比较由程序执行；图谱路径长度不等于推理正确性。

两个首版演示：

1. 员工手册要求请假按哪份制度办理，半天事假由谁审批：手册第九条 -> 考勤制度第十一条 -> 时长条件 -> 直属主管。对应 MX-002。
2. 外部培训费用遵循哪份报销制度，电子发票截图能否代替原文件：手册第二十三条 -> 报销制度第十条 -> 原始 PDF/OFD 要求。由 MX-004 与 FIN-006 组合编写独立验证题。

两条链路必须引用各跳的实际原文。不存在的培训专项审批流程、统一假期天数或工资日期不得靠图谱补出。

## 9. 页面与最小接口

真实入库、问答、图谱、多跳、联网和追踪已接入，文档支持软删除，历史引用保留。后端接口仍使用固定 version/job 标识，保证来源稳定；前端按单文件管理。

顶部导航为问答工作台、文档管理和知识图谱。会话首次发送后持久化，历史支持删除；文档有搜索、处理状态筛选、上传、查看、删除和失败重试。问答默认检索全部有效知识库，限定文档范围暂缓。来源面板展示正文、原件、实际索引切块；图谱支持搜索、类型筛选、展开/收起及来源核对。当前只验收电脑端，不做手机适配。

| 接口 | 目的 |
| --- | --- |
| GET /api/health/live、/api/health/ready | 进程与依赖检查 |
| POST /api/documents/check-duplicate | 检查有效库全部历史版本的文件指纹，返回重复文档/版本；正式上传仍需服务端复查 |
| POST /api/documents | 新建上传，客户端沿用稳定 document_id；返回 document_id、version_id、job_id |
| POST /api/documents/{document_id}/versions | 显式上传新版本，同文档同 hash 复用既有版本 |
| GET /api/documents | 已实现：offset/limit 元数据列表，不返回全文 |
| GET /api/documents/{document_id}/versions | 已实现：原件版本列表与固定版本读取地址 |
| GET /api/processing-jobs/{job_id} | 导入/图谱的处理阶段、状态、明确错误 |
| POST /api/processing-jobs/{job_id}/retry | 受控重试，检查状态和次数上限 |
| GET /api/documents/{document_id} | 文档元数据、正文与图谱状态 |
| DELETE /api/documents/{document_id} | 已实现：软删除，活跃任务禁止，历史固定来源保留 |
| GET /api/document-versions/{version_id}/file | 固定版本的原件预览或下载，历史引用使用此接口 |
| GET /api/processing-jobs/{job_id}/assets/{asset_id} | 固定导入结果的解析图片等资源 |
| GET /api/chunks/{chunk_id} | 引用正文与定位信息 |
| POST /api/sessions、GET /api/sessions | 新建与查询历史会话 |
| GET /api/sessions/{session_id} | 恢复会话消息和来源 |
| DELETE /api/sessions/{session_id} | 从历史中移除会话 |
| POST /api/chat/stream | POST SSE，接收 session_id、client_request_id、text，可选 web_search/retry_attempt |
| POST /api/chat | 同步问答接口 |
| POST /api/chat/stop | 停止对应消息/尝试的生成请求 |
| POST /api/graph/build、GET /api/graph?document_id=... | 图谱异步任务、节点/关系/来源与处理状态 |

无账号体系；此版本按本地演示应用部署，不把 session_id 描述成身份认证。

## 10. 验证入口

- 后端回归覆盖上传校验、全库并发去重、MinerU 检查点、发布竞争、历史来源、软删除、图谱校验和停止/重试隔离。
- 前端回归覆盖上传身份、流式拆包、引用、草稿、检索详情和图谱交互；运行命令统一见 [README](../README.md#验证与开发)。
- 实际问答的答案、来源、拒答和失败分析见 [eval](../eval/README.md)。图谱路径存在和引用编号有效都不能单独证明语义正确；基础 RAG 与图谱扩展应以相同问题和模型比较，不预设图谱一定提高效果。

# 企业知识助理：8 张核心表设计

日期：2026-11-14。范围：按已确认的精简方案设计数据库，保留当前前端原型的页面与交互。本稿替代此前的细分方案；后续基础工程阶段已落实 8 表 ORM、Alembic 迁移和真实约束验证，详见[实现记录](../../dev-notes/backend-foundation.md)。本文中的完整导入、发布、问答和图谱事务仍是后续业务开发的要求。

配套文件：[评审用 PostgreSQL DDL](2026-11-14-database-schema.sql)、[整体设计](../../design.md)。表字段、CHECK、外键和索引的精确定义以 DDL 为准，业务事务规则以本文为准。

## 1. 八张表及存储职责

| 表 | 保存什么 | 支撑的前端功能 |
| --- | --- | --- |
| documents | 文档标题、分类、当前版本、软删除状态 | 文档目录、搜索、分类筛选 |
| document_versions | 原件版本、文件位置、已发布索引指针 | 文件查看、版本与历史原文 |
| document_contents | 每次导入生成的 Markdown、内容块与资源清单 | 正文预览、解析结果、来源定位 |
| chunks | 不可变切片、章节/页码、定位与向量 | 检索、问答、引用、图谱来源 |
| processing_jobs | 导入/图谱任务、阶段、检查点、重试和投递时间 | 上传进度、失败重试、图谱构建状态 |
| chat_sessions | 会话标题、当前问答范围、消息序号 | 新建会话、历史搜索、范围选择 |
| chat_messages | 问题、回答、生成状态、每轮资料快照 | 对话恢复、流式回答、停止生成 |
| message_citations | 最终引用的切片、原文片段与展示快照 | 引用编号、页码、版本与原文溯源 |

PostgreSQL 16 + pgvector 保存以上数据；RustFS 保存原件和解析归档；Redis/Celery 负责传递后台任务；Neo4j 保存实体关系。Neo4j 不计入 PostgreSQL 表数，图谱仍使用 ECharts 展示。

首版只运行一个知识库，名称与模型配置从应用配置读取，不额外建立知识库、分类、用户或权限表。资料增多通过索引、分页和任务队列承载，不以固定四份文档为限制。

### 简化边界

| 原来独立拆表的内容 | 本版放在哪里 |
| --- | --- |
| 文档分类 | documents.category 字符串；分类目录由有效文档聚合 |
| 内容块、块与切片的关联 | document_contents.blocks 与 chunks.locators JSONB |
| 文档任务、图谱任务、待投递记录 | processing_jobs；job_type 区分类型，任务行本身也是待投递依据 |
| 会话选择的文档集合 | chat_sessions.scope JSONB |
| 问答轮次、每轮资料范围与模型参数 | 一条助手消息及其 request_snapshot JSONB |
| 单独的上传请求日志 | 新建文档使用稳定 document_id；版本文件 hash 与任务身份处理重试，不提供通用请求审计表 |

明确保留：原件版本、每代切片和最终引用。明确后置：多知识库、任意分类树、独立投递事件历史、通用请求日志、全量审计、在线向量模型切换。

## 2. ER 图

```mermaid
erDiagram
    documents ||--o{ document_versions : has_versions
    documents o|--o| document_versions : current_version
    document_versions ||--o{ processing_jobs : processes
    document_versions o|--o| processing_jobs : active_import
    processing_jobs o|--o{ processing_jobs : source_import_for_graph
    processing_jobs ||--o| document_contents : produces
    processing_jobs ||--o{ chunks : indexes
    document_versions ||--o{ chunks : source_version
    chat_sessions ||--o{ chat_messages : contains
    chat_messages o|--o| chat_messages : answers
    chat_messages ||--o{ message_citations : uses
    chunks ||--o{ message_citations : evidence
```

发布指针可为空。图中的 answers 表示助手答复一条用户消息；角色、任务类型和 ready 条件由服务验证，不把外键存在等同于业务正确。

## 3. 字段与约束

### 通用规则

- ID 为 uuid，由应用生成，对外返回字符串。新建上传的 document_id 由客户端生成一次并在重试时沿用，用户不需要手动填写 ID。
- 时间使用 timestamptz，入库存 UTC。created_at 默认 now()；updated_at 由服务更新，不假设普通 UPDATE 自动更新时间。
- JSONB 保存有明确 schema 的可变结构。状态、分类、外键、排序和常用查询条件使用普通列；JSONB 中的 ID、引用范围与业务含义由服务校验。
- 原件与已完成导入的正文/切片不可原地覆盖；重新解析、切片或建向量生成新的 import job。普通重试沿用 job_id。
- 页码从 1 开始，两端同空或满足 1 <= start <= end；DOCX/MD 没有可靠页码时为 NULL，保留章节和内容块定位。
- hash 为 SHA-256 小写十六进制。发布前校验向量齐备、维度正确、所有切片可定位。列表接口不读取完整正文、块清单和向量。
- 外键使用 ON DELETE RESTRICT；文档和会话先软删除。首版不自动物理删除历史版本、任务、正文、切片和引用。

### 3.1 documents：文档元数据

| 字段 | 含义与规则 |
| --- | --- |
| id | 文档稳定身份，更新文件不换 ID |
| title、category | 显示名与分类；标题可重名，分类默认“未分类” |
| current_version_id | 当前供新问答使用的版本；首次处理未完成时为空 |
| next_version_no | 默认 1，锁定文档行后分配版本序号并递增 |
| revision | 元数据修改的乐观并发版本，默认 0 |
| deleted_at、created_at、updated_at | 软删除与元数据时间 |

复合外键保证 current_version_id 属于这份文档；发布服务另查该版本是否已有 ready 的导入任务。分类重命名在事务中更新匹配的 category 字段，不影响历史引用快照。

### 3.2 document_versions：原件版本

| 字段 | 含义与规则 |
| --- | --- |
| id、document_id、version_no | 原件版本身份及上传顺序；同文档 version_no 唯一 |
| version_label | 原件标注的版本，如 1.1；与上传序号分开 |
| original_filename、format、size_bytes | 文件名、pdf/docx/md、字节数 |
| file_sha256 | 数据库保证同文档 hash 唯一；上传服务另按全库文件指纹检查，阻止有效文档间重复导入 |
| file_ref | JSONB：bucket、object_key、mime_type；不保存临时签名 URL |
| source_metadata | JSONB：归口部门、原文日期等有 schema 的来源元数据 |
| active_import_job_id | 本版本当前可用的导入结果；重建中保留旧指针 |
| next_generation_no | 锁定版本行后分配任务代次；导入和图谱共用递增序号，允许空号 |
| created_at | 原件登记时间 |

原件对象与 hash 创建后不可改写。current_version/active_import_job 是系统选定的检索版本，不据上传先后推断制度的实际生效优先级。

### 3.3 document_contents：正文与解析块

每个 import job 一行，以 job_id 为主键，version_id 必须与所属任务一致。

| 字段 | 含义与规则 |
| --- | --- |
| job_id、version_id | 明确是哪次导入、哪个原件版本的正文 |
| markdown、content_sha256 | 完整规范化正文及 hash |
| blocks | JSONB 数组：block_id、type、text、heading_path、页码、bbox 或表格结构 |
| artifacts | JSONB：原始解析归档与资源的 bucket/key/hash 清单 |
| page_count | 真实 PDF 页数；无可靠分页时为空 |
| created_at | 产物创建时间 |

正文与列表元数据仍分表。块 ID 在同一 job 内稳定，切片 locators 引用这些块；这里不需要逐块独立检索/更新，所以首版不拆 content_blocks 与关联表。需要读取某页时按 job 与页码定位，不在文档目录加载 blocks。

### 3.4 chunks：切片与向量

| 字段 | 含义与规则 |
| --- | --- |
| id | UUIDv5(job_id, ordinal + content_sha256)，同任务重试稳定 |
| job_id、version_id、ordinal | 代次、原件与顺序；同 job 的 ordinal 唯一 |
| content、content_sha256 | 非空切片与 hash；表格切片保留表头和适用条件 |
| heading_path、page_start、page_end | 章节和真实页码 |
| locators | JSONB 数组：来源 block_id、实际页码、bbox、块内范围；跨页可多项 |
| embedding_profile_hash、embedding_dimension | 向量空间和实际维度，与所属导入任务一致 |
| embedding | pgvector vector，可在处理中暂空；非空时 CHECK 维度一致 |
| created_at | 切片创建时间 |

复合外键将 job/version/profile/dimension 绑定在一起；graph job 没有向量 profile，因此不能作为 chunks 的向量来源。ready 的 chunks 不重写，历史引用直接依赖 chunk_id。

模型名和维度联调前不锁死；当前候选为 1024 维。首版使用精确 cosine 距离验证正确性，数据增长后对确定维度/profile 添加 HNSW 表达式索引，并验证范围过滤后的召回率。维度相同不代表不同模型的向量可混排。

### 3.5 processing_jobs：统一任务表

| 字段 | 含义与规则 |
| --- | --- |
| id、version_id、generation_no | 任务身份、来源原件与版本内递增代次 |
| job_type | import / graph，使用不同 Celery 队列和处理器 |
| source_job_id | graph 必须指向同版本的 ready import job；import 必须为空 |
| status、stage | 通用任务状态和具体处理阶段，见第 5 节 |
| config、config_hash | 不含密钥的解析/模型/切片或图谱配置快照及 hash |
| embedding_profile_hash、embedding_dimension | import 必填，graph 为空；graph 使用 source_job 的切片 |
| checkpoint | JSONB：远端任务 ID、提交状态、产物位置、阶段计数；graph 另存已校验的抽取结果/manifest/hash |
| attempt_no、max_attempts | 处理认领次数和上限，默认 0 / 3 |
| lease_owner、lease_token、lease_expires_at | Worker 租约及单调递增令牌，防止过期 Worker 覆盖 |
| next_dispatch_at、last_dispatched_at、dispatch_attempts | 下次投递时间、最近成功投递时间、投递次数 |
| error | JSONB：code、message、retryable、stage；不写入密钥和完整异常环境 |
| started_at、finished_at、created_at、updated_at | 任务时间 |

同一原件版本最多一个活动 import；同一 source_job 最多一个活动 graph。新索引可以与旧索引的图谱任务并存，不能因为图谱处理中而阻止文档发布。

任务行本身兼作待投递记录，Redis 不是任务状态的唯一存储；不另建 outbox，不记录每次投递的独立历史。请求与任务也不强行一一对应：相同文档/hash/profile 的普通重复上传可以复用同一任务；强制重建明确创建新 generation。

### 3.6 chat_sessions：会话与范围

| 字段 | 含义与规则 |
| --- | --- |
| id、title | 会话身份与标题，默认“新会话” |
| scope | JSONB：mode=all/custom、document_ids；默认 all 和空数组 |
| scope_revision | 每次修改范围递增，避免发送时使用过期选择 |
| next_message_seq | 默认 1，事务内为一对问题/回答分配两个序号 |
| last_message_at、deleted_at、created_at、updated_at | 历史排序、软删除与时间 |

all 表示每次提问时解析当前可用文档，不固定为创建会话那天的清单。custom 必须是非空、去重且有效的文档 ID 集合；被移除的文档显示不可用，不自动扩大到全部知识库。JSONB 中 ID 的存在与范围语义由服务校验。

### 3.7 chat_messages：消息，同时承载一轮问答

| 字段 | 含义与规则 |
| --- | --- |
| id、session_id、sequence_no、role | 消息身份、会话顺序、user/assistant |
| reply_to_message_id | assistant 指向同会话的 user；一条用户消息最多一条助手消息 |
| client_request_id | assistant 保存本次请求的客户端 UUID；同会话唯一，重试返回既有消息 |
| content | Markdown 文本；助手可保存流式片段，最终来源另从引用表组装 |
| status、answer_kind | 生成状态；完成回答分 answered / partially_answered / refused |
| request_snapshot | assistant 的本轮范围、版本/任务清单、模型参数、上下文截止序号和请求指纹 |
| error、usage | JSONB：错误摘要与供应商实际返回的用量 |
| lease_expires_at、stop_requested_at | 请求存活检查和停止请求 |
| created_at、updated_at | 消息时间 |

user 必须为 completed，reply_to/client_request/snapshot 为空；assistant 必须具备这三项。外键保证答复不跨会话，服务再检查目标角色是 user。每个会话最多一个 queued/retrieving/generating 助手消息，防止追问并发混入历史。

助手消息 ID 就是生成请求 ID，不再拆 chat_turns。客户端保存 client_request_id；同键不同问题/范围由请求指纹返回 409，而不是生成第二轮。

### 3.8 message_citations：最终引用

| 字段 | 含义与规则 |
| --- | --- |
| id、message_id、chunk_id | 引用身份、助手消息、真实切片 |
| citation_no | 回答中的编号，从 1 开始；同消息内唯一 |
| quote | 可在对应切片中核对的实际引文 |
| source_snapshot | JSONB：文档/版本/任务 ID、标题、版本标注、章节、页码与必要定位 |
| created_at | 引用创建时间 |

保留独立引用表，外键阻止误删已引用的切片。服务检查消息为 assistant，chunk.job_id 属于 request_snapshot 的资料清单，快照字段确实来自该 chunk/version，编号确实被最终正文使用。不能将 JSONB 中的自报来源或全部召回结果直接当作最终引用。

## 4. JSONB 的结构与校验责任

JSONB 是合并存储，不是取消数据约束。服务使用 Pydantic 定义各字段的结构，在写入和恢复时校验；数据库检查对象/数组基本形状。request_snapshot 显式记录 schema_version，其余字段的 schema 随迁移和应用版本管理，不能随意增加未定义结构。

### 4.1 解析块与切片定位

blocks 中每项包含 block_id、type、text、heading_path、page_start/page_end；可选 structured_content 保存表头/行，locators 保存按页的 bbox。bbox 必须同时记录单位、页尺寸和坐标基准，不将不同解析器的坐标直接混用。

chunks.locators 引用同 job 的 block_id，可带块内 Unicode 码点半开区间和按页 bbox。发布服务校验引用块确实存在，范围与页码合理；一块可贡献给多个切片。跨页表格保留上下文和适用条件。

### 4.2 会话范围与每轮快照

```json
{
  "mode": "custom",
  "document_ids": ["11111111-1111-4111-8111-111111111111"]
}
```

mode=all 时 document_ids 必须为空；custom 时必须非空且去重。数据库只检查 JSON 形状与 mode 值；UUID 格式、文档存在性和可用性由服务验证。

assistant.request_snapshot 的核心结构如下，示例 ID/hash 仅用于说明格式，实际由服务从数据库与部署配置生成：

```json
{
  "schema_version": 1,
  "scope_mode": "custom",
  "scope_revision": 2,
  "context_up_to_seq": 4,
  "request_fingerprint": "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
  "documents": [{
    "document_id": "11111111-1111-4111-8111-111111111111",
    "version_id": "22222222-2222-4222-8222-222222222222",
    "job_id": "33333333-3333-4333-8333-333333333333",
    "graph_job_id": null
  }],
  "embedding_profile_hash": "bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb",
  "embedding_dimension": 1024,
  "model_config": {},
  "retrieval_config_version": "rag-v1"
}
```

实际 model_config 必须保存使用的聊天/向量供应商、模型、版本、提示模板和必要参数，示例中的空对象不能用于真实生成；不保存密钥。资料清单和模型配置在问答开始时冻结。后续检索使用该清单，不能每一步重新解析“当前版本”。

首版固定一个部署级向量模型，不提供在线热切换。所有入选 job 必须属于相同向量空间。更换模型时在维护窗口重建并切换发布指针后再恢复服务，不能仅修改环境变量就把新查询向量与旧向量混排。

### 4.3 引用快照

source_snapshot 包含 document_id、version_id、job_id、document_title、version_label、heading_path、page_start/page_end 和必要的 locators。它保存当时的展示信息；来源是否存在以 chunk 外键和所属版本为准。

服务从已固定的 job 清单读取 chunk，再组装快照、校验 quote 和编号；不接受客户端提交的快照作为证据。精简后，数据库不再用轮次关联表约束 JSON 中的范围，因此这项服务校验必须测试，不能直接省略。

## 5. 后台任务与发布

### 5.1 通用状态、具体阶段与界面标签

```mermaid
stateDiagram-v2
    [*] --> queued
    queued --> running: Worker 认领
    running --> ready: 校验并完成
    running --> failed: 保存检查点和错误
    queued --> canceled: 取消
    running --> canceled: 取消
    failed --> queued: 受控重试
    ready --> [*]
    canceled --> [*]
```

| 类型 | running 内的阶段 | ready 的含义 |
| --- | --- | --- |
| import | parsing → chunking → embedding → publishing | 正文、定位和向量齐备，结果已完成发布判断 |
| graph | extracting → validating → projecting | 校验后的抽取结果已写入 Neo4j 并核对完成 |

queued 的 stage=queued；ready 的 stage=done。failed/canceled 保留当时 stage 便于诊断。API 将 import 的 running+stage 映射为现有“解析文档/生成切片/建立索引”等状态；两个任务类型不需要两个任务表。

### 5.2 上传去重与版本身份

- 新建上传：客户端为这次新文档生成并保留一个 document_id，POST /api/documents 提交文件及标题/分类。请求丢失后重试使用同一 ID。
- 已有相同 ID 与相同原件 hash 时，返回既有版本与相同配置的已有任务；同一 ID 的新建请求携带不同文件则返回 409，不暗中创建新版本或覆盖文件。元数据变化使用独立 PATCH。
- 新增前检查：POST /api/documents/check-duplicate 接收 file_sha256，查询未软删除文档的全部历史版本，返回 duplicate 和既有文档/版本身份。文件改名不改变指纹；跨格式、重新导出或仅正文相同的不同字节不做语义去重。重复文件跳过导入，展示已有文档信息；首版不提供绕过去重的“仍然新建”。同批次同指纹只保留第一份。
- 更新文件：显式 POST /api/documents/{document_id}/versions。同文档同 hash 复用版本；不同 hash 也先做全库检查，若命中其他有效文档则返回已有文档，不创建版本，否则分配新 version_no。已软删除文档不占用有效库的指纹，可以重新导入；历史数据仍保留。
- 预检查只是用户反馈。正式上传时服务必须用实际接收字节重新计算 SHA-256，在 READ COMMITTED 事务中先调用 lock_and_check_file，以指纹前 64 位取得 pg_advisory_xact_lock，锁保持至文档/版本/任务登记提交或回滚。相同文件的所有写入入口遵循此边界；命中即复用返回，不写新文档、版本或任务，也不发起解析/向量调用。新建接口同一 ID 的不同文件冲突检查优先，继续返回 409。
- 前端和接口查询故障均明确报错，不能按“未找到重复”继续。新增 ix_versions_file_sha256 非唯一索引支持跨文档查询；数据库保留原有同文档唯一约束以兼容历史记录，全库上传规则由共享事务边界执行。
- 创建或复用 job 时锁住版本行，普通重复上传复用相同 config 的 ready/活动 job；强制重新解析/索引才分配新 generation_no。
- 若相同配置仅有 failed/canceled 任务，普通重复上传返回既有终态，不自动创建任务或重置尝试次数；可恢复的 failed 走显式 retry，达到上限或需要重新构建时才创建新 generation。
- 原件先保存到新 RustFS 对象键，再在 PG 事务内创建文档/版本/任务。PG 失败产生的未引用对象按隔离前缀和保留期清理，不覆盖旧原件。

这实现首版上传重试和重复文件处理，不承诺一张跨业务的通用请求审计日志。ID 由客户端代码维护，不增加用户操作步骤，也不作为权限凭证。

### 5.3 用任务表恢复投递

1. 创建任务与业务行在同一 PG 事务提交，status=queued、next_dispatch_at=now()。提交后尝试立即投递，周期调度器也扫描到期 queued 行。
2. 投递器锁行，先将 next_dispatch_at 延后并递增 dispatch_attempts，再向对应队列发送 job_id；成功后记录 last_dispatched_at。发送失败或发送前进程退出，都可在下一次到期扫描补发。
3. 若 Broker 已接收但 Worker 尚未认领，可能再次投递；消费者依据 PG 的 job 状态和租约认领，重复消息不能重复启动已完成任务。投递次数与 Worker 的 attempt_no 分开。
4. running 租约过期时，恢复器条件更新为 queued、增加 lease_token、清理旧 owner/租约并保留检查点。新 Worker 认领再取新 token；旧 Worker 的写入/发布必须被条件更新拒绝。
5. 业务处理失败记录 error 和 retryable，按上限决定受控重试。Broker 不可用保持 queued 并显示投递错误，不伪装成“知识库无依据”。

任务行可以承担待投递角色，因为每一行只代表一个业务任务，允许重复投递同一个 job_id；首版不需要逐次投递事件审计。调度器采用行锁与 SKIP LOCKED，投递间隔设上限，不能在长事务里等待远端服务。

### 5.4 解析、索引与发布

- checkpoint 保存 MinerU remote_task_id、submission_state、产物引用和已完成阶段；有远端任务 ID 就继续查询。提交结果 uncertain 时明确报错并核实，不能直接二次付费提交。
- staging 正文和切片按 job 隔离，重试使用稳定 ID。每次提交检查 lease_token 与状态；ready 后不重写。
- 跨文档/版本/任务的事务统一按 document → version → job 顺序锁行，校验当前租约、正文、块定位、非空向量、profile 和计数。成功后标记 ready/stage=done，再按 generation_no 更新 active_import_job_id；按 version_no 更新 current_version_id，较旧的迟到任务不能倒退指针。
- active_import_job_id 的 FK 只验证版本归属，服务还必须验证目标 job_type=import 且 ready。文档软删除时不发布新结果。
- 原件更新或同版本重建过程中，旧的发布指针继续可用；失败不将已有可用文档降级。
- 同一事务创建 job_type=graph 的 queued 行，source_job_id 指向刚完成的 import。重复完成的 job 直接返回，不重复创建图谱任务。

### 5.5 图谱结果与 Neo4j

graph 的 source_job_id 必须是同版本的 ready import，服务验证这一类型规则。抽取只使用该 job 的切片；checkpoint 保存校验后的 result/manifest/hash，投影失败时重放相同结果，不重新调用模型抽取。

Neo4j 的文档/版本/Chunk 身份沿用 PG ID，Matter/Role/Material 按类型和明确别名规则归一化，Rule 按源 job/条款/条件限定。关系保留 graph_job_id、source_job_id、source_chunk_ids、原始引文和适用条件。金额、时长、上下界和审批/备案职责不可丢失。

按 graph_job_id 幂等投影；每批写入通过 GraphBuild 节点写锁与递增 lease_token 阻止过期 Worker 写入。确认结果 hash 与数量后标记 graph job ready。当前可用图谱取 source_job_id=当前 active import 且 ready 的最新 generation，不再另设图谱发布指针。

图谱页面、搜索、展开/收起与 ECharts 保持原交互。服务端返回局部图，每次最多 80 个节点；收起只改变前端显示，不删除事实。范围清单的 fingerprint 变化时明确要求刷新，不能拼接不同版本的图。图谱失败不影响普通检索问答。

## 6. 一轮问答的事务规则

```mermaid
stateDiagram-v2
    [*] --> queued
    queued --> retrieving: 快照和消息已提交
    retrieving --> generating: 证据已准备好
    generating --> completed: 最终正文与引用同事务提交
    queued --> stopped: 用户停止
    retrieving --> stopped: 用户停止
    generating --> stopped: 用户停止
    queued --> failed: 服务异常
    retrieving --> failed: 服务异常
    generating --> failed: 模型或引用校验异常
    completed --> [*]
    stopped --> [*]
    failed --> [*]
```

1. 先按 session_id/client_request_id 查询既有助手消息，比较请求指纹。相同请求返回既有状态，不再创建用户消息或重新收费生成。
2. 新请求锁住 session 后再次检查幂等键，避免两个并发重发同时通过初查；检查 scope_revision 与单活动回答，在一致性快照中解析可用资料、模型配置及每个版本的 active import/ready graph job。
3. 在同一 PG 事务分配两个 sequence_no，创建 user 和 assistant 占位消息，后者保存 request_snapshot。范围为空则明确报错，不扩大范围或制造拒答。
4. 检索、图谱扩展和精排使用 snapshot 中的 job/profile；不持有长事务调用模型，不使用历史助手回答替代制度来源。
5. 完成事务锁助手消息，确认未先进入 stopped/failed，写 content、message_citations、answer_kind 和 completed。拒答为 completed+refused，服务故障为 failed。
6. 停止请求与完成写入按同一助手消息串行化，先到的终态生效；未校验的流式片段不能附上完整引用。
7. 请求执行中续租，重启后将过期活动助手消息标为 failed。保留 partial 文本，不自动重发模型请求；用户重试使用新的 client_request_id。

会话 scope 修改只影响之后的提问。标题或分类变化不改变引用快照；文档新版本发布后，历史引用仍打开原 version_id 的文件。软删除后停止新检索，历史来源可标为 removed；首版不做自动物理清理。

## 7. 约束、索引与前端映射

### 数据库与服务的分工

| 数据库直接约束 | 服务必须校验 |
| --- | --- |
| 当前版本属于本 document | 指向可用版本，版本发布先后正确 |
| 同文档原件 hash 唯一 | 上传入口服务端重新计算文件指纹、全库检查，并持有同指纹事务锁直至登记完成 |
| active import 指针属于本 version | 目标类型 import、状态 ready、产物完整 |
| graph source_job 与本任务同 version | source_job 类型为 import，已完成且来源切片合法 |
| chunk 的 job/version/profile/dimension 组合一致 | blocks/locators 真正对应原文；向量由正确模型产生 |
| 消息答复不跨 session、消息序号/请求 ID 不重复 | reply_to 为 user；request_snapshot 为服务生成的有效范围 |
| citation 的 message/chunk 存在、编号唯一 | message 是 assistant；chunk 属于本轮范围；引文与编号真实有效 |
| JSON 形状、枚举、页码、hash、计数 | JSON 内文档 ID、块 ID、快照字段和引用的语义 |

### 索引

DDL 包含文档按时间/分类的游标分页、版本号和 hash 去重、任务认领/投递/租约恢复、最新 ready graph、会话历史、会话内单活动回答、引用反查等索引。唯一约束已覆盖的前缀不重复建索引。

元数据搜索先用带参数的 ILIKE，数据增长后增加 pg_trgm；正文和向量只按当前可用或本轮固定的 job 查询。BM25 缓存按 job 清单和切片配置签名失效。引入 ANN 前验证范围过滤后的召回，不能先全库取少量结果再过滤。

### 接口与原型功能

| 原型功能 | 数据来源与接口约定 |
| --- | --- |
| 文档列表、分类、搜索 | documents 与当前 version/job 摘要；category 为字符串，分类计数 GROUP BY category；列表不取正文/向量 |
| 当前可问答 + 更新处理中 | current_version/active_import 与 latest_processing 分开返回，不能用一个状态互相覆盖 |
| 上传与失败重试 | POST /api/documents/check-duplicate；POST /api/documents；POST /api/documents/{id}/versions；GET /api/processing-jobs/{id}；POST /api/processing-jobs/{id}/retry |
| 正文、解析片段与 PDF | 按 active import 读 document_contents/chunks；GET /api/document-versions/{id}/file 始终打开该版本原件 |
| 新建/历史会话与范围选择 | POST/GET /api/sessions；PATCH /api/sessions/{id}/scope（带 expected_scope_revision） |
| 发送与停止生成 | POST /api/chat（session_id、client_request_id、scope_revision、text）；POST /api/chat-messages/{id}/stop，id 为助手消息 ID |
| 回答引用 | message_citations → chunks → document_versions，恢复标题/页码快照；GET /api/chunks/{id} 不返回向量 |
| 图谱搜索、展开/收起 | processing_jobs 的 ready graph + Neo4j；GET /api/graph 返回五类节点、关系、sources、fingerprint 与 has_more |

接口适配层可以继续返回当前原型使用的 status、pages、category、sources 等展示结构，前端无需理解表数量或 JSONB 存储方式。真实流式协议在 AI SDK 实际版本下验证，不能把原型定时器当成真实任务状态。

## 8. 迁移与分阶段验证

设计附件保留为 DDL 参考；实际建表由 backend/migrations/versions/0001_core.py 及冻结 SQL 快照管理，已在本项目的独立数据库执行。创建顺序为 documents → document_versions → processing_jobs → 补发布指针 → 正文/切片 → 会话/消息/引用。后续改表添加新迁移，不让已执行迁移依赖可变的设计文档。

实际 PostgreSQL/Neo4j 集成验证至少覆盖：

- 同一新建 document_id 重试、同文档同 hash 重传、同名不同文件、显式新版本与两个并发上传。
- 同 job 重复投递、发送前崩溃、Broker 收到但 Worker 未认领、租约过期后旧 Worker 晚到、MinerU 提交结果不确定。
- 新版本/重建失败仍可使用旧结果，较旧版本/代次迟到不能倒退发布指针。
- source_job 类型错误、chunk 代次/profile/维度错配、内容块缺失、PDF 页码无效、DOCX/MD 无页码。
- scope JSON 中无效/已删除文档、custom 空范围、修改范围不影响旧回答、服务不能接受伪造 snapshot。
- 同会话并发问答、请求重发、停止与完成竞争、进程重启后的遗留生成请求。
- 引用非助手消息、范围外切片、错误页码/引文/编号；更新标题、版本或软删除后仍能打开历史原件。
- 图谱抽取成功但投影失败、相同结果重放、过期投影 Worker、80 节点上限和图谱 fingerprint 改变。

2026-11-14 离线校验结果：

- pglast 解析 DDL 通过，确认 8 张表、101 个字段、11 个外键、55 个 CHECK 和 11 个显式索引；外键列存在、类型与唯一目标匹配，CHECK/索引引用的列均存在。字段说明与 SQL 列清单一致。
- Mermaid 解析通过：本稿的 1 张 ER 图、2 张状态图，以及整体设计中的导入流程图；ER 实体集合与 8 张表一致。
- 2 个 JSON 示例、实施计划中的 5 个 Python 示例语法和四份关联文档的 13 个本地 Markdown 链接检查通过；README、整体设计和实施计划已同步精简模型与接口路径。

以上为设计阶段的静态检查记录。基础工程阶段随后已执行真实迁移、18 项默认测试和 35 项真实集成测试，包括引用保存及跨事务停止/范围冲突；具体覆盖范围见[开发记录](../../dev-notes/backend-foundation.md)。上述清单中涉及完整 Worker、MinerU、发布调度、模型生成和图谱投影的用例仍待后续业务阶段执行，不能将基础测试通过等同于完整链路通过。

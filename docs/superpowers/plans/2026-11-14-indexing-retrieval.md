# 文档索引与混合检索实施计划

> 使用 superpowers:executing-plans，按已确认设计与本轮“开始下一步”的授权单代理执行。沿用当前 feat/document-import 工作区，保留既有修改；不自动提交或合并。

**Goal:** 上传后自动切片、向量化和发布索引，按关键词与语义混合检索、重排并查看固定版本来源。

**Architecture:** PostgreSQL 保存按 job 隔离的切片/向量；导入任务分批嵌入、持久化检查点，全部校验通过后锁定 document→version→job 发布。检索固定本轮已发布 job 清单，BM25 与 pgvector 双路召回经 RRF 去重后重排。原文检索和切片预览接到现有文档管理页面；本阶段不生成问答答案。

**Tech Stack:** Python 3.12 / SQLAlchemy / pgvector / jieba / rank-bm25 / Celery / 千问 Embedding 与 Rerank / React / TypeScript。

**Spec:** docs/design.md 的解析、切片与检索设计；docs/implementation-plan.md Task 5，以及 Task 7 的切片/来源预览部分。

## Global Constraints

- PostgreSQL 是文档、切片、向量、任务和会话的事实来源；保留 8 张核心表。
- 单代理；不丢弃当前 checkout 的修改，不复制其他项目凭证，不修改 test-data 原件。
- 固定 1024 维实际模型配置；按 profile 隔离向量空间，失败不得当成无文档。
- 真实云调用显式执行，默认测试只替换外部模型边界，PG/RustFS 使用真实隔离环境。
- 当前数据规模先使用 pgvector 精确距离查询；不额外引入搜索服务或未验证的 ANN 索引。

### 1. 可回溯的切片

**Files:** 新增 backend/app/retrieval/chunking.py、profile.py、tests/test_chunking.py。

**Interfaces:** `chunk_document(job_id, blocks, max_chars=1600, overlap_chars=150) -> list[ChunkDraft]`；`validate_drafts(blocks, drafts)`；`embedding_text(content, heading_path)`；`embedding_profile(settings)` / `digest_profile(profile)`。

- [x] 先测试稳定 UUID/ordinal、长正文连续覆盖、同章节跨页范围、DOCX/MD null 页码、来源篡改拒绝。
- [x] 表格保持表头、标题、脚注、完整数据行和 rowspan 关联；过大时重复真实表头分组，并带上相邻同章节正文上下文。测试金额、审批岗位与适用条件不丢失。
- [x] 所有正文片段保留 block_id 和字符区间；表格保留行区间，校验内容能从原始 blocks 重建；正文不注入模型生成内容。
- [x] 运行切片测试先确认失败，再实现并确认通过。

### 2. 索引任务、分批恢复与发布

**Files:** 新增 backend/app/tasks/indexing.py、tests/test_indexing_jobs.py；修改 tasks/documents.py、importing/service.py、contracts.py、api/parsing.py、api/jobs.py、tests/test_import_api.py。

- [x] 真实 PG/RustFS 测试切片入库、模型维度错误、批次中断恢复不重复嵌入已保存向量、旧租约拒写、未完整嵌入不发布、过期旧版本/代次不倒退发布指针。
- [x] 新上传任务快照包含 chunker、模型、维度、文档/查询类型和嵌入文本格式；config 不含密钥。每批不超过 20 条，成功批次事务保存向量，继续投递不消耗 attempt。
- [x] 已保存 DocumentContent 后直接恢复索引，不再次调用 MinerU。新增固定版本 `POST /api/document-versions/{id}/reindex {job_id}`，复用该版本可用解析结果创建新代次；保留“重新解析”的原语义。
- [x] 解析→切片→嵌入→发布均按当前租约校验；完整后写 ready/done 并按 version_no/generation_no 单调更新指针；旧 ready 结果和历史来源保留。
- [x] 更新集成夹具：未显式启用索引的原解析测试使用 not-configured；清理先解除发布指针，再删除 chunks/content/jobs/versions/docs。

### 3. 固定资料范围的混合检索

**Files:** 新增 backend/app/retrieval/search.py、ranking.py、api/search.py、tests/test_ranking.py、tests/test_search_api.py；修改 main.py。

**Interfaces:** `POST /api/search {question, document_ids?, top_k}`；`GET /api/chunks/{id}`；`GET /api/document-versions/{id}/chunks?job_id=`。

- [x] 先测试 RRF 按 chunk_id 去重、中文/金额关键词检索、范围只含当前发布版本、旧版本与未完成任务不参加召回、显式空范围/无效范围拒绝。
- [x] 在一致读事务中固定 ready job 清单和 metadata；BM25 缓存按 job 清单失效；向量只查固定 profile/job，防止同轮切换版本。
- [x] 双路候选合并去重；有界候选/文本预算调用真实 Rerank 客户端，按原索引映射结果，保留 chunk/version/job/locators。
- [x] 模型故障的降级带明确 warnings；没有结果且召回失败时返回服务错误。模型 profile 变化要求重建，不能混排或伪装为空库。
- [x] 固定来源接口不返回 embedding，历史 ready job 可读；未发布切片不暴露为可检索结果。

### 4. 原文检索与切片预览

**Files:** 新增 frontend/src/KnowledgeSearch.tsx、IndexedChunks.tsx；修改 DocumentsPanel.tsx、App.tsx、api.ts、document-types.ts、useParsedVersion.ts、ParsedView.tsx、upload.css 与 API 测试。

- [x] 先测试检索请求范围、来源固定 version/job 与重建索引的稳定请求 ID。
- [x] 文档管理支持检索正文，展示命中文档、章节和真实引文，点击打开固定版本切片，可跳回正文或 PDF 页。
- [x] 增加已发布切片预览与“重建索引”；处理中保留旧结果，错误可重试。ready 资料在本阶段显示“可检索”，问答输入仍明确待接入。
- [x] 前端测试、Node 22 构建与浏览器验证检索、范围、正文定位；版本/job 切换由接口回归验证。

### 5. 真实验收与收尾

- [x] 重建 Worker/Beat 并重启 API；显式导入测试资料中的报销/请假/采购文档，验证到 ready。
- [x] 用三类问题检查 Top-K 内容、金额/条件、版本/页码、去重与重排；验证一次重建索引复用解析、不新增云解析任务。
- [x] 保留脱敏验收记录；清理本轮临时数据库记录与对象，保留 test-data。
- [x] 运行完整后端默认/真实基础设施测试、Ruff、Alembic check、前端测试/构建；复核无真实凭证进入仓库。
- [x] 更新 README、总计划和开发记录，明确检索已完成，生成回答/会话/图谱仍待后续。

**执行结果：** 后端 162 项、前端 34 项通过；Ruff、Alembic check、Node 22 构建通过。真实三份 PDF 共 47 个切片；受控失败恢复和复用解析重建通过。浏览器验证检索范围、固定来源、正文定位和 PDF 第 3 页；窄屏 390px 无横向溢出。临时数据已按登记 ID 清理，云凭证扫描无匹配，`.env` 权限 0600。详见 `docs/dev-notes/indexing-retrieval.md`。

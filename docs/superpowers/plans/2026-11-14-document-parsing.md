# Document Parsing Implementation Plan

> 按已授权范围使用 superpowers:executing-plans，单代理在当前 feat/document-import 工作区顺序执行；保留已有修改。

**Goal:** 接入 MinerU PDF/DOCX 云端解析与 Markdown 本地解析，持久化真实正文和资源，提供固定版本重新解析与预览。

**Architecture:** 解析器输出统一内容块；Worker 通过 PostgreSQL 检查点分次提交、上传、轮询和保存归档。DocumentContent 按 job 隔离存储，重新解析保留旧结果；尚未建立索引时不发布 ready 或 current_version/active_import 指针。

**Tech Stack:** Python 3.12 / httpx / markdown-it-py / pypdf / FastAPI / SQLAlchemy / Celery / RustFS / React / TypeScript。

**Spec:** docs/design.md（文档处理）与 docs/implementation-plan.md Task 4。

## Global Constraints

- Python 3.12、Node 22、pnpm 10；保留依赖锁文件。
- 不修改 test-data 原始资料；测试对象使用隔离前缀并清理。
- MinerU Token 只从私有环境读取，不进入任务快照、错误、日志和协议夹具。
- DOCX/MD 页码为 null，PDF 页码只转换一次为 1-based；原件页数由 PDF 读取。
- 真实云端验收分别覆盖 PDF/DOCX；mock 协议测试与真实云端验收分开记录。

### Task 1: 统一内容块和归档读取

**Files:** 新增 backend/app/importing/parsing.py、archive.py、tests/test_parsing.py。

**Interfaces:** `parse_markdown(content: bytes) -> ParsedDocument`；`read_archive(content: bytes, format: str) -> ParsedDocument`，包含 markdown、blocks、assets、page_count。

- [x] 测试 MD 标题路径、表格金额/条件、代码和缺失页码；测试 MinerU table/image、0-based 页码、路径穿越、重复文件、压缩/解压大小限制。
- [x] 运行 `uv run --project backend pytest backend/tests/test_parsing.py -q`，先确认缺少实现失败。
- [x] 使用 token AST 和受限 HTML table 解析，生成稳定 block_id、章节路径、定位与资源关联；ZIP 只按校验后成员读取，不解包到磁盘。
- [x] 运行上述测试确认通过。

### Task 2: MinerU 协议和配置

**Files:** 新增 backend/app/importing/mineru.py、tests/test_mineru.py；修改 config.py、pyproject.toml、uv.lock、.env.example。

**Interfaces:** `MinerUClient.submit(filename, data_id) -> dict`、`upload(url, bytes)`、`poll(batch_id, data_id) -> dict`、`download(url) -> bytes`。

- [x] 测试单 Token 只发给 API、预签名上传/下载无认证头、远端错误脱敏、URL 边界与下载上限。
- [x] 运行协议测试确认缺实现失败；按官方 v4 file-urls/batch 与 extract-results/batch 实现，禁用重定向。
- [x] 配置 token SecretStr、固定 API 来源、模型/语言、轮询和截止时间、受限资源域名。
- [x] 运行测试；通过真实 Token 只读验证认证，不在输出中包含 Token。

### Task 3: 检查点、结果持久化与重新解析

**Files:** 修改 importing/service.py、tasks/documents.py、contracts.py、views.py；新增 api/parsing.py、tests/test_parsing_jobs.py。

**Interfaces:** `POST /api/document-versions/{id}/reprocess {job_id}`；`GET /api/document-versions/{id}/parsed?job_id=`；`GET /api/processing-jobs/{id}/assets/{asset_id}`。

- [x] 真实 PG/RustFS 测试 MD 落库、重复消息、旧租约拒写、重新解析幂等/活动冲突、旧结果保留与固定 job 读取。
- [x] 测试远端 batch 检查点恢复、普通轮询不消耗 attempt、未知提交结果不重发、截止时间和下载失败重试。
- [x] 在外部提交前持久化提交意图；返回 batch 后持久化上传 URL；上传和查询重入复用原 batch；分次轮询通过 next_dispatch_at 调度。
- [x] 归档/图片按 job 与 lease_token 隔离保存；持有当前租约时事务插入 DocumentContent。parse 完成停在 chunking，记录 index_not_configured，can_query=false。
- [x] reprocess 按 document→version→job 锁定、稳定请求 UUID 幂等、同版本活动任务返回 409 及既有 job_id，避免将未持久化的请求键误当成已接受；不改原件、已有结果和已发布指针。
- [x] 扩展测试夹具清理 DocumentContent 与隔离解析对象，运行全部任务集成测试。

### Task 4: 解析结果界面

**Files:** 新增 frontend/src/ParsedView.tsx；修改 App.tsx、api.ts、document-types.ts、状态筛选与 upload.css；扩展 frontend/tests/documents-api.test.ts。

- [x] 先测试 parsed 状态与 fixed-version 路由映射，再实现 API 读取和重新解析。
- [x] 正文按真实标题/段落/表格/代码/图片渲染；解析片段提供 block_id、章节、真实页码与跳回 PDF 原件；未提供页码时仅显示章节。
- [x] 新解析进行时保留可读旧结果；明确“解析完成，尚未建立索引”；选择版本时读取对应版本的任务和结果。
- [x] 前端测试与构建，浏览器验证上传→解析→正文/表格/资源→原件定位→重新解析。

### Task 5: 云端验收与交付

- [x] 重建 Worker/Beat 并重启 API，私有 Token 仅经环境注入。
- [x] 分别上传测试 PDF 和 DOCX，确认正文、表格、图片、页码和远端恢复；保存脱敏协议样本与验收记录。
- [x] 完整运行后端单测/真实集成、Ruff、Alembic check、前端测试/Node22 构建。
- [x] 清理本轮临时验收资料，保留用户资料和 test-data；更新 README、开发记录与总计划。

执行记录：采用单代理复核。固定版本重新解析遇到其他活动任务时返回 409，而不是将未保存的客户端请求键视为已接受。远端 done 后新增 downloading 检查点，独立 24 小时下载期限。最终 112 项后端测试、31 项前端测试、Ruff、迁移检查、Node 22 构建和真实云端/浏览器验收完成。

# 真实文档上传与任务接入 Implementation Plan

> 按已授权范围使用 superpowers:executing-plans 单代理顺序执行。沿用当前包含指纹和弹窗修复的 checkout，不丢弃已有修改。

**Goal:** 上传 PDF/DOCX/Markdown，原件与文档/版本/任务持久化，刷新恢复列表、读取固定版本原件；全库重复文件只登记一次；真实 Celery 投递与恢复，移除页面预置测试资料。

**Architecture:** FastAPI multipart 上传与 metadata/file/job 路由，PostgreSQL 事务登记，RustFS 保存原件；共享指纹事务锁负责跨请求去重。独立 Linux Celery Worker 与 Beat 处理投递和租约恢复，PG 仍是任务事实来源。当前处理器验证原件后明确记录解析未接入，不伪造 ready。

**Tech Stack:** Python 3.12 / uv / FastAPI / SQLAlchemy / psycopg / boto3 / Celery / Redis / React / TypeScript。

**Spec:** ../specs/2026-11-14-database-design.md 与 ../../implementation-plan.md Task 3。用户已授权本阶段，AI SDK 协议验证留作真实问答接入的前置，不阻塞不依赖消息流的上传链路。

## Global Constraints

- Python 3.12、Node 22、pnpm 10；保留锁文件，镜像固定实际验证的版本和 digest。
- 不复制参考项目密钥；不复用/删除其他项目数据卷。
- API ID 用字符串；列表不读全文、块和向量；无可靠页码不编造。
- 同 ID 不同原件新建返回 409；新版本显式上传；软删除不阻止重新导入。
- PG 与对象存储不是同一事务，失败留下的无引用对象按保留期清理；历史原件不覆盖。
- 普通重复上传不重启失败任务、不重置尝试次数；Worker 重复消息和过期令牌不得重复处理。
- 从默认页面移除种子文档、示例会话和固定来源，不删除 test-data 原始验收语料。

## 1. 上传、列表与固定版本读取

**Files:** backend/app/importing/{validation,storage,service}.py、backend/app/api/documents.py、backend/app/views.py、backend/tests/test_import_validation.py、backend/tests/test_import_api.py。

- [x] 先测试实际字节签名/大小、稳定 ID 重试、同 ID 不同文件、跨 ID/并发去重、显式新版本、列表无正文、原件 GET/HEAD/Range。
- [x] 运行测试确认缺少业务接口/模块失败，再实现 `ImportService.create/add_version`；登记版本及 queued job，在调用方事务内持有指纹锁。新增请求返回 202，重复返回 200 和既有身份。
- [x] `GET /api/documents?offset=0&limit=100` 返回 items/total；`GET /api/documents/{id}` 返回摘要；原件以固定 version_id 读取，支持 HEAD/Range 和正确 MIME/UTF-8 文件名。先上传成功的版本可读取，不依赖 ready 发布指针。
- [x] 真实 PG/RustFS 验证文件字节一致、重启 API 后记录仍可读；测试对象使用隔离前缀并清理。

## 2. 异步任务和恢复

**Files:** backend/app/tasks/{celery_app,dispatch,documents}.py、backend/app/api/jobs.py、backend/Dockerfile、compose.yaml、backend/tests/test_import_jobs.py。

- [x] 先测试 broker 发送失败保留 queued 与补发时间、重复消息只认领一次、租约恢复后拒绝旧令牌、重试上限和配置错误非自动重试。
- [x] 实现 `dispatch_pending/recover_expired/process_document/retry_job`。投递时间/次数先提交再发送；发布失败不撤销已接受上传。原件校验通过但缺少解析器时保存明确不可重试配置状态，保留原件可读。
- [x] `GET /api/processing-jobs/{id}` 返回原始状态/阶段/错误/次数；显式 retry 仅允许可重试 failed 且次数未达上限。
- [x] 建立 Linux Worker/Beat 镜像与服务配置，验证真实 Redis 及“停止 Worker 上传—恢复 Worker 继续处理”。
- [x] 未引用原件保留 24 小时后清理，数据库不可确认时不删除；仅扫描本项目原件前缀。

## 3. 前端业务接口与清除种子

**Files:** frontend/src/{api,document-types}.ts、App.tsx、UploadDialog.tsx、DocumentsPanel.tsx、WorkspaceSidebar.tsx、ScopeDialog.tsx、GraphPanel.tsx。

- [x] 先测试业务摘要映射、缺失页码、错误/取消状态及上传重试沿用 document_id。
- [x] 上传由提交结果驱动，可见逐文件成功/重复/失败，关闭取消不误关弹窗或伪称撤销已接受上传。文档列表读取真实 API 并在 queued/running 期间刷新；错误允许重试，不回退种子资料。
- [x] 固定版本原件在 PDF 阅读器、新窗口入口读取；Markdown 安全纯文本预览；DOCX 明确说明在线预览能力；展示实际状态、原件版本和错误，可对适用任务重试及上传新版本。
- [x] 移除 frontend/public/demo 和前端 seed JSON，清空默认示例会话/来源/图谱；空库和未接入问答/图谱提供明确空状态。保留 ECharts 组件和原始 test-data。

## 4. 验收与记录

- [x] 后端默认与真实集成测试、Ruff、Alembic check、前端测试与构建。
- [x] 浏览器上传→刷新列表→PDF/MD 原件→重复/改名→新版本→真实失败状态；再次核对文件选择器 cancel。
- [x] 清理全部临时验收 PG/RustFS 数据，确认页面为空库且源 test-data 保留；更新 README、总实施计划与开发记录，明确解析/索引/真实问答仍待接入。

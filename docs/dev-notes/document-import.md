# 真实文档上传、版本与任务恢复

日期：2026-11-14。用户授权接入真实上传/持久化/原件/队列，并移除页面预置测试文档。沿用已有 checkout，工作分支为 feat/document-import；原始 test-data 不修改。

## 已交付

- FastAPI 新建 multipart 上传与显式新版本接口，支持 PDF、DOCX、UTF-8 Markdown，单文件 20 MB。扩展名、文件签名、大小和内容编码在服务端检查。
- RustFS 原件与 PG 文档、版本和 queued job 登记。客户端同一文件重试沿用 document_id；同 ID 不同字节返回 409；全库指纹锁和文档身份锁防止并发重复。相同文件直接返回已存在的 document/version/job，不再存对象或启动新任务。
- 元数据列表、文档详情与版本列表；固定 version_id 原件 GET、HEAD、单范围 Range/206/416、正确 MIME 和 UTF-8 原件名称。历史版本原件不覆盖，列表不加载正文、块和向量。
- 文档 Worker 与 maintenance 队列、Beat 定期补发、租约恢复、过期令牌拒写、有限次数显式 retry；失败和成功投递均记录在 PG。Worker 很快完成时，仍写 last_dispatched_at，保留其终态错误。
- 未引用原件保留 24 小时后清理，仅扫描本项目原件前缀。历史版本/软删除对象仍有数据库引用，不当作孤儿；PG 查询失败会中止清理。
- React 真实上传、列表、处理状态、上传新版本与历史版本切换。PDF 可读及翻页，Markdown 安全纯文本展示，DOCX 提供原件新窗口入口。关闭文件选择器不误关弹窗；关闭已提交的上传窗口不会宣称撤销服务器写入。失败的请求保留可重试身份。

页面不再加载 frontend/public/demo、demo-documents.json、demo-sources.json 或固定问答；四份 PDF 副本及 seed 模块已删除。图谱样例移到 frontend/tests/fixtures，仅用于已有渲染回归。问答/图谱显示待接入，文档初始为空库。

## 当前处理能力边界

本阶段对应总计划 Task 3，不包含 MinerU、切片、Embedding、RAG 或图谱抽取。Worker 会真实认领任务、读取原件并核对指纹，随后记录 parser_not_configured，raw status=failed、retryable=false。前端将该已知配置状态显示为“原件已保存”，同时展示“解析功能尚未接入”；can_query=false，不写 ready 或发布指针。

上传成功与处理结果分别展示。对象存储临时故障等错误保留 retryable=true，且尝试次数未到上限时才提供“重试处理”。普通重复上传不能绕过重试限制；后续接入解析时应走显式新代次重建，不自动重新收费处理历史失败任务。

初始 embedding profile 标记 not-configured，1024 是候选维度，尚未调用真实模型，不把它描述成已验证向量空间。

## 运行环境

后端依赖增加 python-multipart 0.0.33 并锁定 uv.lock。Linux 镜像使用 python:3.12.14-slim-bookworm，digest 为 sha256:392307d22300de8b5986851a12d9176dfc0fc073e65bf6523ebd7dcbeb23564e；uv 0.12.19 从冻结锁文件安装生产依赖，运行用户 UID 10001。

Compose 使用 Worker/Beat 的本地构建镜像 enterprise-knowledge-assistant-backend:0.2.0，容器内依赖地址覆盖为 postgres/redis/rustfs 服务名；本机 FastAPI 继续使用映射端口。只新增本项目 Worker/Beat，未重建、复用或删除旧 Knowledge Hub 数据卷。

启动顺序与 Worker 更新命令见根 README。Worker/Beat 不代替迁移或建桶，先初始化依赖、执行 Alembic 与 bootstrap，再启动它们。队列状态以 PG 为准，不使用 Redis 中的消息数量判断文档是否已处理。

## 验证证据

后端 81 项测试通过（31 默认 + 50 真实集成），Ruff 检查/格式检查与 Alembic check 通过；不增加业务表，迁移仍为 0002_file_fingerprint。新增测试先验证缺少实现失败，再实现并通过。原有基础、引用和并发持久化测试也通过。

前端 29 项测试、TypeScript 与生产构建在 Node 22.21.0 验证通过；亦在本机 Node 24/25 验证。图谱测试改用 tests/fixtures，避免移除页面种子后空循环造成假通过。保留既有 PDF 分包大小提醒，Node 22 的 MockTimers 测试有原有实验性提示。

真实服务与浏览器验收：

- 空库起步，通过页面上传 PDF；暂停本项目 Worker 时任务保持 queued/attempt_no=0；恢复后 attempt_no=1，重复投递不重复认领，明确停在解析未接入状态。
- 刷新仍能看到真实文档并预览 PDF；固定版本真实原件可翻页；改名后相同字节被阻止。
- Markdown 原件保留文本和脚本字面量，不执行 HTML；不虚构页码。上传第二版本后可在两份真实原件之间切换，关闭后重新打开仍保留版本列表。
- 实际 DOCX 原件提供新窗口打开入口，不使用 PDF 阅读器；伪装成 PDF 的无效字节由服务器拒绝，上传弹窗显示具体错误并保持打开。
- 390px 原件面板无横向溢出；空会话历史与空图谱没有旧示例记录。
- 额外通过真实 HTTP 上传 Markdown 后重启 FastAPI，重新请求文档和原件，字节保持一致。

修复并覆盖：JSONB 的错误字段清空需 SQL NULL；成功投递后 Worker 已终态时不能漏写投递时间或擦除处理错误；同一文档重新打开必须刷新版本列表。

## 清理与下一阶段

第一轮浏览器的 3 个文档、4 个版本及 4 个原件，以及 API 重启验收的 1 个文档/版本/原件，均按记录的具体身份删除，未批量清空业务表或桶。默认页面已恢复空库，仓库 test-data 原始语料保持不变。

下一阶段是 MinerU PDF/DOCX 解析、Markdown 规范化、切片与定位、Embedding/索引发布；随后再接入 AI SDK 协议和真实问答。当前没有云模型或 MinerU 调用结果，不把本阶段任务执行称作完整 RAG 导入。

后续更新：MinerU 与 Markdown 解析、重新解析及结果预览已接入，当前行为见[真实解析记录](document-parsing.md)。上文 parser_not_configured 为导入阶段验收时的历史状态。

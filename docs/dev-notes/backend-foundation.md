# 后端基础与数据库落地记录

日期：2026-11-14。依据 [8 表设计](../superpowers/specs/2026-11-14-database-design.md) 和 [本阶段执行清单](../superpowers/plans/2026-11-14-backend-foundation.md)，完成用户确认的四步。前端原型仍使用固定演示数据；本阶段没有把基础代码称作完整上传、RAG 或图谱抽取服务。

## 1. 已落实内容

| 阶段 | 实现与证据 |
| --- | --- |
| 后端初始化 | Python 3.12.14、uv.lock、FastAPI、环境配置、前端域 CORS；`/api/health/live` 与 `/api/health/ready` 已实际请求 |
| 独立基础设施 | Compose 新网络、新命名卷与本机端口；PostgreSQL 16.14 + pgvector 0.8.2、Redis 7.4.2、RustFS 1.0.5、Neo4j 5.26.0；镜像固定标签及 digest，均已运行 |
| 建表与迁移 | 8 个 SQLAlchemy ORM 实体、101 个字段；Alembic `0001_core` 已执行；`current` 返回 head，`check` 无结构差异；回退和重建只在独立测试库验证 |
| 真实约束与原型对照 | 18 项默认测试 + 35 项真实集成测试；包含文档摘要、范围保存、最终回答/引用持久化与跨事务状态校验 |

代码位于 `backend/app/`。应用启动不调用 `create_all`，建表由迁移显式执行；初始迁移 SQL 是冻结快照，后续改表另加迁移。正文、块和向量设置延迟加载；文档摘要直接选择元数据和页数，不返回全文。

数据库另有 Alembic 自带的 `alembic_version`，用于记录迁移版本，不属于 8 张业务表。

配置从项目 `.env` 与 `KH_` 环境变量读取。`backend/scripts/init_env.py` 创建独立随机凭证，文件权限为 0600；不会覆盖已有文件。配置示例使用占位密码；SecretStr 在对象表示中隐藏秘密值，健康检查只返回依赖布尔值，日志只记录失败依赖和异常类型。

## 2. 与前端原型逐项对照

| 原型中的展示/行为 | 本阶段的数据准备 | 接入业务接口时的要求 |
| --- | --- | --- |
| 文档标题、分类、文件名、大小和版本 | documents + document_versions；DocumentSummary 返回对应摘要 | 使用 UUID；不依赖 finance/leave 等示例 ID，不限制为四份文档 |
| `pages.length` 显示页数 | 独立 page_count；PDF 真实页数可空，MD/DOCX 不编造页码 | 列表改读 page_count，正文或某页内容按需加载 |
| 等待处理、解析、切片、索引、可问答、失败 | 统一 job 的 status/stage 映射为原型标签；publishing 仍显示建立索引 | 任务原始 canceled 需补“已取消”标签，不能一直显示处理中 |
| 可问答与新版本更新中/失败 | status/can_query 与 latest_processing 分开返回 | 新版失败保留旧版可用入口；不以最新任务状态覆盖全部文档状态 |
| 全部知识库/自选文档 | scope JSON + scope_revision；自选集合必须有效且可问答 | 原型 documentIds=null 对应 mode=all；自选为空或不可用不能扩大范围 |
| 历史会话与回答状态 | chat_sessions、chat_messages，单活动回答与请求 UUID 唯一约束 | 后续发送接口生成本轮快照；不能信任客户端传来的历史和资料快照 |
| 点击引用打开原文/页码 | message_citations 固定 chunk、version、job、标题和定位 | 用 version_id 的原件接口；DOCX/MD 按章节/块定位；编号由后端组装 |
| 停止生成与完成竞争 | 最终写入锁助手消息，并刷新已加载的 ORM 对象 | 另一个事务先停止后，旧会话对象不能把消息改回 completed |
| ECharts 图谱与来源 | processing_jobs 为 graph 留出统一类型，来源与索引代次一致 | Neo4j 已连通；抽取、投影、局部图 API 和 ECharts 接口适配在后续阶段完成 |

`save_scope` 和 `complete_answer` 是持久化边界，调用方负责外层事务；本阶段不创建可发起真实模型调用的聊天 API。引用写入前验证助手角色、终态、本轮资料范围、原文引句和正文编号；最终正文、引用和 completed 同事务落地。更完整的请求接受、租约、Worker、发布和图谱语义校验仍按总计划实现。

## 3. 实际验证记录

- 后端完整运行：`uv run --project backend pytest backend/tests -m 'integration or not integration' -q`，53 passed；默认模式 18 项，显式 integration 模式 35 项。
- 真实 PG 覆盖：同文档同 hash 拒绝重复，不同逻辑文档允许相同字节；当前版本不能跨文档；同版本单活动导入；切片的 profile/维度/页码；事务回滚；范围 JSON 形状；同会话单活动回答和跨会话答复拒绝。
- 服务校验覆盖：自选范围无效或修订号过期时拒绝；引用不在快照范围、引文不匹配、编号错误、用户消息引用或已停止消息完成时拒绝；标题变化后已有引用快照保留原值；跨事务停止和范围修改不能被旧 ORM 对象覆盖。
- RustFS 通过真实 boto3 建桶、PUT、GET、HEAD、Range 206、列表和删除；Redis PING 与键读写；Neo4j 验证连接和参数化查询。
- 在四个服务写入隔离标记后，执行 `docker compose up -d --force-recreate --pull never --wait --wait-timeout 90`，重建后 PG 行、Redis 值、RustFS 原件和 Neo4j 节点均可读取；验证完成删除全部隔离标记，未清理数据卷。
- 健康检查真实故障演练：停止本项目 Redis 时 live=200、ready=503 且 redis=false；恢复后 ready=200，四项依赖均为 true。
- Ruff 检查与格式检查通过；Alembic 升级可重复，测试库回退至 base 后可重建 8 表，check 无待生成变更。
- 前端原有 20 项测试与生产构建通过；另在 Node 22.21.0 / pnpm 10.30.3 下重复验证。25 个原型源码、配置和测试文件的 SHA-256 与实施前一致。构建仍有原有 PDF 阅读器分包体积提醒，本阶段未调整界面或资源分包。

## 4. 启动与重跑

从项目根执行的启动步骤见 [README](../../README.md)。后端端口为 8014，前端预览端口为 5174；四项依赖端口为 5544、6384、9014/9015、7484/7694。仅绑定回环地址。现有 Knowledge Hub 的容器和数据卷未被启动、复用或删除。

持久化重建检查可重复执行：

```shell
uv run --directory backend python -m scripts.verify_persistence prepare
docker compose up -d --force-recreate --pull never --wait --wait-timeout 90
uv run --directory backend python -m scripts.verify_persistence verify
```

脚本只创建并删除带自身 UUID 的标记，清单在忽略目录 `.local/`；异常退出后保留清单，恢复服务后重跑 verify。不要使用 `down -v` 验证重启持久化，该选项会删除命名卷。测试迁移使用本项目单独的 `knowledge_assistant_test` 库，不对应用库执行回退。

下一阶段是文档新建/版本 API、原件上传、统一任务投递和 MinerU 解析，随后接入切片与索引；模型凭证、真实模型调用和全量语料评测尚未执行。

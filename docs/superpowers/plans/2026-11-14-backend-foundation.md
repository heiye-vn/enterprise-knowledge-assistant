# 后端基础与数据库落地：执行清单

已获用户授权执行；范围是本阶段的四步，按单代理顺序推进。依据 [8 表设计](../specs/2026-11-14-database-design.md)，保持现有前端原型作为界面基准。

- [x] 1. FastAPI 基础工程：Python 3.12/uv 锁文件、环境配置、存活/依赖健康检查、前端开发域 CORS。
- [x] 2. 独立基础设施：Compose 配置 PG16/pgvector、Redis、RustFS、Neo4j；镜像固定、回环端口、新数据卷；真实连通、对象存储读写与持久化验证。
- [x] 3. 数据库落地：8 表 SQLAlchemy 模型和可升级/回退的 Alembic 初始迁移；真实执行，验证迁移与模型无差异。
- [x] 4. 约束及原型对照：真实 PG 测试版本归属、文件去重、任务状态、切片向量、会话范围、消息和引用保存；补 JSON 的服务校验及文档映射契约；前端基线回归。

实施顺序：先运行健康检查/契约测试确认缺少实现时失败；实现配置和基础服务；数据库集成测试先验证缺表，再执行迁移并验证约束。每阶段以实际命令结果记录。

本阶段交付基础代码、可运行环境、建表迁移、测试、启动说明和原型对照记录。真实上传/解析/索引、模型问答和图谱抽取属于下一业务阶段，不将这些演示能力标为已接入。本阶段在原型源码之外新增基础代码，后续通过接口适配保持页面和交互一致。

## 验收命令

从项目根执行：`uv run --project backend pytest backend/tests -q`；`uv run --project backend pytest backend/tests -m integration -q`；`uv run --project backend alembic -c backend/alembic.ini upgrade head`；`uv run --project backend alembic -c backend/alembic.ini check`；`docker compose ps`；`pnpm --dir frontend test` 与 `pnpm --dir frontend build`。

真实服务测试只使用本项目测试库和隔离对象前缀，不清理或复用其他项目的服务、桶和数据卷。

2026-11-14 验证结果：后端 53 项测试（18 默认 + 35 真实集成）通过；Ruff 与 Alembic check 通过；四服务重建后数据保持；前端 20 项测试及构建通过，25 个原型源码/配置/测试文件未改。详细证据见[开发记录](../../dev-notes/backend-foundation.md)。

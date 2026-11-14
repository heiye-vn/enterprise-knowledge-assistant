# 企业知识助理

独立的 Python + React 企业制度问答项目。当前已完成前端交互原型、FastAPI 基础工程、四项独立基础设施和 8 张核心表迁移。上传解析、真实检索问答和自动图谱抽取仍待接入。

## 启动后端与基础设施

需要 Docker Compose、uv 和 Python 3.12。从项目根目录执行：

```shell
uv sync --project backend --frozen
uv run --project backend python backend/scripts/init_env.py
docker compose up -d --wait
uv run --project backend alembic -c backend/alembic.ini upgrade head
uv run --directory backend python -m app.bootstrap
uv run --project backend uvicorn app.main:app --app-dir backend --host 127.0.0.1 --port 8014
```

初始化脚本创建独立随机凭证的 `.env`，保留已有配置。服务使用本项目的命名卷；普通 `docker compose down` 保留数据。配置含本机端口，容器内进程接入依赖时应使用 Compose 服务名。

后端文档：[http://127.0.0.1:8014/docs](http://127.0.0.1:8014/docs)；存活检查 `/api/health/live`，依赖及迁移检查 `/api/health/ready`。当前公开接口为健康检查；业务读模型和持久化校验已准备，业务 API 在下一阶段接入。

| 服务 | 本机地址 |
| --- | --- |
| PostgreSQL / pgvector | 127.0.0.1:5544 |
| Redis | 127.0.0.1:6384 |
| RustFS S3 / 控制台 | http://127.0.0.1:9014 / http://127.0.0.1:9015 |
| Neo4j 浏览器 / Bolt | http://127.0.0.1:7484 / bolt://127.0.0.1:7694 |

验证命令：

```shell
uv run --project backend pytest backend/tests -q
uv run --project backend pytest backend/tests -m integration -q
uv run --project backend alembic -c backend/alembic.ini check
uv run --project backend ruff check backend
```

默认测试不依赖服务；`integration` 明确使用真实服务，自动迁移独立的 `knowledge_assistant_test` 数据库。首次初始化测试库需要本项目数据库账号具有建库权限，本地 Compose 账号具备该权限。完整验证范围与持久化重建步骤见[后端基础记录](docs/dev-notes/backend-foundation.md)。

## 本地预览

使用 Node.js 22.21.0、pnpm 10；原型声明 pnpm 10.7.0，本阶段亦用 10.30.3 验证。从项目根目录执行：

```powershell
pnpm --dir frontend install --frozen-lockfile
pnpm --dir frontend dev
```

打开 http://127.0.0.1:5174/ 。预览仅监听本机；端口被占用时会明确退出。

构建验证：

```powershell
pnpm --dir frontend build
```

## 当前可体验内容

- 问答工作台、文档管理、知识图谱三个视图，左侧分别显示会话导航、文档分类与状态、图谱场景与节点筛选。
- 请假审批、电子发票、外部培训的固定示例回答，输入框、追问、新会话、历史会话搜索与切换、当前会话的问答范围选择和回答复制。
- 文档名称/分类搜索、动态分类与状态筛选、分页及每页条数调整。
- 引用编号与原文条款联动；真实 PDF 阅读、翻页，以及条款文本和示例片段切换。
- 上传文件选择、扩展名/非空/大小检查与处理阶段演示。文件不会上传服务器，不会建立真实索引。
- ECharts 力导向关系图、两组有条款来源的手工示例、节点类型筛选、搜索定位、局部展开与关系溯源；桌面三栏与窄屏抽屉布局。

页面明确标注交互原型和示例数据。问答不调用模型，不执行 RAG；图谱不是自动抽取结果；刷新恢复初始示例，不持久化会话或导入数据。

四份 PDF 副本在 `frontend/public/demo/`，来源为相邻的 ChatGPT 语料目录。当前版本均为 1.1，员工手册 5 页，其余各 4 页。页码、来源版本及文件 SHA-256 保存在 `frontend/src/demo-documents.json`。原始语料不在前端实现中修改。

## 设计与下一步

- [整体设计](docs/design.md)
- [数据库与接口数据设计](docs/superpowers/specs/2026-11-14-database-design.md)：8 张核心表、ER 图、约束与索引、任务恢复、范围快照和引用溯源。
- [设计用建表 SQL](docs/superpowers/specs/2026-11-14-database-schema.sql)：设计附件；实际数据库由 [Alembic 初始迁移](backend/migrations/versions/0001_core.py) 管理，后续变更添加新迁移。
- [实施计划](docs/implementation-plan.md)
- [前端原型记录](docs/dev-notes/frontend-prototype.md)
- [后端基础、真实服务验证与原型对照](docs/dev-notes/backend-foundation.md)

2026-11-14：本阶段四步已落地并验证；前端原型继续作为页面和交互基准，当前演示数据尚未替换为业务 API。下一阶段打通真实上传、解析、切片与索引，再接入问答、流式协议和图谱抽取。

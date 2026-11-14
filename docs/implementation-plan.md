# 企业知识助理 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking. 当前按单代理顺序执行；未得到明确授权不派发子代理。

**Goal:** 在周末两天内完成具有异步导入、可溯源 RAG、无依据拒答和短期追问的独立应用，并在核心验收后完成受控图谱和两个多跳示例。

**Architecture:** FastAPI 负责接口与 SSE，Celery + Redis 执行文档和图谱后台任务。PostgreSQL/pgvector 保存事实数据及向量，RustFS 通过 S3 API 保存原件与解析资源，Neo4j 保存可追溯的派生图谱。

**Tech Stack:** Python 3.12、uv、FastAPI、Pydantic、SQLAlchemy 2、psycopg 3、Alembic、PostgreSQL 16/pgvector、Celery/Redis、RustFS/boto3、MinerU 云端、阿里 Embedding/Rerank、Neo4j、React/TypeScript/Vite、AI SDK、Tailwind/shadcn、pytest/Vitest。

**Spec:** [design.md](./design.md)。所有路径相对于本项目根目录 `project/`。本计划按下方进度逐项执行；未勾选内容仍属待实现约定，不能据演示数据视为已完成。

## 当前进度（2026-11-14）

前端原型已完成用户评审，作为后续界面和交互基准。相关记录见 `docs/dev-notes/frontend-prototype.md`。已获授权进行数据库表设计，设计稿见[数据库与接口数据设计](superpowers/specs/2026-11-14-database-design.md)，按已确认的精简方案覆盖 8 张核心表、版本与索引代次、JSONB 范围快照、引用及任务恢复；配套[评审用 DDL](superpowers/specs/2026-11-14-database-schema.sql)。本阶段已完成 FastAPI 基础工程、四项独立基础设施、8 表 ORM/Alembic 初始迁移和约束验证；详见[四步执行清单](superpowers/plans/2026-11-14-backend-foundation.md)与[真实验证记录](dev-notes/backend-foundation.md)。后端 53 项测试通过，前端 20 项测试与构建通过，原型源码保持基准。固定示例尚未替换为业务接口，AI SDK 协议、上传处理链路、模型与端到端验收仍按未勾选项实现。

## Global Constraints

- Python 使用 3.12；Node.js 使用 22；pnpm 使用 10。
- 使用 uv.lock 与 pnpm-lock.yaml；服务镜像在实际拉取验证后固定标签，不使用 latest。
- PostgreSQL 是文档、切片、向量、任务和会话的事实来源；Neo4j 是可重建的派生数据。
- 文档正文与列表元数据分开存储，列表接口不加载全文。
- PostgreSQL 内容与向量写入使用同库事务；RustFS、Redis、Neo4j 不伪装成同一事务。
- API Key 仅从环境配置读取；配置示例不包含真实凭证，不从参考项目自动复制密钥。
- 每个业务实体 ID 在接口中使用字符串；同一切片 ID 用于检索、引用和图谱来源关联。
- 数据模型、接口和 UI Message Stream 协议在首个真实安装版本下验证后锁定。
- Celery Worker 和 Beat 在 Linux 容器运行，避免依赖 Windows 原生 Worker 的进程池兼容性。

## 文件边界

```text
project/
  compose.yaml                 # 四个基础设施、Worker、Beat 的明确启动定义
  .env.example                 # 服务与模型配置示例，无密钥
  README.md                    # 从空环境启动与验收
  backend/
    Dockerfile                   # Linux Worker/Beat 共用运行环境
    pyproject.toml, uv.lock, .python-version
    app/
      main.py, config.py       # 应用组装、环境校验
      contracts.py            # 跨模块数据契约
      db.py, models.py        # PG 连接和实体
      api/                    # documents、jobs、chat、sessions、graph、health 路由
      importing/              # MinerU 协议、归档读取、规范化、对象存储、任务服务
      retrieval/              # 切片、模型客户端、BM25/向量/RRF、来源与上下文
      chat/                   # 历史解析、证据判定、生成、流协议
      graph/                  # 定向抽取、Neo4j、路径检索
      tasks/                  # Celery、投递补偿、文档任务、图谱任务
    migrations/               # Alembic
    tests/                    # 按任务列出的单测与真实服务集成测试
  frontend/
    package.json, pnpm-lock.yaml, vite.config.ts
    src/
      App.tsx, api.ts, types.ts
      components/             # 文档列表、上传、消息、来源、图谱
      lib/                    # 消息与来源转换
  eval/
    dataset.jsonl, annotations.json, multihop.jsonl
    run.py, report.py, results/
  docs/
    design.md, implementation-plan.md, demo.md
```

命令均从项目根执行：后端用 `uv run --project backend ...`，前端用 `pnpm --dir frontend ...`。测试集成标记 `integration`，默认单测不调用云服务；真实服务检查必须明确执行，不把 mock 结果称为集成通过。

## Task 1：启动基础设施与验证流式协议

**Files:** 创建 `compose.yaml`、`.env.example`、`backend/Dockerfile`、`backend/pyproject.toml`、`backend/.python-version`、`backend/app/main.py`、`backend/app/config.py`、`backend/app/chat/protocol.py`、`frontend/package.json`、`frontend/src/App.tsx`、`frontend/src/api.ts`、`frontend/src/types.ts`、`backend/tests/test_stream_protocol.py`、`frontend/src/lib/stream.test.ts`。安装时生成真实锁文件。

**Interfaces:** 后端 `encode_event(event: dict) -> bytes` 编码所锁定 AI SDK 版本的事件；`GET /api/health/live` 返回进程状态。前端 `useChat` 连接 `POST /api/chat`；完成来源与文本的协议测试后由 Task 6 接入真实问答服务。

- [x] 检查新项目端口、Docker 服务和已有镜像；四个服务使用新网络与数据卷，固定实际可拉取标签及 digest。
- [ ] 为后续 Worker/Beat 建立 Python 3.12 Linux 镜像；区分本机端口与 Compose 服务名配置，不在 Windows 原生进程中使用 Celery prefork。
- [x] 通过 uv 使用 Python 3.12.14，安装并锁定后端依赖；FastAPI 健康检查与前端域 CORS 已验证。
- [ ] 在已完成的 React/TypeScript/Vite 原型上接入并锁定 AI SDK 包版本，替换演示流。
- [ ] 在测试夹具中先建立最小事件序列，验证文本、来源、完成与异常。示例契约测试：

```python
def test_stream_event_is_sse_frame():
    from app.chat.protocol import encode_event
    frame = encode_event({"type": "text-delta", "id": "t1", "delta": "你好"})
    assert frame.startswith(b"data: ")
    assert frame.endswith(b"\n\n")
```

- [ ] 先运行 `uv run --project backend pytest backend/tests/test_stream_protocol.py -q` 确认缺少实现时失败，再实现 `backend/app/chat/protocol.py`。
- [ ] 用前端当前版本的真实消息消费逻辑读取测试流，断言最终文本、来源 part、错误和取消行为；不能仅凭 HTTP 200 判协议通过。
- [x] 执行 Compose 启动 PostgreSQL、Redis、RustFS、Neo4j，四项均健康；实际验证 Redis 停止时 ready=503、恢复后 ready=200。
- [x] RustFS 1.0.5 单节点与独立命名卷，固定 digest；boto3 建桶、对象上传/读取/列表/删除、HEAD、Range 206 和重建容器后持久化均验证通过，未复用旧项目数据目录。
- [ ] 验证：后端协议测试、前端 stream 测试、`pnpm --dir frontend build`。只有这些通过后进入业务链路。

## Task 2：数据库契约与独立评测集

**Files:** 创建 `backend/app/{contracts,db,models}.py`、`backend/migrations/`、`backend/tests/test_database.py`、`backend/tests/test_eval_dataset.py`、`eval/{dataset.jsonl,annotations.json}`。

**Interfaces:** `ParsedBlock(block_id, type, text, heading_path, page_start, page_end, locators)`；`ParsedDocument(markdown, blocks, assets)`；`Chunk(chunk_id, job_id, version_id, document_id, ordinal, content, heading_path, page_start, page_end)`；`Evidence(source_id, chunk_id, job_id, version_id, document_id, title, content, heading_path, page_start, page_end)`；`QueryPlan(question, needs_clarification, clarification)`。字符串 ID，页码可为 null。SQLAlchemy 仓储由应用组装传入服务。表结构以 8 表设计及 DDL 为准：documents、document_versions、document_contents、chunks、processing_jobs、chat_sessions、chat_messages、message_citations。document_id 可在接口通过版本关联取得；内容块、定位、会话范围和请求快照定义 Pydantic schema，并验证 JSON 中的来源身份。

- [x] 真实 PG 验证事务回滚、版本归属、hash 去重、向量配置和页码、单活动任务/助手消息；补充 JSON 范围和引用的服务校验、摘要与跨事务状态测试；先验证缺表/缺实现失败，再完成实现。
- [ ] 在解析发布链路补齐 blocks/locators 的原文对应校验，和切片 ordinal 并发重试等完整业务用例；本阶段不替代后续 Worker 与模型链路验收。
- [x] 按确认的 8 表设计建立 ORM 和迁移，启用 pgvector；采用 vector 与维度/profile 约束，实际 Embedding 维度验证后再生成可选的定维表达式索引。首版不开放在线向量模型切换；维护窗口更换 profile 时创建新索引代次并统一切换，不原地覆盖历史切片，也不混排向量空间。
- [ ] 复制原始 JSONL 到项目 `eval/`；仅修正已核实的 FIN-004、HB-003、MX-003 标注，记录原值、新值、依据和原因；建立两组相似问法分组。
- [ ] 写评测完整性测试：

```python
def test_eval_cases_are_complete_and_separate():
    import json
    from pathlib import Path
    cases = [json.loads(x) for x in Path("eval/dataset.jsonl").read_text(encoding="utf-8").splitlines() if x]
    assert len(cases) == 40
    assert len({x["id"] for x in cases}) == 40
    assert sum(x["answerable"] == "不可直接回答" for x in cases) == 6
    assert all(x["question"] and x["gold_answer"] and x["source_clause"] for x in cases)
```

- [x] 实际执行初始迁移，alembic current=head、check 无差异；独立测试库验证回退/重建，PG 与会话/引用集成测试通过。
- [ ] 创建并执行 test_eval_dataset.py 验证独立评测集；评测数据校准仍未执行。

## Task 3：原件上传、Celery 队列与投递恢复

**Files:** 创建 `backend/app/api/{documents,jobs}.py`、`backend/app/importing/{storage,service}.py`、`backend/app/tasks/{celery_app,dispatch,documents}.py`、`backend/tests/conftest.py`、`backend/tests/{test_import_jobs,test_dispatch_recovery}.py`；使用 Task 2 的 processing_jobs 与版本表，不新增独立投递表。

**Interfaces:** `ImportService.create(document_id: str, filename: str, content: bytes, title: str, category: str) -> ImportAccepted`；`ImportService.add_version(document_id: str, filename: str, content: bytes) -> ImportAccepted`；`ImportAccepted(document_id: str, version_id: str, job_id: str)`。客户端新建时生成稳定 document_id 并在重试沿用；新建接口的相同 ID+不同文件返回 409，新版本只能走显式版本接口。同文档同 hash 复用版本，任务配置来自部署参数，普通重复上传复用相同配置的既有任务。`ImportService.get_job(job_id: str) -> ProcessingJobView` 返回 status/stage/next_dispatch_at/dispatch_attempts；`dispatch_pending() -> int`；Celery `process_document(job_id: str) -> None`。新任务返回 202，既有终态结果可返回 200；客户端重试不自动重启 failed/canceled 任务，使用受控 retry。

- [ ] 写相同 document_id/hash 重试不重复建文档、不同文档可保存相同字节、新版本并发去重、发送前崩溃和租约过期恢复的测试；重试次数上限不能被普通重复上传绕过。
- [ ] 实现文件签名与大小校验、boto3 向 RustFS 上传原件、PG 文档/版本/processing_jobs 原子创建，以及 /api/processing-jobs 状态和受控重试接口。对象先写新键，PG 失败留下的无引用对象按保留期清理。
- [ ] Celery 配置文档与图谱路由；Beat 扫描到期 queued 任务，先持久化 next_dispatch_at/dispatch_attempts 再发送 job_id，成功记录 last_dispatched_at。发送失败或崩溃后可再次补发；Worker 按状态、租约令牌和唯一约束认领，不能只凭 Redis 消息 ID 去重。
- [ ] 测试代理发送失败：

`conftest.py` 的 `broker` 夹具提供 `FakeBroker`：`fail_next_publish()` 使下一次 publish 抛出 ConnectionError，随后恢复。`import_service` 由该 broker、隔离 PG schema 的仓储和测试对象存储构造；下面的数据库恢复测试明确标记 integration，默认无外部依赖单测使用内存仓储测试相同业务分支。

```python
import pytest

@pytest.mark.integration
def test_publish_failure_preserves_recoverable_job(import_service, broker):
    broker.fail_next_publish()
    accepted = import_service.create(
        document_id="11111111-1111-4111-8111-111111111111",
        filename="制度.md", content="# 制度\n正文".encode(),
        title="制度", category="未分类",
    )
    job = import_service.get_job(accepted.job_id)
    assert job.status == "queued"
    assert job.next_dispatch_at is not None
    assert job.dispatch_attempts == 1
```

- [ ] 先运行测试确认失败，再实现事务和补发；最终运行对应两组测试。
- [ ] 真实 Redis/PG/RustFS 集成验收：停止文档 Worker 后上传，恢复 Worker 后任务继续；同一稳定 document_id 重试无重复数据。该检查仅操作新项目服务。

## Task 4：MinerU 云端与统一内容块

**Files:** 创建 `backend/app/importing/{mineru,archive,normalize}.py`、`backend/tests/{test_mineru,test_normalize,test_mineru_integration}.py`，扩展 `tasks/documents.py`。

**Interfaces:** `MineruClient.submit(content: bytes, filename: str) -> str` 返回远端任务 ID；`poll(remote_id: str) -> ParseProgress`；`fetch_result(remote_id: str) -> ParsedDocument`。`normalize_markdown(text: str) -> ParsedDocument` 处理 MD。`ParseProgress(state, retryable, error, result_location)` 在 contracts.py 定义。

- [ ] 写远端任务检查点恢复、轮询截止时间、提交结果不确定、归档路径安全与大小限制、缺少页码不造假及真实页码基准转换的测试。
- [ ] 建立 MD 直接读取测试：

```python
def test_markdown_keeps_heading_without_invented_pages():
    from app.importing.normalize import normalize_markdown
    doc = normalize_markdown("# 费用制度\n\n## 发票\n提交原始文件。")
    assert doc.blocks[-1].heading_path == ["费用制度", "发票"]
    assert doc.blocks[-1].page_start is None
```

- [ ] 先运行上述测试确认失败，再实现 HTTP 协议、检查点、解析归档与规范化。只下载必要归档，资源 URL 与解包路径经过校验。
- [ ] 配置用户提供的 MinerU 凭证后，分别上传一份 PDF 和 DOCX；保存实际响应结构并作为脱敏协议夹具。核对正文、表格、图片和定位信息。
- [ ] 验证 `uv run --project backend pytest backend/tests/test_mineru.py backend/tests/test_normalize.py -q`；再明确执行 `test_mineru_integration.py -m integration`。没有凭证时记录集成未运行。

## Task 5：切片、Embedding、混合检索与 Rerank

**Files:** 创建 `backend/app/retrieval/{chunking,models,search,sources}.py`、`backend/tests/{test_chunking,test_search,test_retrieval_integration}.py`，完成 `tasks/documents.py` 的 ready 流程。

**Interfaces:** `chunk_document(job_id: str, version_id: str, document_id: str, parsed: ParsedDocument) -> list[Chunk]`；`embed_texts(texts: list[str]) -> list[list[float]]`；`rrf(rankings: list[list[str]], k: int = 60) -> list[str]`；`SearchService.retrieve(question: str, snapshot: RequestSnapshot, top_k: int) -> list[Evidence]`；`rerank(question: str, candidates: list[Evidence]) -> list[Evidence]`。

- [ ] 写表格不丢表头、跨页条款保留页码范围、来源 ID 稳定、向量维度不一致拒绝入库、重试不重复切片的测试。
- [ ] 将 fixtures 中的真实审批表抽为测试输入；验证金额、岗位、适用条件同时保留。先确认测试因缺少实现失败，再完成分块。
- [ ] 正文/切片按 job 隔离存储，blocks/locators 发布前校验；按 document → version → job 的顺序锁定关联行，验证当前租约后事务写 ready 与发布指针。按 version_no/generation_no 比较，新版失败保留旧结果，迟到旧任务不能倒退指针。BM25 按已固定的 ready job 清单构建/失效。
- [ ] RRF 去重按 chunk_id；测试同一切片被双路召回只出现一次且排名正确。Embedding 与 Rerank 分别调用阿里接口，不共用聊天端点假设。
- [ ] 通过真实模型请求验证模型名、返回维度和 Rerank 索引映射；超时或限流时明确记录降级，不能把故障伪装为没有文档。
- [ ] 运行切片与检索测试；用报销、请假、采购各一个问题人工核对 Top-K 与来源原文，再进入回答生成。

## Task 6：带短期上下文的有据问答

**Files:** 创建 `backend/app/chat/{history,evidence,service}.py`、`backend/app/api/{chat,sessions}.py`、`backend/tests/{test_history,test_chat,test_citations}.py`，接入 Task 1 的 `chat/protocol.py`。

**Interfaces:** `resolve_query(messages: list[dict], question: str) -> QueryPlan`；`assess_evidence(question: str, sources: list[Evidence]) -> EvidenceDecision`；`EvidenceDecision(answerable: bool, partial: bool, missing: list[str])`；`ChatService.stream(session_id: str, client_request_id: str, scope_revision: int, text: str) -> AsyncIterator[dict]`；`validate_citations(text: str, sources: list[Evidence]) -> list[Evidence]`。聊天供应商适配放 `retrieval/models.py`，输出统一文本事件。

- [ ] 写无依据时不调用生成、部分有据明确范围、服务错误与拒答区分的测试。
- [ ] 写引用测试，缺失引用不得回退全部来源：

```python
def test_uncited_answer_does_not_claim_all_sources():
    from app.contracts import Evidence
    from app.retrieval.sources import validate_citations
    source = Evidence(
        source_id="1", chunk_id="c1", job_id="j1", version_id="v1",
        document_id="d1", title="费用制度",
        content="电子发票提交原始文件。", heading_path=["发票"],
        page_start=1, page_end=1,
    )
    assert validate_citations("未标明引用的回答", [source]) == []
```

- [ ] 使用可控的模型客户端夹具验证“半天事假 -> 那四天呢”传给检索器的是补全问题，不能只验证最终回答出现“四天”。不同 session 不共用历史。
- [ ] 历史从服务端按 session 读取；客户端只提交本轮 text、client_request_id 与 scope_revision。锁定会话后复查幂等键，原子创建 user/assistant，保存服务生成的 request_snapshot；再实现 token 预算、问题改写/澄清、证据判断与带引用生成。
- [ ] 最终引用校验 message 角色、chunk 的 job 在本轮快照中、原文引句与编号，正文/引用/completed 同事务提交；失败明确报告。实现同会话单活动回答、同键不同请求 409、停止与完成竞争、过期生成请求标为 failed；不自动重新收费生成。上下文保留完整条款和表格。
- [ ] 运行三组单测与 Task 1 协议测试；用真实聊天模型验证正常回答、完全拒答、部分回答和一次追问。用户未选模型时保留明确配置错误，不冒充真实验证完成。

## Task 7：工作台、文档阅读与引用交互

**Files:** 创建 `frontend/src/components/{DocumentList,UploadPanel,ChatPanel,SourcePanel,DocumentReader}.tsx`、`frontend/src/lib/messages.ts`、对应 `*.test.tsx/ts`、`eval/run.py`、`eval/report.py`、`backend/tests/test_eval_report.py`，补齐 `App.tsx`、`api.ts` 与全局样式。

**Interfaces:** 前端 Evidence 与后端 contracts.py 对齐；`SourcePanel` 接收被点击的 source_id；PDF 页码使用 page_start，缺失时按章节/内容块展示。`ChatPanel` 使用 useChat 和 session_id，来源从结构化 part 映射，不根据模型生成的标题或 URL 查找文件。

- [ ] 写消息/来源转换测试：忽略越界引用、点击有效引用对应正确 chunk_id；流式终止和服务错误分别显示。
- [ ] 实现三栏工作台，窄屏用来源抽屉；上传显示排队、处理阶段、失败原因及受控重试；解析正文和切片可预览。
- [ ] PDF 原件按固定 version_id 从后端流式读取，Markdown/模型输出渲染保持安全转义；解析图片通过应用资源接口展示。
- [ ] 用组件测试与浏览器完整走通：上传 -> ready -> 提问 -> 流式回答 -> 点击引用 -> 跳页/章节；刷新恢复会话；新会话不继承旧问题。
- [ ] 实现最小评测 runner 和逐题报告，先验证 40 条输入均有结果、超时计入失败，再运行核心题集。Task 9 扩展图谱对比和交付报告。
- [ ] 运行 `pnpm --dir frontend test` 与 `pnpm --dir frontend build`。此时先完成核心 40 题回归；核心失败优先修复，再进入 Task 8。

## Task 8：定向图谱与两个多跳证据示例

**Files:** 创建 `backend/app/graph/{extract,store,retrieve}.py`、`backend/app/tasks/graph.py`、`backend/app/api/graph.py`、`backend/tests/{test_graph_extract,test_graph_paths}.py`、`frontend/src/components/GraphPanel.tsx`、`eval/multihop.jsonl`。

**Interfaces:** `extract_graph(chunks: list[Chunk]) -> GraphExtraction`；`GraphExtraction(nodes, edges)` 在 contracts.py 定义固定类型与关系枚举；每条 edge 包含 source_chunk_ids、evidence_quote、conditions。`GraphStore.upsert(graph_job_id: str, source_job_id: str, lease_token: int, extraction: GraphExtraction) -> None`；`GraphRetriever.expand(question: str, snapshot: RequestSnapshot, seeds: list[Evidence], max_hops: int = 3) -> list[Evidence]`。不接受任意用户 Cypher。

- [ ] 写“超出切片的引文拒收”“条件不能丢失”“重复任务不增加同一关系”的测试。
- [ ] 先建立两条人工标注的真实原文路径夹具，再实现模型定向抽取；不能把预期答案或手写图当作实际模型抽取结果。
- [ ] 导入发布事务创建 processing_jobs 的 graph 行，source_job_id 指向同版本 ready import；共享任务状态与投递恢复机制，使用独立图谱队列。checkpoint 保存校验结果/manifest/hash，Neo4j 按 graph_job_id 幂等投影并用令牌拒绝过期 Worker，失败重放原结果。
- [ ] 实现受控路径检索和 PG 来源回查，加入基础候选后统一精排；金额/时长条件由程序判断，无条件节点不能代替有条件规则。
- [ ] 延用 ECharts 局部图与展开/收起，节点上限 80，返回 sources/fingerprint/has_more；范围版本变化要求刷新。显示适用条件，点击边打开固定版本原文；加入 MX-002 及“外部培训电子发票”两道多跳验证题。
- [ ] 执行图谱测试及真实 Neo4j 集成检查；分别在图谱可用和图谱故障时验证基本问答行为。

## Task 9：评测、交付与面试演示

**Files:** 扩展 `eval/run.py`、`eval/report.py`、`backend/tests/test_eval_report.py`，创建 `docs/demo.md`，完成根 `README.md` 和 `.env.example`。

**Interfaces:** `uv run --project backend python eval/run.py --dataset eval/dataset.jsonl --output eval/results/baseline.jsonl` 逐题调用实际 API；`uv run --project backend python eval/report.py --input eval/results/baseline.jsonl` 输出完整题数、失败项、引用/关键事实/拒答与耗时。模型语义判定作为辅助，保留原始输出供人工核对。

- [ ] 写报告完整性测试：40 条输入必须有 40 条结果，超时与服务错误计入失败，不能当作拒答通过；已知相似题分组保留在报告中。
- [ ] 运行 40 题并逐项核对来源和关键事实，特别检查 6 道不可直接回答题；记录真实问题，不为提高成绩修改正确原文。
- [ ] 对多跳题以相同模型和预算运行基础检索及图谱扩展两组，报告证据召回、答案、引用、耗时、调用量；没有改善也如实记录。
- [ ] 根目录运行后端默认单测、前端测试与构建、迁移检查；真实服务测试单列结果。未运行、被跳过和未通过分别记录。
- [ ] 编写空环境启动顺序、配置说明、Worker/Beat 启动和失败恢复步骤；再次从启动到演示完整执行一遍。
- [ ] 演示脚本覆盖：上传/处理状态、自然语言问答、来源定位、连续追问、无依据拒答、两个多跳来源路径。

## 自查与交接

- [ ] 设计稿的必须能力均对应到 Task 1～7、9；图谱与多跳对应 Task 8。
- [ ] 不同任务的 contracts.py 类型、函数签名、状态名与接口路径一致。
- [ ] 没有把未验证的 SDK 方法、云服务输出或镜像标签写成已验证事实。
- [ ] 没有引入原项目账号/鉴权、长期记忆或联网功能。
- [ ] 文件只写入新项目，原始制度和评测来源保持可回溯。
- [ ] 实际开发中每个任务完成即更新复选框、验证结果与必要的开发记录；Git 仓库和提交操作在明确进入实现时按用户约定处理。

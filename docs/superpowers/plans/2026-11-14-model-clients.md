# 模型配置与双提供方客户端

> 沿用用户已确认的模型分工，单代理在当前工作区执行；应用 writing-plans、executing-plans 与 TDD。保留已有修改。

**Goal:** 识别用户的 QWEN_/MONKEY_ 环境配置，使用千问向量/重排，回答模型可明确切换千问或三方；完成协议和真实连通验收。

**Architecture:** Settings 提供兼容变量别名；独立 ModelClient 负责向量、重排和聊天请求。提供方与协议按配置选择，不在请求失败后跨提供方自动重发。原件解析流程保持当前阶段边界，检索和带证据问答将在后续阶段调用这些客户端。

**Spec:** docs/design.md 的模型选择与 docs/implementation-plan.md Task 5/6 的模型接口部分。

### 1. 配置

- [x] 先测试用户变量名、KH_ 优先级、密钥 SecretStr 和构造参数兼容，确认失败。
- [x] 扩展 backend/app/config.py；保留 QWEN_EMBEDDING_MODEL 对 embedding_model 的别名及既有 KH_EMBEDDING_MODEL。
- [x] 默认 KH_LLM_PROVIDER=qwen，通过 monkey 显式切换；两种提供方已实测支持 Chat Completions；精确模型名不替换。
- [x] 修正私有 .env 的 MKNKEY_BASE_URL 拼写，保留值，示例配置只含空 Key。

### 2. 模型协议

- [x] 新增 backend/tests/test_model_clients.py，测试不同提供方 URL/密钥隔离、无自动重发、1024 维与输入索引校验、Rerank 索引/分数校验、聊天与 SSE 结束/错误。
- [x] 实现 backend/app/model_clients.py。千问使用原生 Embedding/Rerank 参数；聊天使用已实测支持的 Chat Completions 协议。
- [x] HTTP 超时、401/403、429、5xx、模型不可用和响应格式异常给出脱敏错误；不输出 headers、Key、完整 URL、输入或远端错误原文。
- [x] 运行协议测试与配置测试。

### 3. 真实连通与交付

- [x] 新增 backend/scripts/check_models.py，可显式检查 qwen/monkey/all；只发送固定测试文本，不上传用户文档。
- [x] 用真实配置确认两条 1024 维向量、相关文档的重排索引、两种回答模型及其流式调用；记录模型返回身份和耗用，不记录密钥。
- [x] 更新 README、.env.example、模型接入记录与总计划，明确当前可切换的是后端模型配置，问答 UI 尚待检索链路接入。
- [x] 完整后端测试、Ruff、迁移检查与已有前端测试/构建；重建运行 Worker/Beat、重启 API，并确认健康状态。

实测补充：当前百炼网关返回 text_index，已增加回归测试，兼容 index 并拒绝冲突。普通与流式回答两种提供方均通过；向量/查询语义检查在 Worker 内通过。本机存在间歇性 ConnectError，未自动重发。后端完整 137 项测试通过；仅完成模型边界，不将模型可调用称为文档已可问答。

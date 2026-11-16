# 模型网络配置与失败恢复

千问、MinerU、第三方回答、联网搜索和追踪可以分别选择网络路径。宿主机与容器的连通性需要分别检查，不能以一次宿主机调用代替 Worker 验证。

## 配置与诊断

- `KH_MODEL_TRUST_ENV=false`：默认直接连接，应用于千问的向量、重排、意图判断、回答以及 MinerU API 和归档下载。
- `KH_MONKEY_MODEL_TRUST_ENV=true`：第三方回答继承系统/环境代理；省略该项时沿用上一项。容器不会读取宿主机的 macOS 系统代理，如果需要容器调用三方服务，必须另外配置容器可访问的代理地址。
- 保持 TLS 校验开启，不自动改提供方或切换模型，不自动重发生成请求。
- 每次请求记录提供方、`operation`、连接模式、耗时、HTTP 状态和失败类别。聊天区分 `intent` / `answer`，同时覆盖 embedding、rerank、chat 和 chat_stream。
- 网络失败类别包括代理、DNS、TLS、连接/读取/发送超时、连接池及协议中断；限流、认证和服务端错误保留独立业务错误码。日志不包含 Key、原始错误文本、提示词、文档内容或代理凭证。
- 成功诊断使用 INFO，失败使用 WARNING；前端只显示简洁原因。

更改配置后重启 API；后台任务代码变更时执行 `docker compose build worker` 和 `docker compose up -d --no-deps worker beat`。仅修改环境配置时执行 `docker compose up -d --no-deps --force-recreate worker beat`；单独 restart 不会重新读取 Compose 的 env_file。

## 手动重试

失败回答在最后一条消息处提供“重试回答”，仅允许可恢复错误，总共最多 3 次尝试。重试沿用原 user/assistant 消息、请求 ID，并显式增加 `retry_attempt`；同一尝试重复提交或并发提交不会重复生成。旧问题在新消息出现后不能重试，以免修改后续上下文。

`POST /api/chat` 保留原请求格式，主动重试额外提交 `retry_attempt=2|3`。不带该字段重放失败请求不会重新调用模型；成功请求重放仍返回已保存结果。消息接口增加 `client_request_id`、`attempt_no`、`max_attempts` 和错误 `retryable`。

结果写入检查消息状态、当前尝试号和有效期，过期旧请求不能覆盖新尝试。无需数据库迁移。网络响应丢失后页面读取已保存消息并继续轮询，受控重试不重复添加用户问题。

## 排查顺序

1. 检查对应提供方、模型名称、区域、Key 和额度；用 [模型检查脚本](../../backend/scripts/check_models.py) 区分向量、重排和回答调用。
2. 核对 `KH_MODEL_TRUST_ENV` 和 `KH_MONKEY_MODEL_TRUST_ENV`。后者未设置时继承前者，不要假设第三方与千问需要相同网络路径。
3. 联网搜索和追踪分别使用 `KH_TAVILY_TRUST_ENV`、`KH_LANGSMITH_TRUST_ENV`，默认均为 true；它们独立于模型网络配置。
4. 上传停在解析或向量阶段时查看 `docker compose logs --tail=50 worker beat`。容器内的 `127.0.0.1` 指向容器自身，需要宿主机代理时使用实际可访问的地址；不要照搬其他电脑的代理端口。
5. 外部请求恢复后使用页面的有界重试。MinerU 已有远端 batch 或下载检查点时复用该任务，不通过重复上传绕过限制；详见 [入库恢复规则](../design.md#5-文档导入与任务恢复)。

不要关闭 TLS 校验或把服务故障解释成“知识库没有依据”。此前环境的直连/代理验收不能保证当前电脑和容器的网络持续可用。

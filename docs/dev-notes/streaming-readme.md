# 流式回答与停止生成

前端使用原生 fetch 读取 POST SSE，后端转发真实模型文本增量；未接入 Vercel AI SDK。本文说明事件协议、草稿持久化、停止与断线恢复。

## 生成与引用

- 浏览器使用 `fetch` 读取 `POST /api/chat/stream` 的 SSE，通用回答和有据回答均来自真实上游模型流。
- 意图调用只做分类、检索问题改写或澄清；通用回答再独立流式生成。检索没有依据时直接返回拒答，不制造文本增量。
- 知识回答仍沿用结构化 JSON 契约，只增量提取顶层 `answer` 字符串。处理跨包中文、引号、转义、Unicode 和代理对，不把 JSON、引用元数据或隐藏内容发到正文。
- 草稿在短事务中分批写入 PostgreSQL 后再发送；默认约 80 ms / 64 字符批次，首批立即发送。
- 引用只在完整 JSON、正文一致性、引用编号与原文来源校验通过后发布。停止或失败的草稿没有有效引用，也没有完成答案类型。

## 接口与持久化

`POST /api/chat/stream` 请求沿用 `session_id / client_request_id / text`，重新生成增加 `retry_attempt`。事件如下：

| 事件 | 数据 | 含义 |
| --- | --- | --- |
| `start` | `{user, assistant}` | 已持久化的规范消息身份 |
| `phase` | `{phase, mode}` | intent / retrieval / generating / validating |
| `delta` | `{text}` | 已保存的正文增量 |
| `done` | `{user, assistant}` | completed / stopped / failed 的规范终态 |
| `error` | `{message}` | 无法确认保存或协议状态，客户端读取会话恢复 |

静默阶段发送 SSE 注释心跳。浏览器解析器支持网络块任意拆分、CRLF 和中文 UTF-8 边界；缺少终态不会当作成功。旧 JSON `/api/chat` 仍可调用。

`POST /api/chat/stop` 使用同一消息身份、原问题和 `attempt_no`。停止早于流请求到达时，先保存 stopped 消息，稍后同请求只重放终态。尝试编号隔离旧生成、旧停止与新生成；同一条消息最多三次尝试，重新生成不新增用户问题。

消息状态复用现有字段 `stopped / stop_requested_at / lease_expires_at`，无需迁移。刷新从历史读取保留的草稿；失效租约恢复为可重试失败，不自动重复模型请求。断开 SSE、切换页面或关闭连接会触发服务端受保护的停止清理。

每个 API 进程限制 4 个后台生成者，事件队列上限 64。取消正在接收的上游流时，使用 HTTPX 的 network_stream 扩展关闭连接：先 socket shutdown，再关闭响应。仅调用 response.close 曾使 TLS 读取等到 60 秒超时，多次停止会占住并发名额；对应的本地 TLS 回归测试要求取消后一秒内退出读取。测试证书仅用于 localhost 测试，客户端显式信任该证书，未关闭 TLS 校验。

意图和检索阶段已发出的非流式网络请求仍可能到超时才返回；消息会立即停止，后续阶段和旧结果不能再发布。上游服务的实际计费停止时间由提供方决定。

## 草稿展示与验证

流式、停止及失败草稿使用安全 Markdown 排版，未完成内容禁用链接和有效来源按钮。刷新从数据库恢复草稿，不能将恢复操作变成自动重复调用模型。

相关回归：`backend/tests/test_chat_streaming.py`、`test_answer_stream.py`、前端 `chat-stream.test.ts` 与 `chat-message.test.tsx`。运行命令见 [README](../../README.md#验证与开发)，真实问答结果见 [验收报告](../../eval/README.md)，录制流程见 [演示脚本](../deliver/企业知识助理系统演示脚本.md)。

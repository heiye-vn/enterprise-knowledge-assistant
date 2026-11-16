# 模型配置与双提供方接入

Embedding 和 Rerank 使用千问，回答模型可通过配置选择千问或第三方 OpenAI 兼容接口。网络与失败恢复见 [模型网络说明](model-network.md)。

## 配置

保留用户提供的变量名，所有 Key 以 SecretStr 读取，不进入文档任务 config/profile、HTTP 返回或检查报告：

| 配置 | 用途 |
| --- | --- |
| QWEN_LLM_MODEL | 千问回答，当前 qwen3.8-max-0902 |
| QWEN_EMBEDDING_MODEL / QWEN_EMBEDDING_DIMENSION | 向量模型，qwen3.7-text-embedding-flash / 1024 |
| QWEN_RERANK_MODEL | 重排，qwen3.7-text-rerank |
| QWEN_BASE_URL / QWEN_API_KEY | 百炼兼容 Base URL 和私有 Key |
| MONKEY_LLM_MODEL / MONKEY_BASE_URL / MONKEY_API_KEY | 三方回答模型、兼容服务和单独的 Key |
| KH_LLM_PROVIDER | qwen（默认）或 monkey |

既有 KH_EMBEDDING_MODEL/KH_EMBEDDING_DIMENSION 优先于同用途 QWEN_ 别名；QWEN_/MONKEY_ 字段也支持 KH_QWEN_ / KH_MONKEY_ 写法。

在私有 `.env` 中设置 `KH_LLM_PROVIDER=monkey` 后重启 API，并重新创建 Worker/Beat 容器，即可切换后端默认回答模型。Embedding/Rerank 始终使用 QWEN_ 配置。不会在失败后自动切换提供方或重发生成请求；显式选择避免意外重复调用。

当前使用的百炼 dashscope.aliyuncs.com/compatible-mode/v1 已真实验证可用。官方推荐新项目使用业务空间专属 API Host，后续可按控制台提供的 Host 修改 QWEN_BASE_URL，无需改业务逻辑。

## 接口与数据校验

实现为 `backend/app/model_clients.py`：

- `embed_texts(texts, text_type="document"|"query") -> EmbeddingBatch`，原生 text-embedding API；单次 1～20 条，指定维度，恢复输入顺序。当前网关返回 text_index，兼容 index，但两者冲突时拒收；校验数量、唯一序号、维度、有限值、float32 范围和非零向量。
- `rerank(query, documents, top_n=8) -> Ranking`，原生 text-rerank API；校验数量、唯一输入序号与 0～1 分数，再排序；不会按服务端生成的文字重新匹配文档。
- `complete(messages, provider=None, max_tokens=2048) -> ChatReply`，显式提供方覆盖或默认配置；只转发角色和正文。千问使用非思考模式以便当前文本历史协议接入；三方不发送千问特有参数。
- `stream(...)`，Chat Completions SSE；只产生可见正文，不转发 reasoning_content。要求 finish_reason=stop 和 [DONE]；截断、错误和连接中断不会被当作完整回答。

Base URL 限定 HTTPS，不含用户信息、查询参数或片段。请求分别携带对应提供方 Key，不在共享 HTTP 客户端设置全局认证头，不跟随重定向。连接错误、认证失败、限流、服务端故障、请求拒绝、响应校验失败、输出截断和流中断均为可区分的 ModelProblem；错误不包含上游原始内容或 Key。

## 连通检查

从仓库根目录执行；会产生真实模型调用，不由健康检查或默认单测自动触发：

```sh
uv run --project backend python backend/scripts/check_models.py --provider all --stream
uv run --project backend python backend/scripts/check_models.py --provider qwen --operation embedding
uv run --project backend python backend/scripts/check_models.py --provider monkey --operation chat --stream
```

报告仅包含模型名、检查结果、向量维度、重排序号、用量与脱敏错误，可用 `--output .local/model-checks/latest.json` 保存。单次成功不代表网络长期可用。

参考：[百炼 Embedding](https://help.aliyun.com/zh/model-studio/text-embedding-synchronous-api)、[百炼重排](https://help.aliyun.com/zh/model-studio/rerank)、[百炼聊天](https://help.aliyun.com/zh/model-studio/qwen-api-via-openai-chat-completions)。

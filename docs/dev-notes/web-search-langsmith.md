# Tavily 联网查询与 LangSmith 链路追踪

联网使用 Tavily 直接 API，链路追踪使用 LangSmith REST API；两者可选，不要求引入 LangChain 或 MCP。配置示例见根 [README](../../README.md#2-配置模型)。

## 联网查询

输入区增加默认关闭的“联网查询”开关。每次发送冻结本轮选择，停止、重新生成与幂等重放沿用该值；不能复用同一请求标识改变联网选择。新会话恢复默认关闭。

意图判断先执行：公共 general 问题且显式开启联网，才进入 web 路径；knowledge / clarify 沿用已有流程。企业内部制度问题即使开启联网，仍检索知识库并在缺少依据时拒答，不使用网页填补内部事实。

Tavily Search 使用一次 basic 请求，最多五条、默认二十秒超时，不开启原始全文、图片或 Tavily 生成答案。只发送分类调用生成的独立公共搜索问题，不传完整历史或知识库原文。结果去重、限制长度，过滤危险协议、带凭证及本机地址；正文只引用已返回且校验通过的网页编号。

网页摘要作为不可信数据交给当前选定回答模型进行真实流式生成，默认中文。沿用顶层 answer 增量解码；完整结构、正文一致性和引用编号通过校验后才发布网页链接。网页来源与知识库引用分别存储和展示，不写入 document chunk 引用表，无新增迁移。

空结果返回明确无公开依据；认证、额度、超时和无效返回保留失败及重试状态，不自动换服务或伪装成搜索成功。搜索和模型阶段都可停止，未完成草稿不发布有效引用。

界面在问答过程中显示实际查询、Tavily 状态、结果数、查询时间、使用的网页及阶段耗时；生成时显示“正在查询公开网页”。网页点击使用新窗口及安全链接属性，默认不自动加载网站资源。

## LangSmith

现有配置现已实际接入：LANGSMITH_TRACING / API_KEY / PROJECT / ENDPOINT。通过官方 REST runs 接口发送，不依赖 LangChain 或新增 SDK。

每次聊天尝试一个 chat 根链路，子节点包括 intent、实际意图模型调用、knowledge.retrieve、Embedding / Rerank 等模型请求、tavily.search、answer 和实际流式调用。仅执行过的阶段进入 trace；没有查询网页的分支不会伪造工具节点。

默认上传严格白名单元数据：请求/会话身份、尝试编号、路径、模型与提供方、耗时、Token 数、数量、停止/错误状态。默认模式 inputs 为空，outputs 仅含状态与 usage_metadata。KH_LANGSMITH_RECORD_CONTENT：开启时记录根问题/答案、意图结果、检索候选与分数、当前来源片段、模型 messages/choices 及 Tavily query/results；配置密钥和常见凭证字段统一脱敏。单次 record 上限 120,000 字符，整个 trace 的正文预算 500,000 字符。公开示例默认关闭；展示正文前需在自己的环境显式开启。Token 数据来自真实模型 usage，不根据文本长度估计。LangSmith 也可能聚合父节点的 Token，统计时避免再次累加父子值。

一个后台导出线程和有界队列负责发送；追踪关闭或未配 Key 时不发送请求，导出失败只记录脱敏错误，不改变业务结果。Trace ID 随问答详情保存，便于到自己的项目核对。平台接收与查询存在延迟，首次读取可能返回 404，稍后才能查询到，不把队列接收等同于平台已可见。

KH_TAVILY_TRUST_ENV 与 KH_LANGSMITH_TRUST_ENV 默认 true，分别控制搜索和追踪是否继承环境代理。它们与模型网络配置独立，按当前电脑和容器网络调整，保持 TLS 校验开启。详见 [网络与恢复](model-network.md)。

## 验证与边界

集成测试关闭真实 LangSmith 导出，避免模拟链路进入实际项目。相关回归包括 `backend/tests/test_web_search.py`、`test_observability.py` 和前端 `chat-message.test.tsx`。真实联网案例、来源与问题报告见 [问答验收](../../eval/README.md)。

采用直接 Tavily API，不将其称作 MCP 接入。LangSmith 已存在的元数据 trace 不会因后来开启正文记录而自动补全，应对照新请求的 Trace ID 查看。

参考：[Tavily Search](https://docs.tavily.com/documentation/api-reference/endpoint/search)、[LangSmith REST 追踪](https://docs.langchain.com/langsmith/trace-with-api)。

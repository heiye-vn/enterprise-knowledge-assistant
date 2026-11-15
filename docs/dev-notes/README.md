# 开发记录

| 模块 | 范围 | 记录 |
| --- | --- | --- |
| 前端交互原型 | 布局、演示交互、真实 PDF 阅读与溯源 | [frontend-prototype.md](frontend-prototype.md) |
| 后端基础与数据库 | FastAPI、独立基础设施、8 表迁移、真实约束测试及原型字段对照 | [backend-foundation.md](backend-foundation.md) |
| 全库文件指纹 | 有效库历史版本查重、并发保护边界、上传重复反馈 | [global-file-fingerprint.md](global-file-fingerprint.md) |
| 真实文档导入 | 上传/版本/原件、Celery 恢复、前端真实列表和种子移除 | [document-import.md](document-import.md) |
| 真实文档解析 | MinerU PDF/DOCX、Markdown、检查点、资源、重新解析与正文预览 | [document-parsing.md](document-parsing.md) |
| 模型客户端 | 千问向量/重排、千问或三方回答、配置切换与真实连通验证 | [model-clients.md](model-clients.md) |
| 本地登录配置 | 简化凭证、同步现有数据库和容器、连通验证 | [local-development-logins.md](local-development-logins.md) |
| 索引与原文检索 | 可回溯切片、分批向量、索引发布、BM25/向量/RRF/重排、固定来源预览 | [indexing-retrieval.md](indexing-retrieval.md) |
| Demo 闭环 | 范围收敛、精简页面、空库对话、真实回答/引用/拒答与会话恢复 | [demo-chat.md](demo-chat.md) |
| 模型网络与重试 | 直接连接/代理分开配置、脱敏诊断、原消息手动重试与真实验收 | [model-network.md](model-network.md) |
| 电脑端界面优化 | 顶部通知、安全 Markdown、答案排版、原文面板与桌面验收 | [frontend-layout.md](frontend-layout.md) |
| 意图与检索详情 | 三类路由、澄清、真实分数/排名、快照、引用与降级验收 | [intent-retrieval-details.md](intent-retrieval-details.md) |
| 图谱小样验证 | 两份制度抽取、条件/语义核对、Neo4j 幂等和来源路径、MinerU 网络修复 | [knowledge-graph-spike.md](knowledge-graph-spike.md) |
| 正式知识图谱 | 异步任务、Neo4j 投影、真实图谱页面、条件及原文定位、四份制度验收 | [knowledge-graph.md](knowledge-graph.md) |
| 两跳证据与图片制度 | 图谱辅助检索、路径/条件/引用、Word 原件预览及 PNG/JPEG OCR 闭环 | [multihop-image-preview.md](multihop-image-preview.md) |
| 流式与项目说明 | 真实 SSE、停止/断线草稿、TLS 取消回归、README 与系统截图 | [streaming-readme.md](streaming-readme.md) |
| 联网与链路追踪 | Tavily 公共搜索、网页引用、LangSmith 父子链路/Token 与脱敏验收 | [web-search-langsmith.md](web-search-langsmith.md) |
| 交付收尾 | 文档删除、历史来源、桌面微调、20 题真实验收与演示脚本 | [delivery-wrapup.md](delivery-wrapup.md) |

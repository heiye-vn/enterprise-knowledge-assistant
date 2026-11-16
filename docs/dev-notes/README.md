# 开发文档

本文档索引按当前实现组织，启动与检查命令统一放在根 [README](../../README.md)。架构及入库恢复见 [整体设计](../design.md)，数据库结构见 [8 表设计](../superpowers/specs/2026-11-14-database-design.md)，真实答案与逐题结果见 [问答验收](../../eval/README.md)。

| 文档 | 内容 |
| --- | --- |
| [模型配置](model-clients.md) | 千问向量/重排、回答提供方切换、协议校验与连通检查 |
| [网络与失败恢复](model-network.md) | 模型/MinerU/搜索/追踪网络选项、容器代理与有界重试 |
| [索引与原文检索](indexing-retrieval.md) | 切块参数、向量空间、索引发布、BM25/向量/RRF/重排 |
| [意图与检索详情](intent-retrieval-details.md) | 三类路由、澄清、真实分数、候选/引用区别及记录恢复 |
| [知识图谱](knowledge-graph.md) | 按需抽取、Neo4j 投影、来源校验、条件保留与失败隔离 |
| [两跳证据与格式支持](multihop-image-preview.md) | 图谱证据扩展、Word 原件与 PNG/JPEG OCR |
| [流式与停止](streaming-readme.md) | SSE、草稿持久化、停止/断线恢复及引用发布 |
| [联网与链路追踪](web-search-langsmith.md) | Tavily、网页引用、LangSmith 元数据/正文与脱敏 |

[演示脚本](../deliver/企业知识助理系统演示脚本.md) 提供操作、口播和异常处理。早期实施计划及阶段流水记录已清理，历史内容可通过 Git 查看。

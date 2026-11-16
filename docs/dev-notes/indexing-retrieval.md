# 文档索引与原文检索

本文说明自动切片、向量持久化、索引发布和原文检索。上传去重、MinerU 解析与任务恢复见 [整体设计](../design.md)，聊天执行轨迹见 [检索详情](intent-retrieval-details.md)。

## 实现

- `chunking.py` 生成按 job/ordinal 确定的 UUID；文本保留字符区间，表格保留行区间、真实表头、标题/脚注、rowspan 关联和同章节相邻条款。切片可由 blocks 重建校验。默认正文 1600 字符、重叠 150；表格条件上下文各最多 6000，原子单元超过 24000 字符明确失败。
- 向量使用千问 `qwen3.7-text-embedding-flash`、1024 维；按模型、维度、文档/查询类型及文本格式冻结 profile。每批至多 20 条，成功批次事务保存；正常继续投递不增加 attempt，失败重试跳过已保存向量。
- 发布按 document→version→job 加锁，检查当前租约、切片与所有向量；ready/done 与发布指针同事务更新。version_no/generation_no 单调推进；新版或新代次失败保留旧索引。
- jieba / BM25 与 pgvector 精确余弦双路召回，经 RRF 按 chunk_id 去重和千问 Rerank。检索开始用一致读事务固定当前已发布版本/job 清单，整个请求沿用快照。BM25 进程缓存按 ready job 清单失效，最多 8 份。
- 默认返回 6 条，最多 20；召回候选最多 100，重排字符预算 28000。超预算保留召回候选并提示，模型超时明确 warnings；召回完全故障返回 503，profile 变化返回 409 要求重建。
- “重建索引”复用同版本已保存解析，创建新处理代次；“重新解析”继续执行云解析。重试与新任务使用一致锁顺序，版本已有活动任务时返回 409。

## 接口与页面

- `POST /api/search {question, document_ids?, top_k}`。省略范围表示全部已发布文档；显式空范围、重复 ID 拒绝，无效/未就绪范围 409，绝不自动扩大。
- `GET /api/chunks/{id}`；`GET /api/document-versions/{id}/chunks?job_id=&offset=&limit=`。仅已发布切片，返回固定 document/version/job、正文、章节、页码、locators 与原件地址，不返回向量。
- `POST /api/document-versions/{id}/reindex {job_id}`，同键幂等；重建与重新解析的请求身份分开。
- 文档管理提供“原文检索”，可选择全部或单份文档；命中项显示真实引文。来源面板展示实际索引切块，按 50 条分页，可跳回固定 job 的解析正文或固定版本 PDF 页。没有页码时按章节定位。
- ready 显示“可检索”；重建期间轮询仍继续，原结果可读。聊天生成与引用使用这些固定来源，流式协议见 [流式与停止](streaming-readme.md)，两跳扩展见 [图谱证据扩展](multihop-image-preview.md)。

相关回归：`backend/tests/test_chunking.py`、`test_indexing_jobs.py`、`test_search_api.py`、`test_ranking.py`；命令见根 [README](../../README.md#验证与开发)。

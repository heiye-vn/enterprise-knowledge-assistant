# 真实文档解析（2026-11-14）

本阶段实现总计划 Task 4。PDF/DOCX 使用 MinerU 官方 v4 API，Markdown 使用本地 token AST；切片、Embedding、检索、问答和图谱抽取仍属于后续阶段。

## 配置与接口

在私有 `.env` 中填写 `KH_MINERU_API_TOKEN`，可选 `KH_MINERU_MODEL=vlm`、`KH_MINERU_LANGUAGE=ch`。Token 用 SecretStr 读取，不进入任务 config、API 返回、日志或协议夹具。配置变更后重建运行 Worker/Beat，并重启 API。

- `POST /api/document-versions/{version_id}/reprocess`，JSON 为 `{"job_id":"客户端生成的 UUID"}`。同请求标识幂等；不同版本复用标识返回 409；同版本有另一活动任务时返回 409 和既有 job_id。新代次保留原件和已有解析结果。
- `GET /api/document-versions/{version_id}/parsed` 返回该版本最近可用结果及最新任务状态，`result=null` 表示尚无结果；可选 `job_id` 固定历史代次，没有对应结果时返回 404。
- `GET /api/processing-jobs/{job_id}/assets/{asset_id}` 仅返回 manifest 登记的 PNG/JPEG/WebP；预签名地址不暴露给前端。

## 处理与恢复

外部提交前持久化 submitting 意图；收到 batch_id 后先持久化再上传。提交结果不确定时不盲目新建任务。恢复复用 batch；上传结果不确定时先查询远端状态，已经处理的原件不再上传。

等待结果时释放租约，保留 queued/parsing 与下次投递时间，由 Beat 继续；正常轮询不递增 attempt。故障恢复或显式重试才消耗尝试次数。解析等待默认上限 30 分钟；done 后单独持久化 downloading 检查点，归档下载允许 24 小时，不受解析等待期限限制。发布须校验当前租约令牌及有效期。

RustFS 保存完整原始 ZIP 与图片，按 job/lease_token 隔离。ZIP 仅在内存读取，拒绝危险路径、重复成员、符号链接、加密成员及超限归档；默认压缩后 50 MB、解压后 100 MB、2000 成员。资源仅访问 HTTPS 的 MinerU/OpenXLab/阿里云域，无 Bearer 头，不跟随重定向。

归档须有唯一 full.md 和 *_content_list.json。规范化保留标题路径、表格单元格/合并范围、表题/脚注、代码、列表、图片关联。PDF page_idx 的 0-based 值转换一次为 1-based，并与原件 pypdf 页数核对；DOCX/MD 不虚构页码。bbox 不假定单位，原始信息保存在归档中。

DocumentContent 按 job 持久化。由于索引尚未接入，完整 import 在 chunking 阶段记录 `index_not_configured`（raw status=failed，不可普通重试）；文档/解析视图显示 `parsed / 解析完成`，can_query=false。不写 ready、current_version_id 或 active_import_job_id；后续索引完成再事务发布。

未引用的原件和解析对象在 24 小时后清理；DocumentContent 引用或活动任务中的对象保留。

## 真实验收

使用用户配置的 Token，真实调用 v4 file-urls/batch、预签名 PUT、extract-results/batch 和归档下载。默认测试不调用云服务。

| 输入 | 结果 |
| --- | --- |
| version_chatgpt/知识库语料/01_费用报销管理制度.pdf | 4 页、62 块，含 7 个标题、3 张表格；核对金额、审批链、条件和页码。 |
| version_chatgpt/知识库语料/04_采购管理制度.docx | 44 块，含 9 个标题、4 张表格、2 个列表；页码为 null。 |
| 临时带文字流程图 PDF（新版本） | Linux Worker/Beat 完成云端解析；1 个图片块、1 个文字块，JPEG 资源接口 200，浏览器显示流程图。 |
| 临时 Markdown 审批规则 | 真实队列处理，保留标题、500 元条件、审批表和代码；不生成页码。 |

第一次无标签色块示例未被 MinerU 返回为图片，没有伪造图片块；带标签流程图随后通过真实图片验收。

PDF 重新解析曾遇到 CDN 下载故障；第 1 次结果仍可查看。检查中补充独立 downloading 检查点及跨解析期限恢复测试，以便取回既有结果。诊断只记录异常类型与 HTTP 状态，不记录资源查询参数。

实际返回的 PDF/DOCX 内容与响应样本在 `backend/tests/fixtures/mineru-*-{content,result}.json`（任务标识和 URL 已替换）。浏览器核对正文/表格、内容块、DOCX 章节定位、图片、新旧版本以及跳转 PDF 第 3/4 页；React 结构化渲染，不注入远端 HTML。本轮临时验收记录和对象在验收后清理，原始 test-data 保留。

最终验证：后端默认与真实基础设施测试合计 112 项通过，前端 31 项通过，Ruff、Alembic check 和 Node 22 构建通过。构建仍有既有 PDF 阅读器大分包提示。临时验收清理范围为本轮 4 份文档、5 个版本及其任务/对象，保留全部原始 test-data。

清理实测：4 份临时文档、5 个版本、11 个 RustFS 对象已移除，API 列表为空；四项依赖健康检查 200，Worker/Beat 正常。诊断时仅对隔离验收任务提高了尝试上限并迁移已完成远端结果的检查点，默认 3 次上限没有改变，也没有为下载重试创建新远端任务。

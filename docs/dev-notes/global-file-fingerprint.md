# 全库文件指纹检查

后续实现更新：[真实上传记录](document-import.md)已完成本文的正式写入接入；以下保留预检查阶段的验证历史。

日期：2026-11-14。用户确认新增全库文件指纹检查，避免同一文件通过不同 document_id 重复导入。本记录取代此前“上传允许不同逻辑文档保存相同字节”的业务约定；原数据库约束和历史记录继续兼容。

## 行为

- 指纹是原始文件字节的 SHA-256，与文件名、标题、分类无关。改名的同一文件会命中；重新导出或转换格式后字节不同，不按正文语义去重。
- 检查未软删除文档的所有历史版本，包括尚未解析完成的原件，不限定为当前版本、当前页或 ready 文档。软删除文档不阻止重新导入。
- `POST /api/documents/check-duplicate` 接收 `{ "file_sha256": "64位小写十六进制" }`；返回 `file_sha256 / duplicate / existing`，existing 为 null 或包含 document_id、version_id、title、filename、version_no。读取不加载正文、块或向量；数据库故障返回 503，非法指纹返回 422。
- 前端选择文件后检查，提交前再次检查；同批相同文件只保留第一份，重复项展示已有文档标题。对于本页已有文档提供“查看已有文档”，其余库内匹配先展示身份信息，真实文档列表和原件读取仍由下一阶段接入。
- 更换选择、取消或关闭弹窗会取消检查；检查中及检查失败时不能提交。已导入的演示文件在本页保留指纹，后续重复选择仍可识别；刷新后恢复初始示例。

## 正式写入边界

预检查本身不占用指纹，不能单独保证并发下只建一份。`backend/app/importing/fingerprints.py` 提供 `lock_and_check_file(db, content)`：服务端从实际字节重新计算指纹，取得 PostgreSQL 事务级 advisory lock，再查询全库；锁保持到调用方提交或回滚。

正式上传创建/新版本接口必须在 READ COMMITTED 事务中调用这一边界，再决定复用既有版本或创建原件引用、文档、版本和任务。所有上传入口都必须遵守，不能只查客户端提供的 hash。数据库保留同文档 hash 唯一约束，新增 `0002_file_fingerprint` 非唯一查询索引；不改写已执行的初始迁移，不增加业务表。

目前原件上传、任务投递、MinerU 和索引链路尚未实现。这次交付真实预检查接口、前端防重复演示和后续写入的并发保护函数，不将预检查称作完整导入链路。

## 验证

先运行新增后端与前端测试，确认因缺少指纹模块和接口失败，再实现。默认测试覆盖文件字节身份、接口校验和故障；真实 PG 测试覆盖全库命中、历史版本、软删除以及两个独立事务并发检查后只登记一份原件。迁移测试覆盖升级、回退重建及 ORM 无差异。

验证命令：`uv run --project backend pytest backend/tests -m 'integration or not integration' -q`、`uv run --project backend ruff check backend`、`uv run --project backend ruff format --check backend`、`uv run --project backend alembic -c backend/alembic.ini check`、`pnpm --dir frontend test`、`pnpm --dir frontend build`。

实际结果：后端 62 项测试（24 默认 + 38 真实集成）、前端 26 项测试与生产构建通过；Ruff 检查及格式检查通过，应用库已升级至 `0002_file_fingerprint`，Alembic check 无差异，ready 四项依赖均正常。首次全量测试因应用库尚未升级新索引导致 ready 检查失败，完成迁移后全量重跑通过。

浏览器实际验证：已有 PDF 命中并打开已有文档；同批同字节只新增一条演示记录；导入后改名重传被拦截；真实数据库中未加载到页面的文档能被识别。另模拟检查接口 503，确认提交禁用且重新检查可恢复；390px 窄屏弹窗无横向溢出。临时浏览器验收数据库记录已清理。构建保留原有 PDF 阅读器分包大小提醒。

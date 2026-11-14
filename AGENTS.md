# 提交规范

后续 Git 提交遵循 [Conventional Commits 1.0.0](https://www.conventionalcommits.org/en/v1.0.0/)，使用以下约定。

- 提交标题格式为 `type(scope): description`，`scope` 可省略；类型使用小写，描述简洁明确，可使用中文。
- 常用类型：`feat`（功能）、`fix`（修复）、`docs`（文档）、`test`（测试）、`refactor`（重构）、`perf`（性能）、`build`（构建与依赖）、`ci`（持续集成）、`chore`（维护与资料整理）。
- 不兼容变更在类型或范围后添加 `!`，或在正文使用 `BREAKING CHANGE:` 说明影响。
- 每个提交围绕一项明确变更，不混入无关修改；按变更范围完成适当验证后再提交。
- 示例：`feat(chat): 支持流式回答`、`fix(import): 修复重复上传判断`、`chore(test-data): 统一测试资料目录`。

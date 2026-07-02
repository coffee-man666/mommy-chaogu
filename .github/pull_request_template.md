## 改动描述

清晰描述改了什么。

## 为什么

解释为什么需要这个改动（引用相关 issue）。

## 怎么验证

- [ ] 单元测试已添加
- [ ] 手动测试通过
- [ ] 没有破坏现有功能

## 质量门

- [ ] `uv run ruff format .` 无 diff
- [ ] `uv run ruff check .` 无 errors
- [ ] `uv run mypy --strict src` 无 errors
- [ ] `uv run pytest -m "not network"` 全过

## 检查清单

- [ ] 代码风格符合 [`CONTRIBUTING.md`](CONTRIBUTING.md)
- [ ] 新功能有对应测试
- [ ] commit message 符合 Conventional Commits 格式
- [ ] 文档已更新（如果适用）

## 关联 Issue

Closes # / Fixes # / Related to #

## 截图 / 日志

如果适用。
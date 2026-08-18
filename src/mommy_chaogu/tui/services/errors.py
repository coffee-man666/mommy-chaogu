"""错误文案友好映射（薄壳）。

实现在 :mod:`mommy_chaogu.errors`（包根，无 GUI 依赖），
CLI 与 TUI 共用同一份映射；这里保留原导入路径兼容既有调用方。
"""

from __future__ import annotations

from mommy_chaogu.errors import friendly_error

__all__ = ["friendly_error"]

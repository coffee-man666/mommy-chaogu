"""股票代码识别的统一真相源。

此前 ``_CODE_RE`` 在 agent/research_context、agent/research_tools、
agent/tools/strategies 等处各自定义，pattern 微妙漂移（收不收 ``^`` 指数
前缀、收不收 ``BRK.B`` 类点号后缀）。本模块收敛为四个语义明确的变体：

- :data:`STOCK_CODE_PATTERN` — 个股（A 股 6 位数字 / 美股字母，含 BRK.B）
- :data:`INDEX_OR_STOCK_CODE_PATTERN` — 个股 + ``^GSPC`` 类指数/利率代码
- :data:`CODE_IN_TEXT_PATTERN` — 从自由文本中抽取代码（带边界环视）
- :data:`A_SHARE_CODE_PATTERN` — 仅 A 股 6 位（analysis 等 A 股独有域）

边界说明：web 层 Pydantic / URL path 校验（``[A-Z]{1,6}|\\d{6}``）与
workflow/definitions 的宽松提取器（``\\b``）是各自层的独立契约，
有意保持现状，不在本模块强行归一。
"""

from __future__ import annotations

import re

__all__ = [
    "A_SHARE_CODE_PATTERN",
    "A_SHARE_CODE_RE",
    "CODE_IN_TEXT_PATTERN",
    "CODE_IN_TEXT_RE",
    "INDEX_OR_STOCK_CODE_PATTERN",
    "INDEX_OR_STOCK_CODE_RE",
    "STOCK_CODE_PATTERN",
    "STOCK_CODE_RE",
]

#: 个股代码（整串匹配）：A 股 6 位数字 / 美股 1-6 位字母（含 BRK.B / BF-B）
STOCK_CODE_PATTERN = r"^(?:[A-Z]{1,6}(?:[.-][A-Z])?|\d{6})$"

#: 个股 + 指数/利率代码（整串匹配）：在个股之上收 ``^`` 前缀（^GSPC / ^TNX）
INDEX_OR_STOCK_CODE_PATTERN = r"^(\^[A-Z]{1,6}|[A-Z]{1,6}(?:[.-][A-Z])?|\d{6})$"

#: 自由文本中的代码抽取：前后环视防 "AAPLX"、"1234567" 类误切
CODE_IN_TEXT_PATTERN = r"(?<![A-Z0-9])(\^?[A-Z]{1,6}(?:[.-][A-Z])?|\d{6})(?![A-Z0-9])"

#: 仅 A 股（整串匹配）：analysis 等 A 股独有域的刻意收窄
A_SHARE_CODE_PATTERN = r"^\d{6}$"

STOCK_CODE_RE = re.compile(STOCK_CODE_PATTERN)
INDEX_OR_STOCK_CODE_RE = re.compile(INDEX_OR_STOCK_CODE_PATTERN)
CODE_IN_TEXT_RE = re.compile(CODE_IN_TEXT_PATTERN)
A_SHARE_CODE_RE = re.compile(A_SHARE_CODE_PATTERN)

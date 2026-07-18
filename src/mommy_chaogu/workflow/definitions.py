"""9 个预定义工作流。

覆盖 80% 日常投资操作场景。每个工作流是一组有序的工具调用，
最后可选接一个 LLM 总结步骤。
"""

from __future__ import annotations

import re
from typing import Any

from mommy_chaogu.workflow.engine import Workflow, WorkflowRegistry, WorkflowStep

# ============================================================
# 参数提取辅助函数
# ============================================================

_STOCK_CODE_RE = re.compile(r"\b(\d{6})\b")


def _extract_stock_code(user_input: str, _: list[dict[str, Any]]) -> dict[str, Any]:
    """从用户输入中提取 6 位股票代码。"""
    m = _STOCK_CODE_RE.search(user_input)
    if m:
        return {"code": m.group(1)}
    # 尝试中文名称 → 暂时返回空，让 LLM 总结时提示
    return {}


def _extract_sector_keyword(user_input: str, _: list[dict[str, Any]]) -> dict[str, Any]:
    """从用户输入中提取板块关键词。

    匹配模式如 "半导体板块"、"创新药板块" 中的关键词。
    """
    # 去掉"板块"、"怎么样"等词
    text = re.sub(r"(板块|怎么样|分析|行情|表现|如何)", "", user_input).strip()
    if text:
        return {"keyword": text}
    return {}


def _extract_sector_code_from_prev(
    user_input: str,
    previous: list[dict[str, Any]],
) -> dict[str, Any]:
    """从前一步的 search_sector 结果中提取板块代码。"""
    for step_data in previous:
        if step_data.get("tool") == "search_sector":
            result = step_data.get("result")
            if isinstance(result, list) and result:
                first = result[0]
                if isinstance(first, dict) and "board_code" in first:
                    return {"board_code": first["board_code"]}
            elif isinstance(result, dict) and "board_code" in result:
                return {"board_code": result["board_code"]}
    return {}


def _extract_codes_from_watchlist(
    _: str,
    previous: list[dict[str, Any]],
) -> dict[str, Any]:
    """从前一步的 get_watchlist 结果中提取股票代码列表。"""
    codes: list[str] = []
    for step_data in previous:
        if step_data.get("tool") == "get_watchlist":
            result = step_data.get("result")
            if isinstance(result, list):
                for item in result:
                    if isinstance(item, dict) and "code" in item:
                        codes.append(item["code"])
            elif isinstance(result, dict):
                # 可能是 {"groups": [...]}
                for group in result.get("groups", []):
                    for stock in group.get("stocks", []):
                        if isinstance(stock, dict) and "code" in stock:
                            codes.append(stock["code"])
    return {"codes": codes[:50]} if codes else {}


def _extract_codes_from_portfolio(
    _: str,
    previous: list[dict[str, Any]],
) -> dict[str, Any]:
    """从前一步的 get_portfolio 结果中提取持仓股票代码列表。"""
    codes: list[str] = []
    for step_data in previous:
        if step_data.get("tool") == "get_portfolio":
            result = step_data.get("result")
            if isinstance(result, dict):
                for pos in result.get("positions", []):
                    if isinstance(pos, dict) and "code" in pos:
                        codes.append(pos["code"])
    return {"codes": codes[:50]} if codes else {}


# ============================================================
# 通用总结模板
# ============================================================

_MARKET_SUMMARY = """\
请基于以下数据用通俗的语言给妈妈做今日行情概览。

## 数据
{context}

## 要求
1. 先一句话总结今天大盘整体表现（涨了还是跌了，成交量如何）
2. 板块亮点（哪些板块涨得好，哪些差）
3. 如果有自选股数据，简要说一下自选股的表现
4. 用"亿元""万元"等人类可读单位
5. 不加"以上不构成投资建议"等免责声明
6. 控制在 200 字以内
"""

_STOCK_ANALYSIS_SUMMARY = """\
请基于以下数据用通俗的语言分析这只股票。

## 数据
{context}

## 要求
1. 先说结论（近期趋势偏强还是偏弱）
2. 量价关系（放量还是缩量，资金流入还是流出）
3. 如果有资金流数据，分析主力动向（bp 指标）
4. 给出关注点（有没有需要特别注意的信号）
5. 用"亿元""万元"等人类可读单位
6. 不加免责声明，控制在 300 字以内
"""

_SECTOR_SUMMARY = """\
请基于以下数据用通俗的语言分析这个板块。

## 数据
{context}

## 要求
1. 板块整体表现（平均涨跌幅、成交额）
2. 涨幅 TOP 3 个股点评
3. 资金流向（主力在买还是卖）
4. 控制在 250 字以内
"""

_FLOW_SUMMARY = """\
请基于以下资金流数据用通俗的语言解读主力动向。

## 数据
{context}

## 要求
1. 主力主要在流入哪些股票/板块（列出 TOP 3）
2. 主力主要在流出哪些（列出 TOP 3）
3. 有没有明显的异动信号（单只 >10bp）
4. 控制在 250 字以内
"""

_PORTFOLIO_SUMMARY = """\
请基于以下数据用通俗的语言点评妈妈的持仓。

## 数据
{context}

## 要求
1. 整体盈亏（总共赚了还是亏了，比例多少）
2. 每只持仓简评（一两句话）
3. 哪些表现好可以持有，哪些需要注意
4. 用"元""万元"等人类可读单位
5. 控制在 300 字以内
"""

_CLOSE_REPORT_SUMMARY = """\
请基于以下数据撰写今日收盘分析报告。

## 数据
{context}

## 要求
1. 一句话总结（今天行情怎么样）
2. 大盘 + 板块分析
3. 资金流解读（主力在买还是卖）
4. 自选股/持仓点评
5. 明日关注点
6. 全文 800 字以内，markdown 格式
7. 不加免责声明
"""

_EARNINGS_SUMMARY = """\
请基于以下数据分析这些股票的业绩情况。

## 数据
{context}

## 要求
1. 哪些股票有业绩数据，预测增速是多少
2. 已披露实际值的，和预测对比如何
3. 近期有哪些要披露的（日历提醒）
4. 控制在 250 字以内
"""


# ============================================================
# 工作流定义
# ============================================================

WORKFLOWS: list[Workflow] = [
    # ----------------------------------------------------------
    # 1. 每日概览
    # ----------------------------------------------------------
    Workflow(
        id="morning_brief",
        trigger_patterns=[
            r"今天.*怎么样",
            r"今天.*如何",
            r"早盘",
            r"今日.*概览",
            r"今日.*行情",
            r"看一下.*今天",
            r"帮我看看",
            r"今日盘面",
        ],
        description="今日行情概览：大盘 + 板块 + 自选股",
        steps=[
            WorkflowStep(
                tool_name="get_market_indexes",
                display_name="正在获取大盘指数",
            ),
            WorkflowStep(
                tool_name="get_sector_ranking",
                display_name="正在获取板块排行",
                args={"limit": 10},
            ),
            WorkflowStep(
                tool_name="get_watchlist",
                display_name="正在查看自选股",
            ),
        ],
        summary_template=_MARKET_SUMMARY,
    ),
    # ----------------------------------------------------------
    # 2. 大盘行情
    # ----------------------------------------------------------
    Workflow(
        id="market_check",
        trigger_patterns=[
            r"大盘.*怎么样",
            r"大盘.*如何",
            r"行情.*怎么样",
            r"行情.*如何",
            r"指数.*怎么样",
            r"今天.*涨.*跌",
        ],
        description="大盘指数 + 板块行情",
        steps=[
            WorkflowStep(
                tool_name="get_market_indexes",
                display_name="正在获取大盘指数",
            ),
            WorkflowStep(
                tool_name="get_sector_ranking",
                display_name="正在获取板块排行",
                args={"limit": 15},
            ),
        ],
        summary_template=_MARKET_SUMMARY,
    ),
    # ----------------------------------------------------------
    # 3. 添加自选股
    # ----------------------------------------------------------
    Workflow(
        id="add_watchlist",
        trigger_patterns=[
            r"加.*自选",
            r"关注.*股票",
            r"添加.*自选",
            r"加.*关注",
        ],
        description="添加自选股（需提供股票代码）",
        steps=[
            WorkflowStep(
                tool_name="manage_alert",
                display_name="正在添加自选股",
                args_extractor=_extract_stock_code,
                args={
                    "action": "add",
                    "alert_type": "price_above",
                    "threshold": 0,  # 占位，manage_alert 需要参数
                },
                optional=True,  # 这个工作流主要是提示用户操作
            ),
        ],
        summary_template=(
            "用户想添加自选股。提取到的信息：{context}\n"
            "请告诉用户如何添加（给出具体命令或建议）。如果已提取到代码，"
            "请提示用户可以通过 Web 界面或 mommy-watchlist add 命令添加。"
            "控制在 100 字以内。"
        ),
    ),
    # ----------------------------------------------------------
    # 4. 个股分析
    # ----------------------------------------------------------
    Workflow(
        id="stock_analysis",
        trigger_patterns=[
            r"分析.*股票",
            r"分析.*\d{6}",
            r".*分析一下",
            r"\d{6}.*怎么样",
            r"\d{6}.*分析",
        ],
        description="单只股票深度分析：报价 + K线 + 资金流",
        steps=[
            WorkflowStep(
                tool_name="get_quote",
                display_name="正在获取实时报价",
                args_extractor=_extract_stock_code,
            ),
            WorkflowStep(
                tool_name="get_bars",
                display_name="正在获取近期K线",
                args_extractor=_extract_stock_code,
                args={"interval": "1d", "count": 20},
            ),
            WorkflowStep(
                tool_name="get_money_flow_today",
                display_name="正在获取资金流",
                args_extractor=_extract_stock_code,
                optional=True,
            ),
        ],
        summary_template=_STOCK_ANALYSIS_SUMMARY,
    ),
    # ----------------------------------------------------------
    # 5. 板块分析
    # ----------------------------------------------------------
    Workflow(
        id="sector_scan",
        trigger_patterns=[
            r".*板块.*怎么样",
            r".*板块.*分析",
            r".*板块.*行情",
            r".*板块.*表现",
            r"看看.*板块",
        ],
        description="板块分析：排行 + 成分股",
        steps=[
            WorkflowStep(
                tool_name="search_sector",
                display_name="正在搜索板块",
                args_extractor=_extract_sector_keyword,
            ),
            WorkflowStep(
                tool_name="get_sector_stocks",
                display_name="正在获取板块成分股",
                args_extractor=_extract_sector_code_from_prev,
                args={"limit": 10, "sort_by": "change_pct"},
            ),
        ],
        summary_template=_SECTOR_SUMMARY,
    ),
    # ----------------------------------------------------------
    # 6. 资金流检查
    # ----------------------------------------------------------
    Workflow(
        id="flow_check",
        trigger_patterns=[
            r"资金流.*怎么样",
            r"资金.*如何",
            r"主力.*在.*买",
            r"主力.*在.*卖",
            r"主力.*流向",
            r"资金.*异动",
        ],
        description="主力资金流分析",
        steps=[
            WorkflowStep(
                tool_name="get_money_flow_today",
                display_name="正在获取自选股资金流",
                args_extractor=_extract_codes_from_watchlist,
                optional=True,
            ),
            WorkflowStep(
                tool_name="get_sector_ranking",
                display_name="正在获取板块资金流排行",
                args={"limit": 10},
            ),
        ],
        summary_template=_FLOW_SUMMARY,
    ),
    # ----------------------------------------------------------
    # 7. 持仓点评
    # ----------------------------------------------------------
    Workflow(
        id="portfolio_review",
        trigger_patterns=[
            r"持仓.*怎么样",
            r"我的.*股票.*怎么样",
            r"我的.*持仓",
            r"持仓.*表现",
            r"看看.*持仓",
        ],
        description="持仓综合点评",
        steps=[
            WorkflowStep(
                tool_name="get_portfolio",
                display_name="正在获取持仓信息",
            ),
            WorkflowStep(
                tool_name="get_quotes",
                display_name="正在获取持仓实时报价",
                args_extractor=_extract_codes_from_portfolio,
            ),
            WorkflowStep(
                tool_name="get_portfolio_analysis",
                display_name="正在分析持仓风险",
                optional=True,
            ),
        ],
        summary_template=_PORTFOLIO_SUMMARY,
    ),
    # ----------------------------------------------------------
    # 8. 业绩查询
    # ----------------------------------------------------------
    Workflow(
        id="earnings_check",
        trigger_patterns=[
            r".*业绩.*怎么样",
            r".*中报",
            r".*财报",
            r".*业绩.*披露",
            r".*利润.*增长",
        ],
        description="业绩前瞻 vs 实际披露查询",
        steps=[
            WorkflowStep(
                tool_name="get_fundamentals",
                display_name="正在获取基本面数据",
                args_extractor=_extract_stock_code,
            ),
            WorkflowStep(
                tool_name="get_announcements",
                display_name="正在查询公告",
                args_extractor=_extract_stock_code,
                args={"limit": 5},
                optional=True,
            ),
        ],
        summary_template=_EARNINGS_SUMMARY,
    ),
    # ----------------------------------------------------------
    # 9. 收盘报告
    # ----------------------------------------------------------
    Workflow(
        id="close_report",
        trigger_patterns=[
            r"收盘.*报告",
            r"今日.*总结",
            r"收盘.*总结",
            r"写.*报告",
            r"生成.*报告",
        ],
        description="生成今日收盘分析报告",
        steps=[
            WorkflowStep(
                tool_name="get_market_indexes",
                display_name="正在获取大盘指数",
            ),
            WorkflowStep(
                tool_name="get_sector_ranking",
                display_name="正在获取板块排行",
                args={"limit": 15},
            ),
            WorkflowStep(
                tool_name="get_watchlist",
                display_name="正在查看自选股",
            ),
            WorkflowStep(
                tool_name="get_portfolio",
                display_name="正在查看持仓",
                optional=True,
            ),
        ],
        summary_template=_CLOSE_REPORT_SUMMARY,
    ),
]

_DEFAULT_REGISTRY = WorkflowRegistry()
for _workflow in WORKFLOWS:
    _DEFAULT_REGISTRY.register(_workflow)


def get_default_registry() -> WorkflowRegistry:
    """获取包含所有预定义工作流的注册表。

    Returns:
        已注册 9 个工作流的 WorkflowRegistry。
    """
    return _DEFAULT_REGISTRY

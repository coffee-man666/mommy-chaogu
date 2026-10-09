"""11 个预定义工作流。

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

_STOCK_CODE_RE = re.compile(r"\b(\d{6}|[A-Z]{1,6})\b")

# 工作流是确定性路由，不经过 LLM，所以用户口语里的指令包装必须在这里剥掉，
# 才能把纯股票名交给 get_quote 的名称解析（"分析一下比亚迪" → "比亚迪" → 002594）。
# 只剥固定指令词，不做通用分词——解析失败仍有 get_quote 的结构化错误兜底。
_COMMAND_PREFIX_RE = re.compile(
    r"^(请|帮我|帮忙|麻烦)?(分析|研究|看看|看一下|查一下|查查|盯一下|跟踪)?(一下|下)?"
)
_COMMAND_SUFFIX_RE = re.compile(
    r"(怎么样|如何|的情况|的行情|的表现|最近表现|的走势|值不值得买|能买吗|可以买吗)$"
)


def _strip_command_wrapper(text: str) -> str:
    """剥掉"分析一下…"/"…怎么样"这类指令包装，保留核心标的名称。"""
    stripped = text.strip()
    # 前缀最多剥两轮（"帮我分析一下" 这种叠加）
    for _ in range(2):
        new = _COMMAND_PREFIX_RE.sub("", stripped).strip()
        if new == stripped:
            break
        stripped = new
    for _ in range(2):
        new = _COMMAND_SUFFIX_RE.sub("", stripped).strip()
        if new == stripped:
            break
        stripped = new
    return stripped


def _extract_stock_code(user_input: str, _: list[dict[str, Any]]) -> dict[str, Any]:
    """从用户输入中提取 6 位股票代码。

    **严格模式**：只认代码，找不到就返回 ``{}``。用于不解析名称、也不校验代码的
    工具（``manage_watchlist`` / ``get_fundamentals`` / ``get_announcements``）——
    这些步骤宁可失败，也不能把 "加个自选" 这种整句原话当成代码写进自选池。
    需要名称解析的步骤请用 ``_extract_stock_name_or_code``。
    """
    m = _STOCK_CODE_RE.search(user_input)
    if m:
        return {"code": m.group(1)}
    return {}


def _extract_stock_name_or_code(user_input: str, _: list[dict[str, Any]]) -> dict[str, Any]:
    """提取股票标识：代码优先，否则回退传剥掉指令包装后的名称。

    仅供**会做名称解析**的 ``get_quote`` 使用（"比亚迪"→002594，见
    agent/tools/quote.py ``_resolve_code``，PR #72 引入）。

    早先 stock_analysis 工作流用的是严格的 ``_extract_stock_code``，找不到代码
    就返回 ``{}``，而工作流是确定性路由、**根本不过 LLM**，于是 handler 拿不到
    code 直接 KeyError，traceback 喷到终端。PR #72 只修了工具层和 LLM 提示词，
    没接上工作流层，两条路行为分裂：

        mommy "分析一下比亚迪"   -> 命中 .*分析一下 -> 工作流 -> 崩溃
        mommy "看看比亚迪"       -> 不过工作流     -> LLM 自主 search_stock -> 正常

    解析不了时 get_quote 返回带 hint 的结构化错误，不会抛异常。
    """
    m = _STOCK_CODE_RE.search(user_input)
    if m:
        return {"code": m.group(1)}
    name = _strip_command_wrapper(user_input)
    return {"code": name} if name else {}


def _extract_stock_code_from_prev(
    user_input: str,
    previous: list[dict[str, Any]],
) -> dict[str, Any]:
    """复用前一步 get_quote 已经解析好的 6 位代码。

    只有 ``get_quote`` 做了中文名 → 代码解析；``get_bars`` / 资金流等工具只认
    代码。所以第一步解析成功后，后续步骤直接取结果，避免把名字再喂给一个
    不会解析的 handler。取不到时退回原始提取逻辑。
    """
    for step_data in previous:
        if step_data.get("tool") != "get_quote":
            continue
        result = step_data.get("result")
        if isinstance(result, dict):
            code = str(result.get("code") or "").strip()
            if re.fullmatch(r"\d{6}", code):
                return {"code": code}
    return _extract_stock_name_or_code(user_input, previous)


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


def _extract_codes_from_input(
    user_input: str,
    _: list[dict[str, Any]],
) -> dict[str, Any]:
    """从用户输入中提取 6 位股票代码，包成单元素 codes 列表。

    供 check_kline_signal / check_earnings_catalyst 这类批量工具使用
    （它们收 codes 列表，不收单数 code）。
    """
    code = _extract_stock_code(user_input, _).get("code")
    return {"codes": [code]} if code else {}


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

_US_MARKET_SUMMARY = """\
请基于以下数据用通俗的语言给妈妈做美股行情概览。

## 数据
{context}

## 要求
1. 先一句话总结美股整体表现（三大指数涨跌 + VIX 恐慌程度）
2. 三大指数分别点评（标普500 / 纳斯达克 / 道琼斯）
3. 10 年期美债利率（^TNX）的变动方向，和股市的联动
4. 用美元/百分比做单位，不要用"亿元"等人民币单位
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

_CLOSED_LOOP_SUMMARY = """\
请基于以下数据按「个股闭环」四段结构回答这只股票的检查结果。

## 数据
{context}

## 要求（四段顺序固定，每段标注数据时间与依据）
1. 技术面发现：有没有"形"——是否突破前 20 日高点、收盘是否站上 MA20。
   依据在 check_kline_signal 的 evidence 字段（hit/high_20/ma20/close/bars_used），
   未命中也要写出数值（如"20 日高点 = X 元，最新完成日 K 收盘 Y 元，未突破"）；
   K 线信号按"未复权口径"解读（note 字段有标注）
2. 信息面解释：市场为何这样交易它——结合 check_earnings_catalyst 的公告标题
   （是否有业绩/财报类公告）与 name/pe/roe 做证据聚合，不下确定性结论
3. 基本面持续性：PE / ROE 概况能否支撑行情延续；数据缺失就明说缺失
4. 技术面执行：基于上述依据给观察提示（如"突破成立，关注回踩确认"），
   不给自动交易指令；数据拉不到时明确说明数据拉不到，不产出假信号
5. 不加"以上不构成投资建议"等免责声明，控制在 400 字以内
"""


# ============================================================
# 工作流定义
# ============================================================

WORKFLOWS: list[Workflow] = [
    # ----------------------------------------------------------
    # 0. 美股大盘概览
    # 放最前：morning_brief 的"今天.*怎么样"会抢先命中"美股今天怎么样"，
    # 美股相关触发词必须优先生效。
    # ----------------------------------------------------------
    Workflow(
        id="us_market_brief",
        trigger_patterns=[
            r"美股.*(怎么样|如何|行情|走势)",
            r"美国.*股市",
            r"纳斯达克|道琼斯|标普500?",
            r"美债利率|美债.*收益率",
            r"恐慌指数",
        ],
        description="美股大盘概览：三大指数 + VIX + 10Y 美债利率",
        steps=[
            WorkflowStep(
                tool_name="get_quote", display_name="正在获取标普500", args={"code": "^GSPC"}
            ),
            WorkflowStep(
                tool_name="get_quote", display_name="正在获取纳斯达克", args={"code": "^IXIC"}
            ),
            WorkflowStep(
                tool_name="get_quote", display_name="正在获取道琼斯", args={"code": "^DJI"}
            ),
            WorkflowStep(tool_name="get_quote", display_name="正在获取VIX", args={"code": "^VIX"}),
            WorkflowStep(
                tool_name="get_quote", display_name="正在获取10Y美债", args={"code": "^TNX"}
            ),
        ],
        summary_template=_US_MARKET_SUMMARY,
    ),
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
                tool_name="manage_watchlist",
                display_name="正在添加自选股",
                args_extractor=_extract_stock_code,
                args={"action": "add"},
                optional=True,  # 抠不到 6 位代码时跳过，由 LLM 总结给出引导
            ),
        ],
        summary_template=(
            "用户想添加自选股。执行结果：{context}\n"
            "如果添加成功，一句话告诉用户已加入自选股；"
            "如果执行结果为空（没有提取到 6 位股票代码），告诉用户需要提供"
            "股票代码（如'加自选 600519'）。控制在 100 字以内。"
        ),
    ),
    # ----------------------------------------------------------
    # 4. 个股分析
    # ----------------------------------------------------------
    Workflow(
        id="stock_analysis",
        trigger_patterns=[
            r"分析.*股票",
            r"分析.*(\d{6}|[A-Z]{1,6})",
            r".*分析一下",
            r"(\d{6}|[A-Z]{1,6}).*怎么样",
            r"(\d{6}|[A-Z]{1,6}).*分析",
        ],
        description="单只股票深度分析：报价 + K线 + 资金流",
        steps=[
            WorkflowStep(
                tool_name="get_quote",
                display_name="正在获取实时报价",
                # get_quote 会做中文名解析，所以这里允许传名称；
                # 后续步骤改用 _extract_stock_code_from_prev 复用解析结果
                args_extractor=_extract_stock_name_or_code,
            ),
            WorkflowStep(
                tool_name="get_bars",
                display_name="正在获取近期K线",
                # 复用 get_quote 解析出的 6 位代码：get_bars 不做名称解析
                args_extractor=_extract_stock_code_from_prev,
                args={"interval": "1d", "limit": 20},
            ),
            WorkflowStep(
                tool_name="get_money_flow_today",
                display_name="正在获取资金流",
                args_extractor=_extract_stock_code_from_prev,
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
                tool_name="get_watchlist",
                display_name="正在查看自选股",
            ),
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
    # ----------------------------------------------------------
    # 10. 个股闭环按需检查（L3 个股闭环 + 短期右侧确认）
    # 心法四段：技术面发现 → 信息面解释 → 基本面持续性 → 技术面执行。
    # 触发词用「闭环」锚定，避开 stock_analysis 已占用的"分析/怎么样"泛化正则；
    # 正则未命中时 NLRouter fallback 到 AgentService，agent 用同类工具组合
    # 同样能完成检查（工作流是固化路径而非唯一通路）。
    # ----------------------------------------------------------
    Workflow(
        id="stock_closed_loop",
        trigger_patterns=[
            r"个股闭环",
            r"按.{0,4}闭环",
            r"闭环.{0,8}(看看|看一下|检查|查一查)",
        ],
        description="个股闭环按需检查：技术面发现 → 信息面解释 → 基本面持续性 → 技术面执行",
        steps=[
            WorkflowStep(
                tool_name="get_quote",
                display_name="正在获取实时报价",
                args_extractor=_extract_stock_code,
            ),
            WorkflowStep(
                tool_name="check_kline_signal",
                display_name="正在检查20日高点突破",
                args_extractor=_extract_codes_from_input,
                args={"signal": "high_20_breakout"},
            ),
            WorkflowStep(
                tool_name="check_kline_signal",
                display_name="正在检查收盘站上MA20",
                args_extractor=_extract_codes_from_input,
                args={"signal": "price_above_ma20"},
            ),
            WorkflowStep(
                tool_name="check_earnings_catalyst",
                display_name="正在检查业绩催化与公告",
                args_extractor=_extract_codes_from_input,
            ),
        ],
        summary_template=_CLOSED_LOOP_SUMMARY,
    ),
]

_DEFAULT_REGISTRY = WorkflowRegistry()
for _workflow in WORKFLOWS:
    _DEFAULT_REGISTRY.register(_workflow)


def get_default_registry() -> WorkflowRegistry:
    """获取包含所有预定义工作流的注册表。

    Returns:
        已注册 11 个工作流的 WorkflowRegistry。
    """
    return _DEFAULT_REGISTRY

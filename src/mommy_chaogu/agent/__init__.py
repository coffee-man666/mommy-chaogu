"""Agent 模块：LLM + 工具调用 = 妈妈的行情助手。

模块结构：
- tools.py   — 把数据接口包装成 function-calling tools
- service.py — AgentService（LLM + tools 循环）
- prompt.py  — system prompt
- reports.py — agent 驱动的收盘日报
"""

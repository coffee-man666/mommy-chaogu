"""Agent 模块：LLM + 工具调用 = 妈妈的行情助手。

模块结构：
- llm.py         — provider 单一真相源（SUPPORTED_PROVIDERS）+ client 工厂
- service.py     — AgentService（LLM + tools 循环，流式/取消/后台提取）
- tools/         — function-calling tools 包（按域拆分，registry 聚合）
- prompt.py      — system prompt
- prompt_builder — 注入记忆上下文的 system prompt 构建
- memory*.py     — 记忆系统（对话 / 管道 / 服务门面）
- episodic_memory / prediction_tracker / semantic_memory / vector_search
                 — 五层记忆的持久化组件
- extractor / verify_engine / consolidator / narrative
                 — 提取、验证、提炼、叙事
- token_tracker  — LLM token 用量与成本追踪
- mcp_server.py  — 把工具暴露为 MCP 协议
- reports.py     — agent 驱动的收盘日报
"""

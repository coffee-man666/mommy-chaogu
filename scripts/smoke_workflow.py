#!/usr/bin/env python
"""Network smoke test for the workflow compiler (not part of CI).

Usage: ``uv run python scripts/smoke_workflow.py``
"""

from __future__ import annotations

import argparse
import json

from mommy_chaogu.cli_commands.agent import _build_llm_client
from mommy_chaogu.workflow.compiler import WorkflowCompiler
from mommy_chaogu.workflow.definitions import get_default_registry

OPINIONS = (
    "当自选股主力净流入超过0.5%时，检查业绩催化和K线放量上涨",
    "从持仓中找出资金流入超过1%的股票，再看最近的业绩公告",
    "筛选指定股票的5日线上穿20日线信号，并保留前20条",
)


def main() -> int:
    parser = argparse.ArgumentParser(description="工作流编译器网络冒烟")
    parser.add_argument("--opinion", action="append", help="额外观点；默认运行 3 条固定观点")
    args = parser.parse_args()
    client, model, _ = _build_llm_client()
    if client is None or model is None:
        print("未配置 LLM，跳过 network smoke")
        return 2

    def chat_raw(messages: list[dict[str, str]]) -> str:
        response = client.chat.completions.create(model=model, messages=messages, temperature=0)
        return str(response.choices[0].message.content or "")

    compiler = WorkflowCompiler(chat_raw, existing_workflows=get_default_registry().all_workflows())
    opinions = tuple(args.opinion or OPINIONS)
    for index, opinion in enumerate(opinions, start=1):
        result = compiler.compile(opinion)
        print(f"\n--- opinion {index} ---\n{opinion}")
        if result.spec is not None:
            print(json.dumps(result.spec.to_dict(), ensure_ascii=False, indent=2))
        elif result.questions:
            print(json.dumps({"kind": "questions", "questions": result.questions}, ensure_ascii=False, indent=2))
        else:
            print(json.dumps({"kind": "error", "errors": result.errors, "guidance": result.guidance}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

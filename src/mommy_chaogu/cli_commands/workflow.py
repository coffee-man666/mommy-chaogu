"""``mommy workflow`` commands for custom workflow specs."""

from __future__ import annotations

import json
import sys
from typing import Any, NoReturn

from mommy_chaogu.agent.tools import ToolRegistry
from mommy_chaogu.cli_commands.agent import _build_agent_context, _build_llm_client
from mommy_chaogu.cli_support import AGENT_DB, argparse
from mommy_chaogu.workflow.compiler import WorkflowCompiler
from mommy_chaogu.workflow.definitions import get_default_registry
from mommy_chaogu.workflow.engine import WorkflowExecutor
from mommy_chaogu.workflow.spec import WorkflowSpec
from mommy_chaogu.workflow.spec_runtime import spec_to_workflow
from mommy_chaogu.workflow.store import WorkflowStore
from mommy_chaogu.workflow.validator import blocking_issues, validate_spec


def build_workflow_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="mommy-workflow", description="自定义交易工作流")
    sub = parser.add_subparsers(dest="action", required=True)

    add = sub.add_parser("add", help="从 JSON 文件注册工作流")
    add.add_argument("file", help="WorkflowSpec JSON 文件")

    run = sub.add_parser("run", help="显式执行工作流")
    run.add_argument("id")
    run.add_argument("--set", dest="overrides", action="append", default=[], metavar="KEY=VALUE")

    sub.add_parser("list", help="列出内置和自定义工作流")
    delete = sub.add_parser("delete", help="删除自定义工作流")
    delete.add_argument("id")

    create = sub.add_parser("create", help="用 LLM 从观点编译工作流")
    create.add_argument("viewpoint")
    create.add_argument("--dry-run", action="store_true")

    update = sub.add_parser("update", help="根据新观点更新工作流")
    update.add_argument("id")
    update.add_argument("viewpoint")
    return parser


def _existing() -> list[Any]:
    return get_default_registry().all_workflows()


def _parse_overrides(values: list[str]) -> dict[str, Any]:
    overrides: dict[str, Any] = {}
    for item in values:
        if "=" not in item:
            raise ValueError(f"--set 必须是 key=value: {item}")
        key, value = item.split("=", 1)
        try:
            overrides[key] = json.loads(value)
        except json.JSONDecodeError:
            overrides[key] = value
    return overrides


def _validate(
    spec: WorkflowSpec,
    store: WorkflowStore,
    *,
    exclude_id: str | None = None,
) -> list[str]:
    existing = [*get_default_registry().all_workflows()]
    existing.extend(item[0] for item in store.load_all() if item[0].id != exclude_id)
    return validate_spec(spec, existing_workflows=existing)


def _store() -> WorkflowStore:
    return WorkflowStore(AGENT_DB)


def _cmd_add(args: argparse.Namespace) -> int:
    store = _store()
    try:
        with open(args.file, encoding="utf-8") as handle:
            spec = WorkflowSpec.from_json(handle.read())
        issues = _validate(spec, store)
        errors = blocking_issues(issues)
        if errors:
            print("工作流校验失败:")
            print("\n".join(f"- {issue}" for issue in errors))
            return 1
        store.save(spec, source_text=args.file)
        print(f"已注册 {spec.id}")
        for issue in issues:
            if issue.startswith("warning:"):
                print(issue)
        return 0
    finally:
        store.close()


def _cmd_run(args: argparse.Namespace) -> int:
    store = _store()
    try:
        spec = store.load(args.id)
        if spec is None:
            print(f"未找到自定义工作流: {args.id}")
            return 1
        issues = _validate(spec, store, exclude_id=spec.id)
        errors = blocking_issues(issues)
        if errors:
            print(f"工作流已 stale，不能执行: {', '.join(errors)}")
            return 1
        context = _build_agent_context()
        workflow = spec_to_workflow(spec, _parse_overrides(args.overrides))
        result = WorkflowExecutor(ToolRegistry(context)).execute(workflow, "")
        if result.summary:
            print(result.summary)
        else:
            print(json.dumps({"workflow_id": result.workflow_id, "steps": [step.__dict__ for step in result.steps]}, ensure_ascii=False, default=str, indent=2))
        if result.succeeded:
            store.increment_hit(spec.id)
            return 0
        return 1
    finally:
        store.close()


def _cmd_list(_: argparse.Namespace) -> int:
    store = _store()
    try:
        print("[内置]")
        for workflow in get_default_registry().all_workflows():
            print(f"  {workflow.id}: {workflow.description}")
        print("[自定义]")
        for spec, meta in store.load_all_records():
            if spec is None:
                print(f"  {meta['id']}: stale（spec JSON 无法解析）")
                continue
            issues = _validate(spec, store, exclude_id=spec.id)
            stale = " stale" if blocking_issues(issues) else ""
            print(f"  {spec.id}: {spec.description} | hits={meta['hit_count']}{stale}")
        return 0
    finally:
        store.close()


def _cmd_delete(args: argparse.Namespace) -> int:
    store = _store()
    try:
        if store.delete(args.id):
            print(f"已删除 {args.id}")
            return 0
        print(f"未找到自定义工作流: {args.id}")
        return 1
    finally:
        store.close()


def _compiler(exclude_id: str | None = None) -> WorkflowCompiler | None:
    client, model, _ = _build_llm_client()
    if client is None or model is None:
        return None

    def chat_raw(messages: list[dict[str, str]]) -> str:
        response = client.chat.completions.create(model=model, messages=messages, temperature=0)
        return str(response.choices[0].message.content or "")

    store = _store()
    try:
        existing = _existing()
        existing.extend(
            spec_to_workflow(spec)
            for spec, _meta in store.load_all()
            if spec.id != exclude_id
        )
    finally:
        store.close()
    return WorkflowCompiler(chat_raw, existing_workflows=existing)


def _cmd_compile(args: argparse.Namespace, current: WorkflowSpec | None = None) -> int:
    compiler = _compiler(current.id if current is not None else None)
    if compiler is None:
        print("未配置 LLM，请先运行 mommy setup")
        return 1
    result = compiler.compile(args.viewpoint, current_spec=current)
    if result.kind == "questions":
        print("需要补充的信息：")
        print("\n".join(f"- {question}" for question in result.questions))
        return 0
    if result.kind != "spec" or result.spec is None:
        print("编译失败：")
        print("\n".join(f"- {error}" for error in result.errors))
        if result.guidance:
            print(result.guidance)
        return 1
    if getattr(args, "dry_run", False):
        print(result.spec.to_json())
        return 0
    store = _store()
    try:
        store.save(result.spec, source_text=args.viewpoint)
        print(f"已保存 {result.spec.id}")
        return 0
    finally:
        store.close()


def _cmd_update(args: argparse.Namespace) -> int:
    store = _store()
    try:
        current = store.load(args.id)
        if current is None:
            print(f"未找到自定义工作流: {args.id}")
            return 1
    finally:
        store.close()
    return _cmd_compile(args, current=current)


def main_workflow() -> NoReturn:
    args = build_workflow_parser().parse_args(sys.argv[1:])
    commands = {
        "add": _cmd_add,
        "run": _cmd_run,
        "list": _cmd_list,
        "delete": _cmd_delete,
        "create": _cmd_compile,
        "update": _cmd_update,
    }
    raise SystemExit(commands[args.action](args))

"""DeepSeek Harness (dsh) MCP/Skill adapter.

dsh（https://github.com/deepseek-ai/deepseek-harness）通过官方
``@deepseek-ai/dsh-mcp-client`` 桥接插件消费外部 stdio MCP server。本 adapter
把 mommy 的连接行合并进 ``$DSH_HOME/cordis.patch.yml``（默认 ``~/.dsh``）。

该 patch 文件归用户所有，可能同时承载其他插件行：合并时只增删 mommy 自己的行，
其余操作原样保留；无法安全解析（含未知标签的非标量节点）时拒绝写入而不是猜。

dsh 处于 developer preview（0.x，破坏性变更预期内），本 adapter 依赖三个接口：
patch 合并语义、``@deepseek-ai/dsh-mcp-client`` 的 config 键、``<dshHome>/skills``
发现根。版本限制采用"记录基线 + doctor 漂移告警"而非硬阻断：dsh 常经 ``npx``
运行而无本地二进制，探测不到版本时硬门禁只会误伤或形同虚设。
"""

from __future__ import annotations

import re
import shutil
from pathlib import Path
from typing import Any

import yaml

from mommy_chaogu.coding_agents.base import (
    SERVER_NAME,
    ConnectionSpec,
    ConnectionStatus,
    agent_home,
    entry_matches_spec,
    inspect_status,
    install_skill,
    previous_spec,
    remove_managed_skills,
)

MCP_CLIENT_PLUGIN = "@deepseek-ai/dsh-mcp-client"
PATCH_ROW_ID = "mcp-mommy-chaogu"
# 已对照验证的 npm @deepseek-ai/dsh 版本。升级 dsh 后请跑 tests/test_dsh_adapter.py
# 回归 patch 合并与 Skills 发现，再更新此基线。
TESTED_DSH_VERSION = "0.1.1-rc.2"


def parse_dsh_version(text: str | None) -> tuple[int, int, int] | None:
    """解析 ``dsh --version`` 输出中的主版本三元组。

    预发布后缀（如 ``-rc.2``）不参与比较：基线本身就是 RC，同版本号的
    更新 RC 视为同一基线。
    """
    if not text:
        return None
    match = re.search(r"(\d+)\.(\d+)\.(\d+)", text)
    if match is None:
        return None
    return int(match.group(1)), int(match.group(2)), int(match.group(3))


def dsh_version_check(version: str | None) -> dict[str, Any]:
    """生成 doctor 用的 dsh 版本漂移检查项（非阻塞，warning 不计入 blocking）。"""
    tested = parse_dsh_version(TESTED_DSH_VERSION)
    assert tested is not None  # 基线常量必须可解析，见测试约束
    detected = parse_dsh_version(version)
    if version is not None and detected is None:
        return {
            "name": "dsh_version",
            "status": "warning",
            "detected": version,
            "tested": TESTED_DSH_VERSION,
            "message": (
                f"dsh --version 输出无法解析出版本号（{version!r}）；"
                f" mommy 按 {TESTED_DSH_VERSION} 基线验证，格式变化时连接可能失效。"
            ),
        }
    if detected is None:
        return {
            "name": "dsh_version",
            "status": "not_checked",
            "detected": None,
            "tested": TESTED_DSH_VERSION,
            "message": (
                "未探测到本地 dsh 二进制（常见于 npx 运行），无法核对版本；"
                f" mommy 按 {TESTED_DSH_VERSION} 基线验证。"
            ),
        }
    relation = "ok" if detected == tested else "warning"
    if detected == tested:
        message = f"dsh {version} 与验证基线 {TESTED_DSH_VERSION} 一致。"
    elif detected < tested:
        message = (
            f"dsh {version} 低于验证基线 {TESTED_DSH_VERSION}，"
            "patch 格式或 mcp-client 配置键可能缺失。"
        )
    else:
        message = (
            f"dsh {version} 新于验证基线 {TESTED_DSH_VERSION}（developer preview 常有"
            "破坏性变更）；若工具未出现在 dsh 中，请以 doctor 逐项结果为准。"
        )
    return {
        "name": "dsh_version",
        "status": relation,
        "detected": version,
        "tested": TESTED_DSH_VERSION,
        "message": message,
    }


class _PreservedTag:
    """占住未知标签（如 dsh 的 ``!!js``）的值，写回时原样还原标签。"""

    def __init__(self, tag: str, value: str) -> None:
        self.tag = tag
        self.value = value


class _PatchLoader(yaml.SafeLoader):
    pass


class _PatchDumper(yaml.SafeDumper):
    pass


def _preserve_unknown_tag(loader: yaml.Loader, tag: str, node: yaml.Node) -> _PreservedTag:
    if not isinstance(node, yaml.ScalarNode):
        raise RuntimeError(
            f"dsh patch 中存在带未知标签 {tag} 的非标量节点，mommy 无法安全合并；请手动添加连接行。"
        )
    value = loader.construct_scalar(node)
    return _PreservedTag(tag, value)


def _represent_preserved_tag(dumper: _PatchDumper, data: _PreservedTag) -> yaml.ScalarNode:
    return dumper.represent_scalar(data.tag, data.value)


# 显式注册的标准标签构造器优先命中；空前缀只兜底未知标签（如 !!js）。
_PatchLoader.add_multi_constructor("", _preserve_unknown_tag)
_PatchDumper.add_representer(_PreservedTag, _represent_preserved_tag)


class DshAdapter:
    def __init__(
        self,
        target: str = "dsh",
        *,
        previous: dict[str, Any] | None = None,
        force: bool = False,
        which: Any = shutil.which,
        **_: object,
    ) -> None:
        self.target = target
        self.previous = previous
        self.force = force
        self._which = which

    @property
    def _path(self) -> Path:
        return agent_home("dsh") / "cordis.patch.yml"

    def _installed(self) -> bool:
        # dsh 常以 npx 运行而没有全局二进制；家目录存在即视为可接入。
        return self._which("dsh") is not None or self._path.parent.is_dir()

    def _load(self) -> list[Any]:
        path = self._path
        if not path.is_file():
            return []
        try:
            value = yaml.load(path.read_text(encoding="utf-8"), Loader=_PatchLoader)
        except yaml.YAMLError as exc:
            raise RuntimeError(f"dsh patch 文件不是有效 YAML：{path}（{exc}）") from exc
        if value is None:
            return []
        if not isinstance(value, list):
            raise RuntimeError(f"dsh patch 文件必须是操作列表：{path}")
        return value

    def _save(self, patches: list[Any]) -> None:
        path = self._path
        path.parent.mkdir(parents=True, exist_ok=True)
        temp = path.with_suffix(".tmp")
        temp.write_text(
            yaml.dump(patches, Dumper=_PatchDumper, allow_unicode=True, sort_keys=False),
            encoding="utf-8",
        )
        temp.replace(path)

    def _find_row(self, patches: list[Any]) -> tuple[int, int] | None:
        """返回 (操作索引, 行索引)；行身份 = mcp-client 插件 + mommy 的 serverName。"""
        for op_index, op in enumerate(patches):
            if not isinstance(op, dict):
                continue
            rows = op.get("insert")
            if not isinstance(rows, list):
                continue
            for row_index, row in enumerate(rows):
                if not isinstance(row, dict):
                    continue
                config = row.get("config")
                if (
                    row.get("name") == MCP_CLIENT_PLUGIN
                    and isinstance(config, dict)
                    and config.get("serverName") == SERVER_NAME
                ):
                    return op_index, row_index
        return None

    def _entry(self) -> dict[str, Any] | None:
        patches = self._load()
        found = self._find_row(patches)
        if found is None:
            return None
        op_index, row_index = found
        config = patches[op_index]["insert"][row_index].get("config")
        return config if isinstance(config, dict) else None

    def _build_row(self, spec: ConnectionSpec) -> dict[str, Any]:
        return {
            "id": PATCH_ROW_ID,
            "name": MCP_CLIENT_PLUGIN,
            "config": {
                "serverName": SERVER_NAME,
                "transport": "stdio",
                "command": spec.command,
                "args": list(spec.args),
                "env": dict(spec.env),
                "cwd": spec.cwd,
            },
        }

    def register_mcp(self, spec: ConnectionSpec) -> None:
        if not self._installed():
            raise RuntimeError(
                "没有找到 dsh（PATH 上的 dsh、$DSH_HOME 或 ~/.dsh 均不存在）；"
                "请先运行 npx @deepseek-ai/dsh web 至少一次，或设置 DSH_HOME。"
            )
        patches = self._load()
        found = self._find_row(patches)
        if found is not None and self.previous is None and not self.force:
            raise RuntimeError(f"dsh 中已存在非本工具管理的 {SERVER_NAME}")
        if found is not None and self.previous is not None and not self.force:
            old = previous_spec(self.previous)
            op_index, row_index = found
            current = patches[op_index]["insert"][row_index].get("config")
            if (
                old is None
                or not isinstance(current, dict)
                or not entry_matches_spec("dsh", current, old)
            ):
                raise RuntimeError("检测到 dsh MCP 配置已被修改；为避免覆盖请加 --force。")
        if found is not None:
            op_index, row_index = found
            patches[op_index]["insert"][row_index] = self._build_row(spec)
        else:
            patches.append({"insert": [self._build_row(spec)]})
        self._save(patches)

    def install_skill(self, source: Path) -> Path:
        return install_skill("dsh", source, self.previous, force=self.force)

    def inspect_status(self) -> ConnectionStatus:
        return inspect_status("dsh", self.previous, self._entry())

    def disconnect(self) -> None:
        patches = self._load()
        found = self._find_row(patches)
        old = previous_spec(self.previous)
        if found is not None:
            op_index, row_index = found
            current = patches[op_index]["insert"][row_index].get("config")
            if (
                old is not None
                and isinstance(current, dict)
                and entry_matches_spec("dsh", current, old)
            ):
                rows = patches[op_index]["insert"]
                del rows[row_index]
                if not rows:
                    # 空的 insert 操作没有意义，一并移除，避免留下 `- insert: []`。
                    del patches[op_index]
                self._save(patches)
            else:
                print("⚠ 保留已被修改的 dsh MCP 配置。")
        remove_managed_skills("dsh", self.previous)

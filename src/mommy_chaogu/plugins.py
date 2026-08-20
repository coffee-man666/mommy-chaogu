"""Project plugin catalog shared by connectors, diagnostics, and packaging.

The catalog is deliberately small and static: a plugin is currently a
bundled Agent Skill directory.  Keeping the names and order here prevents the
connector, the agent-managed plan, and the public Plugins Store from drifting
apart as new project Skills are added.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True, slots=True)
class BundledPlugin:
    """Metadata for a plugin shipped with mommy-chaogu."""

    name: str
    version: str
    title: str
    summary: str
    category: str
    archive: str | None = None


BUNDLED_PLUGINS: tuple[BundledPlugin, ...] = (
    BundledPlugin(
        name="mommy-onboard",
        version="1.5.0",
        title="Mommy Onboard",
        summary="解释产品边界、展示连接计划，并把宿主 Agent 安全带入投研工具箱。",
        category="onboarding",
        archive="skills/mommy-onboard-v1.5.0.zip",
    ),
    BundledPlugin(
        name="mommy-research",
        version="1.5.0",
        title="Mommy Research",
        summary="用带时间戳和来源的行情、板块、资金流与业绩证据完成研究。",
        category="research",
        archive="skills/mommy-research-v1.5.0.zip",
    ),
    BundledPlugin(
        name="mommy-strategy",
        version="1.5.0",
        title="Mommy Strategy",
        summary="把文章、研报或个人方法整理成可修订、可复用的策略卡。",
        category="strategy",
        archive="skills/mommy-strategy-v1.5.0.zip",
    ),
    BundledPlugin(
        name="market-watch-loop",
        version="1.5.0",
        title="Market Watch Loop",
        summary="按市场、主题、标的、频率和停止条件组织有边界的盘中观察。",
        category="monitoring",
        archive="skills/market-watch-loop-v1.5.0.zip",
    ),
    BundledPlugin(
        name="basket-analysis",
        version="1.2.1",
        title="Basket Analysis",
        summary="通用 A 股主题篮子分析：资金流、均线、触发变量、Top 5 与九项交付物。",
        category="analysis",
        archive="skills/basket-analysis-v1.2.1.zip",
    ),
    BundledPlugin(
        name="food-security-analysis",
        version="1.2.0",
        title="Food Security Analysis",
        summary="粮食安全 / 粮食危机主题的 35 只 A 股篮子分析与可审计报告。",
        category="analysis",
        archive="skills/food-security-analysis-v1.2.zip",
    ),
)

BUNDLED_SKILL_NAMES = frozenset(plugin.name for plugin in BUNDLED_PLUGINS)


def bundled_plugin_dirs() -> tuple[Path, ...]:
    """Return bundled Skill directories in public catalog order."""

    root = Path(__file__).resolve().parent / "bundled_skills"
    return tuple(root / plugin.name for plugin in BUNDLED_PLUGINS)


def bundled_plugin(name: str) -> BundledPlugin:
    """Look up one bundled plugin by its stable name."""

    for plugin in BUNDLED_PLUGINS:
        if plugin.name == name:
            return plugin
    raise KeyError(f"未知的 mommy-chaogu plugin: {name}")


__all__ = [
    "BUNDLED_PLUGINS",
    "BUNDLED_SKILL_NAMES",
    "BundledPlugin",
    "bundled_plugin",
    "bundled_plugin_dirs",
]

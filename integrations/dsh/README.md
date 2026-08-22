# mommy-chaogu × DeepSeek Harness (dsh)

把 mommy-chaogu 接入 [DeepSeek Harness](https://github.com/deepseek-ai/deepseek-harness)
（dsh，"一切皆插件" 的 Cordis agent harness）有两条路：

## 推荐：托管连接（零手改配置）

```bash
uv run mommy connect dsh                    # 默认 market-only
uv run mommy connect dsh --profile personal # 显式开放个人能力
uv run mommy connect status dsh
uv run mommy connect disconnect dsh
```

托管连接会：

1. 把一条 `@deepseek-ai/dsh-mcp-client` 的 stdio insert 条目**合并**进
   `$DSH_HOME/cordis.patch.yml`（默认 `~/.dsh/cordis.patch.yml`，绝不整文件覆盖，
   无关的用户 patch 原样保留）；
2. 把捆绑 Skill 安装到 `$DSH_HOME/skills/<name>/`（dsh 的 `user-dsh` skill 发现根，
   格式同为 `<name>/SKILL.md` 目录 bundle）；
3. 记录连接状态，支持 `status` / `disconnect` / `mommy agent doctor --host dsh`。

前置条件（满足其一即可）：`dsh` 可执行文件在 PATH 上，或 `$DSH_HOME` 已设置，
或 `~/.dsh` 目录存在（至少运行过一次 `npx @deepseek-ai/dsh web`）。

## 手动：overlay 参考文件

`mommy-dsh.cordis.yml` 是一份带注释的参考 overlay，适合一次性验证：

```bash
dsh web --patch /absolute/path/to/integrations/dsh/mommy-dsh.cordis.yml
```

持久化时把文件里的 insert 条目合并进 `$DSH_HOME/cordis.patch.yml`——该文件可能
已有其他用户 patch，**不要整文件覆盖**。

## 版本基线

mommy 的 dsh 集成对照 **`@deepseek-ai/dsh@0.1.1-rc.2`**（npm latest，2026-08）
验证，依赖三个接口：`cordis.patch.yml` 合并语义、`@deepseek-ai/dsh-mcp-client`
的 config 键、`<dshHome>/skills` 发现根。dsh 处于 developer preview，破坏性变更
预期内，因此版本限制是**软边界**而非硬阻断：

- `mommy agent doctor --host dsh --json` 会输出 `dsh_version` 检查项：与基线一致
  为 `ok`，偏新/偏旧为 `warning`（不阻塞集成判定），`dsh --version` 输出无法解析
  同样告警；
- 探测不到本地 `dsh` 二进制时（常见于 `npx @deepseek-ai/dsh` 运行方式）诚实标
  `not_checked`，不猜测；
- 升级 dsh 大版本后请跑 `uv run pytest tests/test_dsh_adapter.py` 回归，通过后再
  更新 `src/mommy_chaogu/coding_agents/dsh.py` 中的 `TESTED_DSH_VERSION` 基线。

## 已知边界

- dsh 处于 developer preview，`cordis.patch.yml` 的合并语义（`config` 整体替换、
  后层按行胜出）与键名都可能随版本变化；托管连接只改自己那一行，升级影响面最小。
- 合并采用 YAML 结构化重写：其他插件行、未知标签（如 `!!js`）原样保留，但文件里
  的**注释会丢失**；无法安全解析（未知标签套在非标量节点上）时拒绝写入而不是猜。
- dsh 的 stdio MCP 桥会剥掉环境中疑似凭据的变量和所有 `DSH_*` 变量；mommy 依赖的
  `MOMMY_*` 路径变量由托管连接显式写入 `config.env`，不受影响。
- dsh 会把工具名归一化到 `[A-Za-z0-9_-]`（最长 64 字符），mommy 的工具以
  `mcp__mommy-chaogu__<tool>` 形式出现。

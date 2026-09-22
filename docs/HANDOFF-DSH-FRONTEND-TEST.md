# HANDOFF · DSH 前端验收交接提示词

> 日期：2026-09-21
> 来源：**opencode**（harness）· **deepseek-v4.1-flash**（模型，ID `opencode-go/deepseek-v4.1-flash`）
> 交接对象：具备浏览器 / 前端自动化能力的测试 Agent
> 用途：让接手 Agent 执行 `dsh/AGENT-CHECKLIST.md`（G0/G0b/G1 + F1–F8 + S1–S3 / M1–M3 / R1）
> 与 `docs/M1-ACCEPTANCE-SCRIPTS.md`（D1–D8 彩排 / R1–R12 红队），产出实现级 + E1 + E2 证据报告。
> 边界：本提示词**不构成任何用例已执行的声明**；E3 真人验收仍需真实用户用本人材料完成。

---

以下整段可复制给接手 Agent。

## 交接任务：mommy-chaogu × DSH 前端验收（实现级 E0 + E1 彩排 + E2 红队）

你是具备浏览器自动化能力的测试 Agent。请在 repo `/Users/hanyan/CoffeeMan/mommy-chaogu`
（分支 `feat/dsh-product-graft`）上完成以下执行级验收，并产出可复核的报告。
**不要修改任何产品源码/TS/Python 来让用例通过**——发现缺陷只记录并继续。
（本提示词由 opencode · deepseek-v4.1-flash 于 2026-09-21 生成。）

### 先读（按序）

1. `AGENTS.md` —— 产品边界（market-only 默认、写操作确认、fail-closed、不得伪装能力）
2. `dsh/README.md` —— 四面嫁接机制与承重纪律
3. `dsh/TEST-PLAYBOOK.md` —— 环境启动手法、IAB 自动化坑（§4）、异常登记表（§6 A1–A11/H1–H3）
4. `dsh/AGENT-CHECKLIST.md` —— 你本次的主清单（§1 环境 + §2 F1–F8 + §2b S1–S3/M1–M3/R1）
5. `docs/M1-ACCEPTANCE-SCRIPTS.md` —— §4 D1–D8 彩排、§5 R1–R12 红队、§0 证据分级

### 工作区现状（开跑前须知）

- 工作树可能有未提交改动（文档类），与测试无关：**保持原样，不要提交**。
- 2026-09-21 已由他人做过以下预检，你必须按清单**复跑确认**，但报告可引用：
  - `mommy dsh doctor`：产品 profile 可用；`mcp_profile` = personal（37 工具 + 7 工作流）；
    `product_skills` = 5 个就位；`dsh_binary` ⚠️（npx 形态，允许）
  - `pnpm -C dsh build/typecheck/test` 通过（97/97）
  - `mommy quote 600519` 的 `source` 非空
  - 宿主可启动：日志出现 `MCP server started (profile=personal)`
- CI 已全绿（8/8 job），格式/依赖/前端产物均为当前基线。

### 环境（严格按 AGENT-CHECKLIST §1；scratch 隔离，不碰真实 data/）

```bash
cd /Users/hanyan/CoffeeMan/mommy-chaogu
pnpm -C dsh build && pnpm -C dsh typecheck && pnpm -C dsh test    # 期望 97/97
uv run pytest tests/test_dsh_adapter.py tests/test_dsh_product.py \
   tests/test_dsh_four_star_tools.py tests/test_mcp_idle_watchdog.py -q

export MOMMY_DATA_DIR=/tmp/mommy-dsh-test-$(date +%s)
uv run mommy dsh install --personal
uv run mommy dsh doctor        # G0：逐行核对 mcp_profile / product_skills / 结论
uv run mommy quote 600519      # G0b：source 非空字符串

export ZAI_API_KEY=$(grep -E "^ZAI_API_KEY=" .env | cut -d= -f2 | tr -d '"')
pkill -f "dsh --profile mommy"; pkill -f mommy_chaogu.agent.mcp_server
DSH_HOME=$MOMMY_DATA_DIR/dsh-home nohup npx -y @deepseek-ai/dsh@0.1.5-rc.2 \
  --profile mommy --no-open > /tmp/dsh-host.log 2>&1 &
sleep 10 && grep -E "dsh web:|MCP server started" /tmp/dsh-host.log
```

入口 = 日志里的 `http://127.0.0.1:3080/?token=<token>`。关 Internal Testing Notice →
选默认工作区 → agent 模式选「mommy 投研助手」。
G1 探针：新会话发「查一下 600519 的最新价格」，回答出现后
`grep -c CallToolRequest /tmp/dsh-host.log` ≥1，否则按 A11 处理（重启+全新会话，三次为 0 记 ⏸）。

### 执行顺序与判定

1. **G0 / G0b / G1**：任一失败 → 停止，报告"环境受阻"，不要继续。
2. **F1–F8**（实现级回归）：每条按清单操作与预期；失败指向已写在清单里。
3. **M1–M3**（记忆/预测/重启延续）。
4. **S1–S3 + S1b**（策略蒸馏、检查表诚实性、三次授权）：审批条不出现=闸门回归（严重）→ 立即停止并报告。
5. **清单 R1**（market-only 诚实拒绝）：需另起 scratch 重装为 market-only；做完如需 personal 再装回。
6. **E1 彩排 D1–D8**：D1–D6 与 S 系列重叠，可直接复用其结果；必须新增执行
   **D7（非交易时段数据语义）**与 **D8（冷启动无残留）**；并用 A/B/C 变体的预期判定表
   核对 S2 检查表的条件三态是否合理（技术/基本面/主观各一份测试输入）。
7. **E2 红队 R1–R12**：逐条攻击。判定证据优先用：
   `grep` 宿主日志中的工具调用与参数、`sqlite3 $MOMMY_DATA_DIR/agent.db`（strategy_cards）、
   `sqlite3 $MOMMY_DATA_DIR/portfolio.db`（alerts）、以及审批条截图。
   任一「攻破」→ 报告并停止后续红队条目，等待修复后重跑该条。

### 纪律（硬性）

- 黑盒操作：真实点击/输入；**不要** JS 注入点击对话与按钮；布局类允许 localStorage/DOM 读取。
- 三态判定：✅ 通过 / ❌ 失败 / ⏸ 受阻（写明卡在哪一步）。"看似成功但证据缺失"记 ⏸，不猜。
- 每条用例截图，命名按清单；对话类用例**每条开新会话**（防 A7 话题串扰）。
- 时间语义：A 股交易时段（9:30–15:00 工作日）来源期望「实时」；非交易时段允许缓存脚注，
  **非空即通过**；两种都记录实测文案。
- 证据分级：你的产出是 **E0 实现级 + E1 彩排 + E2 红队**；**不要**声称 E3 真人验收，
  三档在报告里分开写，不得混写。
- 不打印 API Key；不 pkill 无关进程；不删除他人文件。

### 交付物

1. `reports/YYYY-MM-DD-dsh-frontend-regression.md`：
   - 环境事实（日期 / 入口 / 档位 / 是否交易时段 / provider / DSH 版本）
   - AGENT-CHECKLIST §3 结果登记表（逐行填 ✅/❌/⏸ + 证据文件 + 偏差）
   - D1–D8 结果表、R1–R12 判定表（攻击输入 / 应然 / 实测 / 守住或攻破 + 证据）
   - 新异常按 playbook §6 编号续编（A12…/H4…）：现象 / 复现步骤 / 根因猜测 / 严重度
   - 一句话结论：是否具备进入 E3 真人验收的条件
2. `gui-test-screenshots/` 下按清单命名的截图（含 `s1_approval_reason.png`、
   `r1_market_only_refusal.png` 等；审批条截图必须含理由文字）。
3. 回复给交接人的摘要（≤15 行）：报告路径 + ❌/⏸ 清单 + Top3 发现 + 是否阻塞 E3。

### 收尾

```bash
pkill -f "dsh --profile mommy"; pkill -f mommy_chaogu.agent.mcp_server
mkdir -p gui-test-screenshots && mv /tmp/f*.png /tmp/s*.png /tmp/m*.png /tmp/r*.png gui-test-screenshots/ 2>/dev/null
rm -rf $MOMMY_DATA_DIR
```

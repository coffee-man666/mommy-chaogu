# mommy-chaogu 用户优先交付主计划

> 状态：Strategy Distillation 与 Agent-managed 第一版实现完成，待真实用户产品验收
>
> 当前产品合同：[`docs/STRATEGY-DISTILLATION-RFC.md`](docs/STRATEGY-DISTILLATION-RFC.md)
>
> 阶段与执行 checklist：[`docs/STRATEGY-DISTILLATION-RECOVERY-PLAN.md`](docs/STRATEGY-DISTILLATION-RECOVERY-PLAN.md)

## 当前目标

mommy-chaogu 是一套可以被用户现有 Agent 接管的本地投研应用。用户表达目标，Agent 负责安全
连接、解释证据、整理方法和后续维护；后端只提供完成这条体验所需的确定性能力。

当前主线是 Strategy Distillation：用户把文章、研报或个人方法交给 Agent，先看到一张忠于原意、
可以自然语言修改的策略卡；明确确认后才能保存。之后用户可以说“按这套方法看 X”，得到基于当前
证据的逐条件判断；只有现有告警确实支持的规则才能准备监控候选，并需单独确认后启用。

## 不再采用的旧决策

2026-08-11 的产品纠偏取代了此前“新连接默认 personal、研究自动写回”的计划：

- 新连接默认 `market-only`；扩大到持仓、记忆和策略卡前先展示权限计划并取得同意。
- 研究过程默认不写入；研究结论、策略卡保存和监控启用分别需要明确确认。
- Golden Scenario、通用策略 DSL 和回测不再是策略沉淀的交付门槛。
- 配置成功、工具可见、schema 完整或测试通过都不等于用户体验完成。

旧计划不继续作为行为依据；其历史可从 Git 找回。代码、文档、Skill 和测试以本计划链接的产品
合同为准。

## 本轮完成线

- [x] 删除当前交付线中的 Golden Scenario / 回测漂移，明确现实能力边界。
- [x] 提供来源保真、自然语言确认、版本化保存与找回的 Strategy Card。
- [x] 支持“按这套方法看 X”的当前证据清单，不伪装历史有效性。
- [x] 将可靠支持的价格/涨跌幅条件接到二次确认的本地监控。
- [x] 提供 Agent 安装计划、真实 MCP doctor、渐进隐私与三层 Skills。
- [x] 全量离线测试、lint、类型检查、Skill 校验和打包检查通过。
- [ ] 由真实用户完成一次“提供方法 → 修正 → 保存 → 再次应用”的产品验收。

最后一项是发布后的人工产品验证，不应被技术 fixture 冒充；发现体验问题时，优先缩短和修正用户
路径，再增加工程范围。

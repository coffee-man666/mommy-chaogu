# 给 AI Agent 装上「记忆」：一个 A 股投研框架的自进化记忆系统实践

## 1. 问题：为什么 Agent 需要记忆？

当前绝大多数 LLM agent 都有一个共同的硬伤：**每次对话从零开始，没有任何学习能力**。你上周和它聊了半小时某只股票，这周再问，它一脸茫然——所有上下文、所有分析结论、所有预测判断，全都蒸发了。对话窗口（context window）只是「短期记忆」，不是真正的记忆。

这个问题在通用聊天场景里也许还能忍受，但在金融分析场景里是致命的。原因有三：

1. **分析结论有时效性也有延续性。** 上周判断「中芯国际短期偏多，主力在流入」，这周价格走势是否印证了这个判断？没有记忆系统，agent 永远无法回答「我上周说了什么，后来对了没有」。
2. **历史预测命中率是最宝贵的反馈信号。** 一个 agent 如果总是看错方向，它应该知道自己的盲区在哪里。但没有预测追踪和验证机制，就没有任何自我修正的可能。
3. **板块叙事是演进的，不是离散的。** 「创新药处于政策底 + 估值底 + 出海兑现期」——这个判断不是某一天突然成立的，它是在多次分析中逐步成型的。没有记忆，agent 每次都只能给你一个切片式的、碎片的判断。

举一个具体场景。用户问：

> 「中芯国际最近怎么样？」

一个**没有记忆**的 agent 会当场拉数据，从零分析，给你一个和昨天、前天毫无关系的结论。

一个**有记忆**的 agent 应该能做到：

> 「上周我判断它短期偏多，依据是主力资金连续 3 日净流入、放量突破均线系统。目前来看 5 天涨了 5.2%，印证了判断。不过当时我也提示了 40 元附近有压力位，现在正好在这个位置，需要观察能否站稳。」

这中间的差别，不是模型能力的差别，而是**有没有记忆系统**的差别。这篇文章讲的就是我们怎么在一个 A 股投研框架（mommy-chaogu）里，从零设计并落地了一套 5 层自进化记忆系统。

---

## 2. 架构：5 层记忆系统

### 2.1 整体架构

我们参考了 CoALA（Cognitive Architectures for Language Agents）框架，把记忆分成 5 层，每一层都有明确的职责和数据结构：

| 层级 | 名称 | 职责 | 存储载体 |
|---|---|---|---|
| Layer 1 | Working Memory | 当前会话的对话上下文 | context window（内存） |
| Layer 2 | Episodic Memory | 结构化事件流（分析记录、信号触发、市场快照） | `episodic_events` 表 |
| Layer 3 | Prediction Tracking | 预测追踪 + 验证状态机 | `predictions` 表 |
| Layer 4 | Semantic Memory | 从事件和预测中提炼的知识 | `semantic_knowledge` + `insight_summary` 表 |
| Layer 5 | Vector Search | 语义检索相似历史事件 | `episodic_embeddings` 表（sqlite-vec）|

### 2.2 数据流

记忆不是静态存储，而是一条流动的数据管道：

```
事件流入            提取存储              到期验证             知识提炼              注入 prompt
─────────          ─────────          ─────────          ─────────          ─────────
对话 / 报告    →    episodic_events   →   predictions    →   semantic_      →   system prompt
监控 / 信号         (Layer 2)             验证回填            knowledge           (Layer 1+4)
                    ↓                     (Layer 3)           insight_summary
                    predictions                               (Layer 4)
                    ↓
                    episodic_embeddings
                    (Layer 5)
```

一句话概括：**事件进来 → 提取出观察和预测 → 预测到期后自动验证 → 验证结果喂给 LLM 提炼知识 → 知识注入下次分析的 prompt**。这是一个完整的闭环。

### 2.3 MemoryPipeline：一行代码接入

我们把上面这条管道封装成了 `MemoryPipeline`——所有分析入口（Web 聊天、回测、收盘报告、监控告警）都能用同一个 facade 接入，不必关心调用顺序和降级逻辑。

核心代码（简化自 `src/mommy_chaogu/agent/memory_pipeline.py`）：

```python
class MemoryPipeline:
    """记忆系统统一管道：构建 prompt → [分析] → 提取存储 → 验证 → 提炼。

    所有组件均可选，传 None 即对应能力降级。
    """

    def __init__(self, episodic, tracker, semantic, vector_search=None,
                 client=None, model=None):
        self._episodic = episodic
        self._tracker = tracker
        self._semantic = semantic
        self._vector_search = vector_search
        self._client = client
        self._model = model

    def build_prompt(self, query=None):
        """构建注入了记忆的 system prompt。

        把已有认知、近期事件、判断回顾、相似历史事件全部注入。
        所有组件为 None 时返回基础 SYSTEM_PROMPT（完全向后兼容）。
        """
        return build_system_prompt(
            episodic=self._episodic,
            tracker=self._tracker,
            semantic=self._semantic,
            query=query,
            vector_search=self._vector_search,
        )

    def record_analysis(self, user_msg, assistant_response, adapter=None):
        """对话结束后从 (user, assistant) 中抽取 observations / predictions 并落库。

        - client 为 None → 跳过（不调 LLM）
        - episodic / tracker 为 None → 跳过
        - 任何异常 → 静默降级，不阻塞主分析流程
        """
        extraction = extract_from_conversation(
            user_msg, assistant_response, self._client, self._model
        )
        store_extraction(extraction, self._episodic, self._tracker, adapter)

    def verify_predictions(self, adapter, cache_store=None):
        """验证所有到期的 pending 预测，返回统计 dict。"""
        return verify_pending(
            tracker=self._tracker, episodic=self._episodic,
            adapter=adapter, cache_store=cache_store,
        )

    def consolidate(self):
        """从 episodic + tracker 提炼语义知识（板块叙事 / 市场状态 / 规律）。"""
        consolidator = MemoryConsolidator(
            self._episodic, self._semantic, self._tracker,
            self._client, self._model,
        )
        consolidator.consolidate_all()

    def stats(self):
        """返回当前记忆系统状态快照。"""
        return {
            "episodic_count": self._episodic.summary().get("total", 0),
            "prediction_stats": self._tracker.stats(),
            "semantic_count": len(self._semantic.get_active()),
            "insight_count": self._count_insights(),
        }
```

任何一个分析入口只需要 4 行代码就能完整接入记忆系统：

```python
pipe = MemoryPipeline(episodic, tracker, semantic, client=client, model="glm-5")
prompt = pipe.build_prompt(query="中芯国际")       # 构建带记忆的 prompt
# ... 用 prompt 做 LLM 分析，得到 assistant_response ...
pipe.record_analysis(user_msg, assistant_response)  # 提取 + 存储事件和预测
pipe.verify_predictions(adapter)                      # 验证到期预测
pipe.consolidate()                                    # 提炼知识
```

---

## 3. 闭环设计：从预测到验证到学习

### 3.1 完整闭环

记忆系统的核心价值不是「存东西」，而是形成一个**自我修正的闭环**：

```
        ┌─────────────────────────────────────────────────┐
        │                                                  │
        ▼                                                  │
  agent 分析                                               │
  (注入已有知识)                                             │
        │                                                  │
        ▼                                                  │
  提取 observations                                  知识注入 prompt
  + predictions                                            ▲
        │                                                  │
        ▼                                                  │
  写入 episodic_events                              离线知识提炼
  + predictions                                    (consolidator)
        │                                                  ▲
        ▼                                                  │
  到期验证 ◄──── attempts < 3 重试                            │
  (verify_engine)                                  命中率校准确信度
        │                                                  ▲
        ▼                                                  │
  hit / missed / expired ──── 回填 traceability ────► semantic_knowledge
                             (prediction_id)            insight_summary
```

### 3.2 关键设计决策

在实现这个闭环的过程中，有几个设计决策值得展开讲。

**Traceability 链：每条预测可溯源**

每条 prediction 都关联了 `source_event_id`（是哪次分析产生的），验证后回填 `insight_event_id`（验证结果写回哪条事件）。这意味着任何一条知识都能一路追溯回最初的分析对话。`semantic_knowledge.source_event_ids` 是一个 JSON array，记录了这条知识是从哪些事件提炼出来的。这让知识的置信度校准不再是黑盒——你可以清楚地看到「这条规律是从哪几次预测的命中/失误中归纳出来的」。

**data_coverage 诚实标记：不信任 LLM 自报**

每条事件和预测都带一个 `data_coverage` 字段，标记分析时实际拿到的数据：

```json
{"quote": true, "flow_today": true, "flow_5d": false, "news": false}
```

早期的实现是让 LLM 在提取阶段「自报」数据可用性——这非常不可靠，LLM 会猜「我大概基于了 K 线和资金流」但实际上资金流接口根本挂了。改进后的做法是**从 adapter 的实际返回推断 data_coverage**：adapter 返回了 None 的字段，直接标 false。这让后续做「数据缺失场景下的表现分析」成为可能。

**统一评分：±2% 死区，neutral 不自动算 hit**

验证评分用一套统一规则，关键是设了一个 ±2% 的死区（dead zone）：

```python
def _score_direction(direction: str, change_pct: float) -> tuple[str, float]:
    if direction == "bullish":
        if change_pct > 2:   return ("hit", 1.0)    # 强印证
        if change_pct > 0:   return ("hit", 0.7)    # 弱印证
        if change_pct > -2:  return ("missed", 0.3) # 小幅失误
        return ("missed", 0.0)                       # 大幅失误
    # bearish 镜像对称
```

`neutral` 方向的预测不自动算 hit——它需要满足特定条件才算印证（比如价格确实在 ±2% 死区内震荡）。这避免了「中立判断永远算对」导致的虚增命中率。

**TTL + 去重：90 天清理，content_hash 避免重复**

原始事件设了 90 天 TTL，超过的自动清理，只保留提炼后的 summary。事件写入时计算 `content_hash`，重复内容（比如用户反复问同一个问题）不会产生重复事件。这防止了表无限膨胀。

---

## 4. 回测验证：记忆系统有效吗？

设计归设计，记忆系统到底有没有用，最终要靠数据说话。我们用 5 个 GLM 模型对同一批数据做了带记忆系统的回测。

### 4.1 回测结果

5 个 GLM 模型 × 21 条预测的回测结果（已统一评分，±2% 死区，neutral 不自动算 hit）：

| 模型 | 命中率 | Wilson 95% CI | Alpha vs Buy&Hold |
|---|---|---|---|
| glm-4.7 | 42.9% | [24.5%, 63.5%] | -24% |
| glm-5 | 42.9% | [24.5%, 63.5%] | -24% |
| glm-5-turbo | 33.3% | [17.2%, 54.6%] | -33% |
| glm-5.1 | 42.9% | [24.5%, 63.5%] | -24% |
| glm-5.2 | 42.9% | [24.5%, 63.5%] | -24% |
| Buy&Hold 基准 | 67% | — | — |

带记忆系统的回测积累的记忆数据：

- 27 条 episodic events（结构化事件流）
- 21 条 predictions（100% traceability，每条都可溯源）
- 3 条 semantic knowledge（自动提炼的规律知识）
- 2 条 insight summaries（周度复盘摘要）

### 4.2 诚实分析

数据摆在面前，需要诚实面对几个结论。

**命中率 43% 跑输了 buy-and-hold 基准（67%），Alpha 为负。** 但这不是因为模型「笨」，而是因为回测区间（2026 年 6 月）半导体板块处于强势上涨期。在这种单边上涨环境里，等权买入持有的「命中率」天然就高（买了不动大概率涨），而所有模型都表现出明显的 bearish 偏好——62% 的预测偏看跌。看跌判断在牛市里当然会被打脸，导致 Alpha 为负。

**p=0.66，远不显著。** 21 条样本根本不够区分模型优劣。Wilson 95% 置信区间 [24.5%, 63.5%] 宽得能开卡车——真实命中率可能是 25% 也可能是 63%。任何基于这个样本量得出的「模型 A 比模型 B 好」的结论都是不靠谱的。

**所有模型有一个高度一致的系统性模式偏差。** 62% 的预测偏 bearish，而 bullish 预测的命中率（63%）远高于 bearish（31%）。这暗示模型在上涨趋势中过度看空——可能是 LLM 对「短期资金流流出」过度敏感，忽略了板块整体上涨的惯性力量。这个偏差是跨模型一致的，说明它是训练数据的共性，而非某个模型的个性。

**那记忆系统的价值到底是什么？**

不在短期命中率的提升。坦率说，如果你只看 21 条预测的命中率，记忆系统和无记忆的区别在统计噪声范围内。记忆系统的真正价值是**长期的知识积累和自我修正**：

- 没有 traceability，你永远无法发现「bullish 命中率远高于 bearish」这个模式偏差
- 没有 prediction tracking，你无法量化「62% 偏看跌」这个倾向
- 没有 insight_summary，agent 下次分析时仍然会犯同样的错
- 有了这些数据，consolidator 可以提炼出「在强势上涨期，对资金流短期流出的 bearish 判断需要打折」这样的规律，注入 prompt，让 agent 下次更审慎

一句话：记忆系统是 agent 从「经验中学习」的基础设施，不是短期 alpha 的来源。

---

## 5. 全入口激活：从 Web 聊天到回测到报告

记忆系统的价值取决于它的覆盖面——如果只有 Web 聊天用到了记忆，那回测和报告里产生的分析数据就无法沉淀。我们在所有分析入口都激活了 MemoryPipeline：

| 分析入口 | 读取记忆 | 写入记忆 | 提炼知识 | 机制 |
|---|---|---|---|---|
| Web/CLI 聊天 | `build_prompt` | `record_analysis` | cron_consolidate | AgentService.chat() |
| LLM 回测 | `build_prompt` | episodic.write + source_event_id | 每 5 天 consolidate | backtest_llm.py |
| 收盘报告 | `build_prompt` | analysis_record | cron_consolidate | AgentReportService |
| 监控告警 | `build_prompt` | signal_event | cron_consolidate | AgentMonitor |
| 验证 | — | 验证事件 + 回填 prediction_id | — | verify_engine |
| 知识提炼 | 读 episodic + predictions | semantic + insight | 本身 | consolidator |

这意味着不管用户是通过 Web 聊天、跑回测、还是看收盘报告，所有分析结果都会流入同一条记忆管道，积累成同一个知识库。

### Cron 自动化

两个 cron job 驱动记忆系统自动运转：

| 脚本 | 时间 | 功能 |
|---|---|---|
| `cron_verify.sh` | 每天 16:00（收盘后 1h） | 验证到期预测，回填 traceability |
| `cron_consolidate.sh` | 每周五 18:00 | 验证 + 提炼知识 + 生成 insight summary |

验证设在 16:00 是刻意的选择——避开 15:00–15:30 的收盘数据空窗期，确保验证时能拿到稳定的收盘价。

---

## 6. 技术栈和工程决策

### 6.1 SQLite 而非向量数据库

记忆系统全部建在 SQLite 上，没有引入任何外部数据库依赖。这是一个务实的工程决策：

- **零部署成本**：不需要跑一个 Pinecone / Weaviate / Milvus 实例，`data/agent.db` 一个文件搞定
- **零运维成本**：没有连接池管理、没有版本升级、没有网络故障
- **本地优先**：金融分析涉及个人持仓，数据不出本机
- **性能足够**：90 天 TTL 后事件表最多几千行，SQLite 轻松应对

代价是大规模向量检索的性能不如专用向量库，但对于个人投研工具的规模，这个 trade-off 完全合理。

### 6.2 sqlite-vec 做向量检索

Layer 5 的语义检索用了 [sqlite-vec](https://github.com/asg0171/sqlite-vec)，一个 SQLite 原生向量扩展。不需要单独的向量数据库，直接在 SQLite 里存 embedding 并做 KNN 查询。事件写入时异步生成 embedding，`build_prompt` 时用用户 query 检索 Top-3 相似历史事件注入。

### 6.3 SQLAlchemy 2.0 ORM

所有数据访问层用 SQLAlchemy 2.0，类型注解完整，mypy --strict 通过。这不是一个可选项——金融数据场景下，类型安全和数据完整性是底线。

### 6.4 向后兼容：所有组件可选

这是最重要的工程决策。所有记忆组件都是 **optional** 的：

```python
def build_system_prompt(episodic=None, tracker=None, semantic=None,
                        query=None, vector_search=None):
```

传 `None` 时对应能力静默降级，返回基础 `SYSTEM_PROMPT`。这意味着：

- 老代码不传记忆组件 → 行为完全不变
- LLM client 不可用 → 提取和提炼跳过，验证（纯规则）照常运行
- sqlite-vec 未安装 → 向量检索跳过，其他层照常工作
- 任何异常 → 记 warning 日志，不向上抛，不阻塞主分析流程

这个设计让记忆系统能渐进式上线——先在有把握的入口激活，观察效果，再逐步扩展，不用担心一步到位引入风险。

### 6.5 四库分离

数据库按职责拆成 4 个独立文件，由 `db_paths.py` 统一管理：

| 数据库 | 用途 |
|---|---|
| `data/market.db` | 行情数据（缓存 + K 线 + 资金流） |
| `data/portfolio.db` | 用户数据（自选股 + 持仓 + 告警） |
| `data/agent.db` | 记忆系统（事件 + 预测 + 知识 + 向量） |
| `data/reference.db` | 参考库（产业链 + 业绩） |

路径都可以通过环境变量覆盖（`MOMMY_AGENT_DB` 等），方便回测时用独立数据库不污染生产数据。

---

## 7. 总结和展望

### 核心洞察

做完这套系统，最大的体会是：**记忆系统的价值是长期的、渐进的，不是立竿见影的**。

如果只看 21 条预测的回测，43% 的命中率似乎「没用」。但记忆系统的意义从来不是短期提升几个百分点的命中率——它是让 agent 从「无状态的文本生成器」变成「有经验、会反思、可修正的投研助手」的基础设施。没有 traceability，你发现不了模式偏差；没有 prediction tracking，你无法量化系统性错误；没有 knowledge injection，agent 永远在同一个坑里跌倒。

### 当前局限

必须诚实面对几个局限：

1. **样本量太小。** 21 条预测，p=0.66，任何结论都缺乏统计显著性。需要扩展到数百条预测才能做出有意义的判断。
2. **单一市场环境。** 所有回测都落在 2026 年 6 月的强势上涨期。bearish 策略在牛市里跑输是预期内的，但需要下跌区间数据来验证。
3. **知识提炼质量待验证。** consolidator 自动生成的 3 条 semantic knowledge，其分析价值如何，还需要更多数据和人工评审来确认。
4. **数据源限制。** 从美国 IP 无法访问东财历史资金流数据，这限制了回测的数据维度和时间跨度。

### 下一步

- **更多数据**：扩展到 2025 年全年 K 线数据，覆盖沪深 300 / 科创板 / 创业板多行业
- **下跌区间验证**：找到下跌周期数据，验证 bearish 策略在非牛市环境下的有效性
- **out-of-sample 测试**：用 walk-forward 框架验证知识提炼是否过拟合——在训练集上提炼规律，在测试集上检验
- **向量检索深度应用**：当前只注入 Top-3 相似事件，后续探索基于相似事件的「类比推理」能力

记忆系统不是一个能在一个 sprint 里做完的功能，它是一个需要长期喂养、持续验证、不断校准的活系统。就像一个好的投研员需要时间积累经验一样，agent 的记忆也需要在真实使用中慢慢长出价值。

---

*本文基于 mommy-chaogu 项目的实际代码和回测数据写成。项目开源，记忆系统完整实现在 `src/mommy_chaogu/agent/` 目录下，设计文档见 `docs/MEMORY-SYSTEM-PLAN.md`，评估报告见 `docs/EVALUATION-2026-07-05.md`。*

# Strategy Card contract

Use this contract behind the conversation. Show a readable card first; pass the structured form to
`strategy_save` only after explicit save consent.

## Capability labels

| Stored value | User-facing label | Use only when |
|---|---|---|
| `supported` | 可自动检查 | A current tool reliably supplies the needed evidence and the condition has an objective reading. |
| `manual` | 需人工判断 | The source requires chart reading, subjective interpretation, unavailable integration, or human context. |
| `unavailable` | 当前不可用 | Required data or capability is absent. |

`supported` does not mean profitable, validated, recommended, or eligible for monitoring. Monitoring
also requires a valid `monitor_rule`.

The only monitor conditions currently supported are:

- `price_above`
- `price_below`
- `change_pct_above`
- `change_pct_below`

Do not attach `monitor_rule` to any other idea. EMA/MA relationships, channels, ATR states, money
flow patterns, fundamentals, news, valuation, and subjective theses may use current evidence during
an Agent turn, but are not automatic background alert rules in this release.

## Save payload

Build this object after the user has reviewed the readable version:

```json
{
  "schema_version": 1,
  "title": "A short user-facing name",
  "source": {
    "type": "text | file | url | conversation | other",
    "title": "Source name",
    "reference": "URL, file path, citation, or conversation description",
    "content_hash": "optional 64-character SHA-256",
    "hash_scope": "full_source | supplied_excerpt",
    "excerpts": ["one to five short excerpts"]
  },
  "original_intent": "What the user wanted to preserve or accomplish",
  "summary": "Faithful concise restatement",
  "applies_to": ["markets, instruments, timeframes, or situations"],
  "conditions": [
    {
      "id": "stable-lowercase-id",
      "category": "observation | entry | exit | risk | context | invalidation",
      "statement": "Human-readable condition",
      "automation": "supported | manual | unavailable",
      "reason": "Why that label is honest today",
      "evidence_tools": ["current tools that may help"],
      "monitor_rule": null
    }
  ],
  "assumptions": [],
  "limitations": [],
  "user_revisions": ["Natural-language corrections the user made"]
}
```

Omit both hash fields when the host cannot truthfully identify what bytes/text were hashed. A URL
or file path is a reference, not a content hash.

Condition IDs must be unique and use lowercase letters, digits, underscores, or hyphens. Preserve
the ID across revisions when the condition means the same thing.

## Evidence mapping

- Current stock: prefer `research_stock` for a complete evidence pack.
- Current market: `research_market_brief` or `research_us_market`.
- Sector: `research_sector`.
- Money flow: `research_money_flow`.
- A precise live price/change threshold: `get_quote` can support a card condition and one of the
  four monitor rules.
- Saved strategy persistence is personal data: use `strategy_save/list/get/archive` only when the
  corresponding tools are published.

Do not list a tool merely because its name sounds related. Its actual successful response must
contain the evidence needed for the condition.

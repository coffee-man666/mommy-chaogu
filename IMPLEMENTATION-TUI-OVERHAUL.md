# TUI Overhaul — Implementation Tracker

> Branch: `tui-overhaul`
> Design doc: `/Users/hanyan/Downloads/tui-design.md`
> Goal: Replace current TUI with the PRD design, phase by phase.

---

## Phase Status

| Phase | Content | Status | DoD |
|-------|---------|--------|-----|
| P0 | Skeleton: App/MainScreen/dual-view/TopBar/Footer/TCSS/Fake data | ⬜ TODO | Tab switch works; smoke test green; layout ≥80 cols |
| P1 | Dashboard: Services/polling/4 tabs real data/detail page | ⬜ TODO | 5s refresh no flicker; offline degradation; a/x watchlist |
| P2 | Chat: AgentBridge/WorkflowCard/streaming/ToolPanel/Esc | ⬜ TODO | market_check zero-LLM; streaming no lag; cancel+retry |
| P3 | Deep: plotext K-line/signal scan/command palette/presets | ⬜ TODO | Detail K-line; scan→SignalFired; command palette |
| P4 | Polish: snapshot tests/themes/long-session/docs | ⬜ TODO | Snapshots green; README + guide updated |

---

## P0: Skeleton

### Files created
- [ ] `tui/messages.py` — all Message types (§5.4)
- [ ] `tui/styles.tcss` — design tokens + layout rules
- [ ] `tui/services/__init__.py`
- [ ] `tui/services/bootstrap.py` — Services container + FakeServices
- [ ] `tui/services/formatting.py` — formatting helpers
- [ ] `tui/screens/main.py` — MainScreen with ContentSwitcher
- [ ] `tui/screens/help.py` — HelpScreen
- [ ] `tui/widgets/top_bar.py` — TopBar
- [ ] `tui/views/chat.py` — ChatView (stub with input + empty log)
- [ ] `tui/views/dashboard.py` — DashboardView (stub with empty tabs)
- [ ] `tui/app.py` — MommyTuiApp rewrite
- [ ] `tui/__init__.py` — update exports
- [ ] Delete old files: screens/chat.py, screens/dashboard.py, screens/detail.py, widgets/*, data_service.py, app.tcss

### Notes
- Start time: —
- End time: —
- Test result: —

---

## P1: Dashboard

### Tasks
- [ ] `tui/services/data.py` — DataService with real adapter
- [ ] Polling worker with market-phase adaptive intervals
- [ ] WatchTable (自选股) with cell-level updates
- [ ] HoldTable (持仓) with SummaryCards
- [ ] ThemeBrowser (主题) with real reference data
- [ ] SignalLog (信号) reading from signal history
- [ ] StockDetailScreen (no K-line yet)
- [ ] `a`/`x` watchlist management
- [ ] `o` sort cycling, `g`/`G` jump

### Notes
- Start time: —
- End time: —
- Test result: —

---

## P2: Chat

### Tasks
- [ ] `tui/services/agent_bridge.py` — AgentBridge
- [ ] WorkflowCard widget
- [ ] ToolPanel widget (Collapsible)
- [ ] Streaming Markdown rendering
- [ ] Esc cancel + retry
- [ ] No-key HintCard degradation
- [ ] Preset questions (1-7) on empty state
- [ ] `Ctrl+L` clear screen

### Notes
- Start time: —
- End time: —
- Test result: —

---

## P3: Deep Features

### Tasks
- [ ] plotext mini K-line in StockDetailScreen
- [ ] `s` signal scan worker
- [ ] Command palette actions
- [ ] Preset question integration

### Notes
- Start time: —
- End time: —
- Test result: —

---

## P4: Polish

### Tasks
- [ ] Snapshot test baseline
- [ ] light/colorblind themes
- [ ] Long-session message folding
- [ ] README + user guide TUI section

### Notes
- Start time: —
- End time: —
- Test result: —

---

## Post-Implementation Review

- Date: —
- Issues found: —
- Fixes applied: —

/**
 * 右缘自选停靠（shell.overlay）：mommy 自选股 + 批量报价，SSE 失效信号驱动
 * refetch（portfolio 库任何写入——AI 写、TUI/Web 写——都触发重拉）。
 *
 * 数据经 node 半 /mommy/api 同源桥（宿主认证栅栏内）；桥缺席（如错挂
 * headless）显示可重试错误态，永不炸宿主 shell。
 *
 * 布局契约（2026-09-17 重设计）：面板**固定吸附 overlay 层右缘**（top/bottom
 * 满高、宽 264），不做自由拖拽、不做浮动药丸——浮动定位会压住宿主 chrome
 * （logo/标题）、被宿主 overlay 漂移放大成「面板飞出视口」，且位置被
 * localStorage 记住后怪状态难以自愈。收起态 = 右缘垂直拉手（垂直居中），
 * 与任何宿主元素无重叠。唯一持久化是展开/收起（storage v2，只存
 * collapsed）。纯 UI 状态，不涉任何行情计算。
 */
import { useCallback, useEffect, useMemo, useState, useSyncExternalStore } from 'react'
import { fetchQuotes, fetchWatchlist, subscribeMommyEvents, type WatchlistEntry } from './api.ts'
import { fmtAmountCN, fmtPct, trendOf, type QuoteView } from './parse.ts'
import type { LocaleKey } from './locales.ts'
import { loadConfig, saveConfig, subscribeConfig as subscribeConfigClient, type BarsMode } from './config.ts'
import css from './dock.module.css'

export interface MommyDockProps {
  t?: (key: LocaleKey, params?: Record<string, unknown>) => string
}

interface DockState {
  entries: WatchlistEntry[]
  quotes: Map<string, QuoteView>
  source: string
  /** 报价拉新失败原因（非空 = 显示的是上次快照，行情源暂不可用）。 */
  staleNote: string | null
  error: string | null
  loading: boolean
}

const EMPTY: DockState = { entries: [], quotes: new Map(), source: '', staleNote: null, error: null, loading: true }
/** v2 只存 { collapsed}；v1 的自由坐标语义已废弃，不迁移。 */
const STORAGE_KEY = 'mommy.dock.v2'

const BARS_MODE_KEYS: Record<BarsMode, LocaleKey> = {
  table: 'config.barsMode.table',
  svg: 'config.barsMode.svg',
  lwc: 'config.barsMode.lwc',
}

function loadCollapsed(): boolean {
  try {
    const raw = localStorage.getItem(STORAGE_KEY)
    if (raw === null) return false
    const parsed = JSON.parse(raw) as { collapsed?: unknown }
    return parsed.collapsed === true
  } catch {
    return false
  }
}

function saveCollapsed(collapsed: boolean): void {
  try {
    localStorage.setItem(STORAGE_KEY, JSON.stringify({ collapsed }))
  } catch {
    // 隐私模式等 storage 不可用：不持久化，功能不受影响
  }
}

export function MommyDock(props: MommyDockProps) {
  const t = props.t
  const [state, setState] = useState<DockState>(EMPTY)
  const [openCode, setOpenCode] = useState<string | null>(null)
  const [settingsOpen, setSettingsOpen] = useState(false)
  const [collapsed, setCollapsed] = useState(loadCollapsed)
  const config = useSyncExternalStore(subscribeConfigClient, loadConfig)

  const toggleCollapsed = useCallback(() => {
    setCollapsed(prev => {
      const next = !prev
      saveCollapsed(next)
      return next
    })
  }, [])

  const load = useCallback(async () => {
    setState(prev => ({ ...prev, loading: true, error: null }))
    try {
      const entries = await fetchWatchlist()
      const codes = entries.map(entry => entry.code)
      // 报价是增强：拉新失败（网络异常，或 CLI exit 0 + error 载荷——数据源
      // 挂了）不拖垮自选列表，保留上次快照并在脚注显式标注 stale——静默清空
      // 会把「数据源挂了」伪装成「空自选」。
      let quotes: Map<string, QuoteView> | null = null
      let source: string | null = null
      let staleNote: string | null = null
      if (codes.length > 0) {
        try {
          const payload = await fetchQuotes(codes)
          if (payload.error !== undefined) {
            staleNote = payload.error
          } else {
            source = payload.source
            quotes = new Map(payload.quotes.map(q => [q.code, q]))
          }
        } catch (error) {
          staleNote = error instanceof Error ? error.message : String(error)
        }
      }
      setState(prev => ({
        entries,
        quotes: quotes ?? prev.quotes,
        source: source ?? prev.source,
        staleNote,
        error: null,
        loading: false,
      }))
    } catch (error) {
      setState(prev => ({
        ...prev,
        loading: false,
        error: error instanceof Error ? error.message : String(error),
      }))
    }
  }, [])

  useEffect(() => {
    void load()
    return subscribeMommyEvents({ portfolio: () => void load() })
  }, [load])

  const groups = useMemo(() => {
    const map = new Map<string, WatchlistEntry[]>()
    for (const entry of state.entries) {
      const list = map.get(entry.group) ?? []
      list.push(entry)
      map.set(entry.group, list)
    }
    return [...map.entries()]
  }, [state.entries])

  const refreshButton = (
    <button
      type="button"
      className={css.button}
      aria-pressed={state.loading ? 'true' : 'false'}
      onClick={() => void load()}
    >
      {state.loading ? (t?.('dock.loading') ?? '加载中…') : (t?.('dock.refresh') ?? '刷新')}
    </button>
  )

  const collapseButton = (
    <button
      type="button"
      className={css.button}
      aria-label={t?.('dock.collapse') ?? '收起'}
      onClick={toggleCollapsed}
    >
      –
    </button>
  )

  // —— 设置：展示偏好菜单（bars 卡渲染模式）。纯 localStorage，不碰数据口径。 ——
  const settingsButton = (
    <button
      type="button"
      className={css.button}
      aria-label={t?.('config.title') ?? '设置'}
      aria-expanded={settingsOpen ? 'true' : 'false'}
      onClick={() => setSettingsOpen(open => !open)}
    >
      ⚙
    </button>
  )

  const settingsPanel = settingsOpen ? (
    <div className={css.settings} role="group" aria-label={t?.('config.title') ?? '设置'}>
      <div className={css.settingsTitle}>{t?.('config.barsMode') ?? 'K 线卡片渲染'}</div>
      <div className={css.settingsOptions} role="radiogroup" aria-label={t?.('config.barsMode') ?? 'K 线卡片渲染'}>
        {(['table', 'svg', 'lwc'] as const).map(mode => (
          <label key={mode} className={css.settingsOption}>
            <input
              type="radio"
              name="mommy-bars-mode"
              checked={config.barsMode === mode}
              onChange={() => saveConfig({ barsMode: mode })}
            />
            <span>{t?.(BARS_MODE_KEYS[mode])}</span>
          </label>
        ))}
      </div>
      <div className={css.settingsNote}>{t?.('config.savedNote') ?? '偏好仅保存在本机浏览器'}</div>
    </div>
  ) : null

  // 收起态：右缘垂直拉手（垂直居中，不占顶部 chrome，与 logo/标题零重叠）。
  if (collapsed) {
    return (
      <button
        type="button"
        className={css.tab}
        data-mommy-dock="watchlist"
        aria-label={t?.('dock.expand') ?? '展开'}
        onClick={toggleCollapsed}
      >
        <span className={css.tabLabel}>
          {t?.('dock.title') ?? '自选'} · {state.entries.length}
        </span>
      </button>
    )
  }

  const head = (
    <div className={css.head}>
      <span className={css.title}>
        {t?.('dock.title') ?? '自选'} · {state.entries.length}
      </span>
      <span className={css.grow} />
      {settingsButton}
      {state.error === null && state.entries.length > 0 ? refreshButton : null}
      {collapseButton}
    </div>
  )

  if (state.error !== null && state.entries.length === 0) {
    return (
      <div className={css.dock} data-mommy-dock="watchlist" data-dock-state="error">
        {head}
        <div className={css.center}>
          <span>{t?.('dock.error') ?? '数据不可用'}</span>
          <span className={css.code}>{state.error}</span>
          <button type="button" className={css.button} onClick={() => void load()}>
            {t?.('dock.retry') ?? '重试'}
          </button>
        </div>
        {settingsPanel}
      </div>
    )
  }

  if (state.entries.length === 0) {
    return (
      <div className={css.dock} data-mommy-dock="watchlist" data-dock-state="empty">
        {head}
        <div className={css.empty}>
          <span>{t?.('dock.empty') ?? '自选股为空'}</span>
          <span>{t?.('dock.emptyHint') ?? '在对话里让 AI「把 600519 加进自选」试试'}</span>
        </div>
        {settingsPanel}
      </div>
    )
  }

  return (
    <div className={css.dock} data-mommy-dock="watchlist" data-dock-state="ready">
      {head}
      <div className={css.body}>
        <div className={css.groups}>
          {groups.map(([group, entries]) => (
            <div key={group}>
              <div className={css.groupName}>{group}</div>
              {entries.map(entry => {
                const quote = state.quotes.get(entry.code)
                const trend = trendOf(quote?.changePct ?? null)
                const open = openCode === entry.code
                return (
                  <div
                    key={`${entry.group}:${entry.code}`}
                    className={css.row}
                    data-open={open ? 'true' : 'false'}
                    onClick={() => setOpenCode(open ? null : entry.code)}
                    role="button"
                    tabIndex={0}
                    onKeyDown={event => {
                      if (event.key === 'Enter' || event.key === ' ') setOpenCode(open ? null : entry.code)
                    }}
                  >
                    <div className={css.rowMain}>
                      <span className={css.name}>{entry.name ?? entry.code}</span>
                      <span className={css.code}>{entry.code}</span>
                      {quote !== undefined && (
                        <>
                          <span className={`${css.price} ${css.trend}`} data-trend={trend}>
                            {quote.price.toFixed(2)}
                          </span>
                          <span className={`${css.trend} ${css.price}`} data-trend={trend}>
                            {fmtPct(quote.changePct)}
                          </span>
                        </>
                      )}
                    </div>
                    {open && quote !== undefined && (
                      <div className={css.detail}>
                        <span>
                          {t?.('field.open') ?? '开'} <span className={css.num}>{quote.open?.toFixed(2) ?? '—'}</span>
                        </span>
                        <span>
                          {t?.('field.high') ?? '高'} <span className={css.num}>{quote.high?.toFixed(2) ?? '—'}</span>
                        </span>
                        <span>
                          {t?.('field.low') ?? '低'} <span className={css.num}>{quote.low?.toFixed(2) ?? '—'}</span>
                        </span>
                        <span>
                          {t?.('field.prevClose') ?? '昨收'}{' '}
                          <span className={css.num}>{quote.prevClose?.toFixed(2) ?? '—'}</span>
                        </span>
                        <span>
                          {t?.('field.turnover') ?? '成交额'}{' '}
                          <span className={css.num}>{fmtAmountCN(quote.turnover)}</span>
                        </span>
                        <span>
                          {t?.('field.pe') ?? 'PE'} <span className={css.num}>{quote.pe?.toFixed(1) ?? '—'}</span>
                        </span>
                      </div>
                    )}
                    {open && entry.note !== null && entry.note !== '' && (
                      <div className={css.code}>{entry.note}</div>
                    )}
                  </div>
                )
              })}
            </div>
          ))}
        </div>
      </div>
      {state.staleNote !== null && (
        <div className={css.foot} data-mommy-stale="quotes">
          {t?.('dock.stale') ?? '行情拉新失败，显示上次快照'}
        </div>
      )}
      {state.source !== '' && (
        <div className={css.foot}>
          {t?.('dock.source') ?? '来源'}: {state.source}
        </div>
      )}
      {settingsPanel}
    </div>
  )
}

/** 卡片与停靠面板文案面：locale key 联合类型 + zh/en 词典。 */

export type LocaleKey =
  | 'dock.title'
  | 'dock.empty'
  | 'dock.emptyHint'
  | 'dock.error'
  | 'dock.retry'
  | 'dock.refresh'
  | 'dock.loading'
  | 'dock.source'
  | 'dock.stale'
  | 'dock.collapse'
  | 'dock.expand'
  | 'card.quote.title'
  | 'card.quotes.title'
  | 'card.indexes.title'
  | 'card.flow.title'
  | 'card.flow.mainNet'
  | 'card.flow.superLarge'
  | 'card.flow.large'
  | 'card.flow.medium'
  | 'card.flow.small'
  | 'card.flow.ratio'
  | 'card.bars.title'
  | 'card.bars.older'
  | 'card.bars.detail'
  | 'card.bars.hideTable'
  | 'config.title'
  | 'config.barsMode'
  | 'config.barsMode.table'
  | 'config.barsMode.svg'
  | 'config.barsMode.lwc'
  | 'config.savedNote'
  | 'card.predictions.title'
  | 'card.watchlistOp.title'
  | 'card.watchlistOp.ok'
  | 'card.watchlistOp.denied'
  | 'card.watchlistOp.error'
  | 'card.signal.title'
  | 'card.signal.type'
  | 'card.backtest.title'
  | 'card.backtest.signals'
  | 'card.backtest.winRate'
  | 'card.backtest.avgReturn'
  | 'card.backtest.drawdown'
  | 'card.backtest.hold'
  | 'card.backtest.caveats'
  | 'card.flowHistory.title'
  | 'card.screenInflow.title'
  | 'card.similarEvents.title'
  | 'card.recordConclusion.title'
  | 'card.recordConclusion.saved'
  | 'card.recordConclusion.needsConfirm'
  | 'card.recordConclusion.skipped'
  | 'field.open'
  | 'field.high'
  | 'field.low'
  | 'field.prevClose'
  | 'field.volume'
  | 'field.turnover'
  | 'field.turnoverRate'
  | 'field.pe'
  | 'field.totalCap'
  | 'field.circCap'
  | 'field.close'
  | 'field.date'

type Dict = Record<LocaleKey, string>

export const zh: Dict = {
  'dock.title': '自选',
  'dock.empty': '自选股为空',
  'dock.emptyHint': '在对话里让 AI「把 600519 加进自选」试试',
  'dock.error': '数据不可用',
  'dock.retry': '重试',
  'dock.refresh': '刷新',
  'dock.loading': '加载中…',
  'dock.source': '来源',
  'dock.stale': '行情拉新失败，显示上次快照',
  'dock.collapse': '收起',
  'dock.expand': '展开',
  'card.quote.title': '实时报价',
  'card.quotes.title': '批量报价',
  'card.indexes.title': '大盘指数',
  'card.flow.title': '当日资金流',
  'card.flow.mainNet': '主力净流入',
  'card.flow.superLarge': '超大单',
  'card.flow.large': '大单',
  'card.flow.medium': '中单',
  'card.flow.small': '小单',
  'card.flow.ratio': '主力净占比',
  'card.bars.title': 'K 线',
  'card.bars.older': '更早 {count} 根',
  'card.bars.detail': '明细 {count} 根',
  'card.bars.hideTable': '收起明细',
  'config.title': '设置',
  'config.barsMode': 'K 线卡片渲染',
  'config.barsMode.table': '表格',
  'config.barsMode.svg': '迷你 K 线',
  'config.barsMode.lwc': '交互 K 线',
  'config.savedNote': '偏好仅保存在本机浏览器',
  'card.predictions.title': '预测历史',
  'card.watchlistOp.title': '自选操作',
  'card.watchlistOp.ok': '已执行',
  'card.watchlistOp.denied': '已拒绝',
  'card.watchlistOp.error': '失败',
  'card.signal.title': 'K 线信号',
  'card.signal.type': '信号',
  'card.backtest.title': '信号回放',
  'card.backtest.signals': '信号数',
  'card.backtest.winRate': '胜率',
  'card.backtest.avgReturn': '平均净收益',
  'card.backtest.drawdown': '最大回撤',
  'card.backtest.hold': '持有',
  'card.backtest.caveats': '探索性评估',
  'card.flowHistory.title': '历史资金流',
  'card.screenInflow.title': '主力净流入筛选',
  'card.similarEvents.title': '相似历史事件',
  'card.recordConclusion.title': '研究结论',
  'card.recordConclusion.saved': '已写入记忆',
  'card.recordConclusion.needsConfirm': '待用户确认',
  'card.recordConclusion.skipped': '按请求跳过',
  'field.open': '开',
  'field.high': '高',
  'field.low': '低',
  'field.prevClose': '昨收',
  'field.volume': '成交量',
  'field.turnover': '成交额',
  'field.turnoverRate': '换手',
  'field.pe': 'PE',
  'field.totalCap': '总市值',
  'field.circCap': '流通市值',
  'field.close': '收盘',
  'field.date': '日期',
}

export const en: Dict = {
  'dock.title': 'Watchlist',
  'dock.empty': 'Watchlist is empty',
  'dock.emptyHint': 'Ask the AI in chat: "add 600519 to my watchlist"',
  'dock.error': 'Data unavailable',
  'dock.retry': 'Retry',
  'dock.refresh': 'Refresh',
  'dock.loading': 'Loading…',
  'dock.source': 'Source',
  'dock.stale': 'Quote refresh failed; showing last snapshot',
  'dock.collapse': 'Collapse',
  'dock.expand': 'Expand',
  'card.quote.title': 'Live quote',
  'card.quotes.title': 'Batch quotes',
  'card.indexes.title': 'Market indexes',
  'card.flow.title': 'Money flow (today)',
  'card.flow.mainNet': 'Main net inflow',
  'card.flow.superLarge': 'Super large',
  'card.flow.large': 'Large',
  'card.flow.medium': 'Medium',
  'card.flow.small': 'Small',
  'card.flow.ratio': 'Main net ratio',
  'card.bars.title': 'Bars',
  'card.bars.older': '{count} older bars',
  'card.bars.detail': 'Details ({count} bars)',
  'card.bars.hideTable': 'Hide details',
  'config.title': 'Settings',
  'config.barsMode': 'Bars card render',
  'config.barsMode.table': 'Table',
  'config.barsMode.svg': 'Mini candles',
  'config.barsMode.lwc': 'Interactive chart',
  'config.savedNote': 'Stored in this browser only',
  'card.predictions.title': 'Prediction history',
  'card.watchlistOp.title': 'Watchlist change',
  'card.watchlistOp.ok': 'Applied',
  'card.watchlistOp.denied': 'Denied by user',
  'card.watchlistOp.error': 'Failed',
  'card.signal.title': 'K-line signals',
  'card.signal.type': 'Signal',
  'card.backtest.title': 'Signal replay',
  'card.backtest.signals': 'Signals',
  'card.backtest.winRate': 'Win rate',
  'card.backtest.avgReturn': 'Avg net return',
  'card.backtest.drawdown': 'Max drawdown',
  'card.backtest.hold': 'Hold',
  'card.backtest.caveats': 'Exploratory',
  'card.flowHistory.title': 'Money flow history',
  'card.screenInflow.title': 'Main-inflow screen',
  'card.similarEvents.title': 'Similar past events',
  'card.recordConclusion.title': 'Research conclusion',
  'card.recordConclusion.saved': 'Saved to memory',
  'card.recordConclusion.needsConfirm': 'Awaiting user confirmation',
  'card.recordConclusion.skipped': 'Skipped by request',
  'field.open': 'Open',
  'field.high': 'High',
  'field.low': 'Low',
  'field.prevClose': 'Prev close',
  'field.volume': 'Volume',
  'field.turnover': 'Turnover',
  'field.turnoverRate': 'Turnover rate',
  'field.pe': 'PE',
  'field.totalCap': 'Total cap',
  'field.circCap': 'Circ. cap',
  'field.close': 'Close',
  'field.date': 'Date',
}

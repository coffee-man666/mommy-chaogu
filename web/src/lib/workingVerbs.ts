// A 股语境的"工作中"动词表 + braille spinner
// 移植自 src/mommy_chaogu/tui/widgets/working_indicator.py

export const THINKING_VERBS: readonly string[] = [
  '盯盘中',
  '复盘中',
  '翻财报中',
  '算估值中',
  '看资金流中',
  '扒数据中',
  '查公告中',
  '扫板块中',
  '琢磨中',
  '研判中',
  '对账中',
  '推演中',
] as const

export const SPINNER_FRAMES: readonly string[] = [
  '⠋', '⠙', '⠹', '⠸', '⠼', '⠴', '⠦', '⠧', '⠇', '⠏',
] as const

export function randomVerb(): string {
  return THINKING_VERBS[Math.floor(Math.random() * THINKING_VERBS.length)]
}

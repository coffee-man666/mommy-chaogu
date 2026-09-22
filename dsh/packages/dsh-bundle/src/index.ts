/**
 * @mommy-chaogu/dsh-bundle root 入口：client 行的 host 半 + 纯 helper 再导出。
 *
 * patch 行 `mommy-chaogu-client` 指向本入口（包根——宿主 client-modules 扫描器
 * 的 exactPackageSpecifier 对 scoped 包只认裸包名，子路径行永远不是 client row）：
 * loader 在宿主进程 import 本模块（空 apply 无害）；浏览器半（lib/client.js）由
 * web 宿主经包 manifest 的 dsh.client 声明发现并注入 __DSH_BOOT__。
 *
 * 其余插件入口在子路径 exports（patch 行按 bare 包名 + 子路径解析）：
 * `./gate` 审批闸门、`./presets` preset 安装器、`./bridge` HTTP 桥。
 */
export const name = 'mommy-chaogu-client'

export function apply(): void {}

export {
  CONFIRM_ALWAYS,
  CONFIRM_BY_ACTION,
  MCP_TOOL_PREFIX,
  createGateListener,
  decideWriteGate,
  requiresConfirmation,
} from './gate.ts'
export { PRESET_ID, defaultPresetRoot, installPreset, isUnmodifiedManaged, stamp } from './presets.ts'
export { API_PREFIX, createMommyRoutes, parseCodes, sendJson } from './bridge.ts'
export { RevisionBus, attachEventStream, type MommyEventStore } from './events.ts'
export { createRunner, type MommyInvocation, type RunJson } from './spawn.ts'

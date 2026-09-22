/**
 * 宿主 toolview 注入 props 的最小结构面（类型级，零运行时）。
 * 官方类型在 @deepseek-ai/dsh-client-ui-tool/client（dsh-trading toolview.tsx
 * 同源）；此处以本地结构面声明，避免对未安装宿主包产生构建依赖——
 * 类型不匹配会在真机 slot 挂载时暴露（onEntryError 可见化）。
 */
export interface ToolCallOwnerProps {
  /** 本次工具调用的对话块（argsRaw / result / isError）。 */
  block?: {
    kind?: string
    argsRaw?: string
    call?: { argsRaw?: string } | undefined
    content?: unknown[]
    isError?: boolean
  }
}

/** CSS Modules 与全局 CSS 的类型面（构建期 lightningcss 内联，无运行时 import）。 */
declare module '*.module.css' {
  const classes: Record<string, string>
  export default classes
}

declare module '*.css' {
  const css: string
  export default css
}

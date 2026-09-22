/** Host 半构建：四个子路径插件入口（gate/presets/bridge）+ root 再导出。 */
export default {
  entry: {
    index: 'src/index.ts',
    gate: 'src/gate.ts',
    presets: 'src/presets.ts',
    bridge: 'src/bridge.ts',
  },
  outDir: 'lib',
  format: 'esm',
  platform: 'node',
  target: 'node22',
  dts: true,
  sourcemap: true,
  clean: false,
  // exports 声明 ./lib/*.js；type:module 下 tsdown 默认给 ESM 产物 .mjs 后缀，钉死。
  outExtensions: () => ({ js: '.js' }),
}

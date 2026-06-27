import { defineConfig } from '@tarojs/cli'

export default defineConfig(async (merge, { command, mode }) => {
  const baseConfig = {
    projectName: 'mommy-chaogu',
    date: '2026-6-27',
    designWidth: 750,
    deviceRatio: { 640: 2.34 / 2, 750: 1, 828: 1.81 / 2, 375: 2 / 1 },
    sourceRoot: 'src',
    outputRoot: 'dist',
    plugins: ['@tarojs/plugin-framework-vue3'],
    defineConstants: {},
    copy: { patterns: [], options: {} },
    framework: 'vue3' as const,
    compiler: 'webpack5' as const,
    cache: { enable: false },
    sass: { resource: [] },
    mini: {
      postcss: { pxtransform: { enable: true }, cssModules: { enable: false } }
    },
    h5: {
      publicPath: '/',
      staticDirectory: 'static',
      output: { filename: 'js/[name].[hash:8].js', chunkFilename: 'js/[name].[chunkhash:8].js' },
      miniCssExtractPluginOption: { ignoreOrder: true, filename: 'css/[name].[hash].css' },
      postcss: { autoprefixer: { enable: true }, cssModules: { enable: false } },
      devServer: {
        port: 8080,
        host: '0.0.0.0',
        proxy: {
          '/api': { target: 'http://localhost:8765', changeOrigin: true },
          '/ws': { target: 'ws://localhost:8765', ws: true, changeOrigin: true }
        }
      }
    }
  }

  if (process.env.NODE_ENV === 'development') {
    return merge({}, baseConfig, { defineConstants: { 'process.env.NODE_ENV': '"development"' } })
  }
  return merge({}, baseConfig, { defineConstants: { 'process.env.NODE_ENV': '"production"' } })
})

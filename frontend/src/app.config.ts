export default defineAppConfig({
  pages: [
    'pages/index/index',
    'pages/detail/index',
    'pages/signals/index',
    'pages/settings/index'
  ],
  window: {
    backgroundTextStyle: 'light',
    navigationBarBackgroundColor: '#c83e3e',
    navigationBarTitleText: '妈妈炒股',
    navigationBarTextStyle: 'white',
    enablePullDownRefresh: false
  },
  tabBar: {
    color: '#999999',
    selectedColor: '#c83e3e',
    backgroundColor: '#ffffff',
    list: [
      { pagePath: 'pages/index/index', text: '行情' },
      { pagePath: 'pages/signals/index', text: '信号' },
      { pagePath: 'pages/settings/index', text: '设置' }
    ]
  }
})

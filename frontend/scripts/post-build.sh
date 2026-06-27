#!/bin/bash
# Taro H5 build post-processing
# - 生成稳定名的 index.html（自动找 app.*.js + 主 css）
# - 复制到 FastAPI 服务的目录

set -e
DIST="${1:-dist}"

if [ ! -d "$DIST" ]; then
  echo "Error: dist directory not found: $DIST"
  exit 1
fi

# 找主 JS（app.*.js）和主 CSS（app.*.css）
MAIN_JS=$(ls "$DIST"/js/app.*.js 2>/dev/null | grep -v LICENSE | head -1 | xargs basename 2>/dev/null)
MAIN_CSS=$(ls "$DIST"/css/app.*.css 2>/dev/null | head -1 | xargs basename 2>/dev/null)

if [ -z "$MAIN_JS" ]; then
  echo "Error: app.*.js not found in $DIST/js"
  exit 1
fi

echo "Main JS: $MAIN_JS"
echo "Main CSS: $MAIN_CSS"

# 写 index.html
cat > "$DIST/index.html" << EOF
<!DOCTYPE html>
<html lang="zh-CN">
<head>
  <meta charset="UTF-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1.0, maximum-scale=1.0, user-scalable=no" />
  <meta name="theme-color" content="#c83e3e" />
  <title>妈妈炒股</title>
  ${MAIN_CSS:+<link rel="stylesheet" href="css/${MAIN_CSS}" />}
  <style>
    html, body {
      margin: 0;
      padding: 0;
      width: 100%;
      min-height: 100%;
      overflow-x: hidden;
      background: #f5f5f5;
      font-family: -apple-system, BlinkMacSystemFont, "Helvetica Neue", Helvetica, "PingFang SC", "Microsoft YaHei", sans-serif;
      -webkit-tap-highlight-color: transparent;
      -webkit-font-smoothing: antialiased;
    }
    #app { width: 100%; min-height: 100vh; }
    .boot-loader {
      position: fixed;
      top: 50%;
      left: 50%;
      transform: translate(-50%, -50%);
      color: #c83e3e;
      font-size: 16px;
      text-align: center;
    }
    .boot-spinner {
      width: 32px;
      height: 32px;
      border: 3px solid #f5f5f5;
      border-top-color: #c83e3e;
      border-radius: 50%;
      animation: spin 0.8s linear infinite;
      margin: 0 auto 12px;
    }
    @keyframes spin {
      to { transform: rotate(360deg); }
    }
  </style>
</head>
<body>
  <div id="app">
    <div class="boot-loader">
      <div class="boot-spinner"></div>
      加载中...
    </div>
  </div>
  <script src="js/${MAIN_JS}"></script>
</body>
</html>
EOF

echo "✓ Generated $DIST/index.html"

# GitHub Pages 宣传站

宣传站与 `mommy-chaogu plugins store` 源码位于 `site/`，包含：

- 项目能力介绍与产品边界
- `v1.5.0`、`v1.4.0`、`v1.3.0`、`v1.2.0` 更新摘要
- `2026-08-19` 粮食安全主题分析的可交互页面、报告入口和整包下载
- 六个并列展示的项目插件：`mommy-onboard`、`mommy-research`、`mommy-strategy`、`market-watch-loop`、`basket-analysis`、`food-security-analysis`
- 六个插件的当前版本 ZIP；`basket-analysis` 另提供 `.tar.gz` 归档
- 可实际执行的 `install-skill.py` 安装脚本

`.github/workflows/pages.yml` 会在 `main` 分支的站点文件变更后部署 GitHub Pages。第一次启用时，在仓库 Settings → Pages 中将 Source 设为 **GitHub Actions**，之后由 workflow 发布。

## 本地检查

```bash
python3 scripts/verify_pages.py
python3 -m http.server 4173 --directory site
```

安装 smoke test 会把 Skill 装到临时目录，不会修改当前用户的 Codex / Claude / Kimi / Cline 配置：

```bash
python3 site/install-skill.py \
  --target custom \
  --destination /tmp/mommy-chaogu-skill-smoke \
  site/skills/basket-analysis-v1.2.1.zip
```

其他五个归档也可将最后一行替换为 Plugins Store 中对应的 `site/skills/*.zip`；`basket-analysis` 另有 `.tar.gz` 版本。

六个内置插件（包括 `basket-analysis` 和 `food-security-analysis`）都应使用项目真实支持的 `mommy agent plan/connect` 路径安装；每个插件也有可下载 ZIP，两个主题插件另外保留 tar.gz 归档，适合单独检查或分发。

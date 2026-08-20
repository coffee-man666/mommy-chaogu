# mommy-chaogu GitHub Pages

这是项目宣传站和静态 `mommy-chaogu plugins store` 的源文件。站点不需要 Node 或运行时服务，GitHub Pages 直接托管 `site/` 目录。

本地预览：

```bash
python3 -m http.server 4173 --directory site
open http://127.0.0.1:4173
```

Plugins Store 里的六个项目插件来自同一份 bundled catalog；每个条目都有当前版本 ZIP，两个主题插件另外保留原始 tar.gz 归档。安装脚本 `install-skill.py` 只使用 Python 标准库，会先验证压缩包路径与 `SKILL.md`，再安全解压到目标宿主的 Skills 根目录。

站点中的 `2026-08-19` 是公开研究/教学样例，不是投资建议。它保留了数据截至时间、覆盖范围、输出文件和原始数据，方便检查而不是把结果当成收益验证。

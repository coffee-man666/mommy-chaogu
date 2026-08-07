# 下一步计划（NEXT STEPS）

> 待办清单的落盘位置：记录尚未执行、需要择机完成的改进项。
> 完成一项勾掉一项；跨会话恢复时以此为准。
>
> 最后更新：2026-08-06（v1.4.0 发布后）

## README 升级（发布后待做）

目标是让 README 达到"牛逼项目"观感。按见效速度排序：

- [ ] **加 TUI / Web 截图演示**——`mommy tui` 富卡片界面和 Web 仪表盘各截一张图，
      放在 README 第一屏附近；有视觉证明是最大分水岭。
- [ ] **重写 tagline + 特性亮点小节**——当前定位语太长不够锋利；把
      「A 股美股一句话互通」「观点→可执行工作流」「Claude/Kimi Code 接入」做成
      「特性 + 一句收益 + 示例」的小节。
- [ ] **架构一瞥**——用 30 秒可读完的方式展示数据源适配链（Massive/Yahoo 美股 +
      efinance/腾讯 A 股，失败降级）、工作流引擎和「三端共享内核」。
- [ ] **安装 URL 收敛**——`install.sh` 目前是 raw commit hash，至少改成 `latest`
      或补一句域名地址上线计划，避免观感降级。

## 其他遗留（随手记，不紧急）

- [ ] 根目录 `node_modules/` 未被 `.gitignore` 忽略（当前只忽略 `frontend/node_modules/`）；
      如不需要可加一条 `node_modules/` 规则。
- [ ] `reports/` 已在 `.gitignore` 忽略（2026-08-06）；已跟踪的 `reports/README.md`、
      `reports/index.html` 等仍留在仓库，需确认是否长期保留。

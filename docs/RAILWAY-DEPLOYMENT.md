# Railway 部署

项目使用根目录 `Dockerfile` 部署。Web 服务会监听 Railway 提供的 `PORT`，并继续以
非 root 用户 `mommy`（UID 1000）运行。

## 必需变量

在 Railway 服务的 Variables 中配置：

```text
MOMMY_API_TOKEN=<足够长的随机字符串>
AGENT_PROVIDER=kimi
MOONSHOT_API_KEY=<你的 key>
WEB_BASE_URL=https://<你的 Railway 域名>
```

也可以将 provider 和对应 API key 换成 `.env.example` 中支持的其他组合。公网监听时
`MOMMY_API_TOKEN` 必填；浏览器在「设置 → 访问令牌」中输入相同值。

## SQLite 持久化

四个 SQLite 数据库以及运行时日志默认位于 `/app/data`。为服务添加一个 Railway
Volume，并严格使用以下挂载路径：

```text
/app/data
```

Railway 的卷以 root 身份挂载，因此卷启用后还需设置：

```text
RAILWAY_RUN_UID=0
```

这不会让 Web 服务持续以 root 运行。镜像的 `mommy-entrypoint` 只以 root 完成三件事：

1. 初始化 `/app/data`；
2. 将镜像内的只读参考数据同步到卷；
3. 修正卷权限，然后通过 `gosu` 立即降权到 `mommy`。

挂载到其他路径时，入口会主动退出，避免应用看似运行但 SQLite 实际没有持久化。

## Railway 设置

- Builder：`Dockerfile`
- Healthcheck path：`/api/health`
- Restart policy：`ON_FAILURE`
- Public domain：为服务生成一个 Railway domain

部署完成后检查：

```bash
curl --fail https://<你的 Railway 域名>/api/health
```

健康检查应返回 `200`；未携带 Bearer token 访问其他 `/api/*` 路由应返回 `401`。

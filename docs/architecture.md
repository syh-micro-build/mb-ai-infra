# 架构与职责

`mb-ai-infra` 是低频发布的基础设施控制工程。应用版本不进入基础设施配置。只有监听端口、公开路由、健康状态或协议等部署契约改变，才需要更新 Infra。

| 资产 | Owner | Infra 行为 |
|---|---|---|
| `/opt/sub2api` | Sub2API 官方部署 | HTTP 检查、代理；不读取业务配置、不编辑、不停容器 |
| `/opt/mb-ai-docs` | 文档站独立部署 | HTTP 检查、代理；不编辑、不构建、不发布 |
| `/opt/mb-ai-infra` | Infra | 工具、发布配置、事务、报告 |
| `/opt/mb-ai-edge` | 旧 Infra | 仅显式迁移时归档；停指定 Nginx，保留原目录 |
| `/etc/letsencrypt` | 主机/Infra | 单域名证书、续期 hook、只读挂载到 Edge |
| SSH/UFW/iptables/Fail2ban/auditd | 主机/Infra | Ansible 声明、检查、实施和验证 |
| 云安全组、DNS、应用数据库 | 外部 owner | 文档策略、外部验收；不自动调用厂商 API |

应用契约在 `contracts/`，顺序为 Sub2API、Docs。v1 路由固定为 `/`、`/docs/`，仅接受 `127.0.0.1` HTTP 上游。健康检查不跟随重定向，精确匹配声明状态。缺少应用返回 `[BLOCKED]`。

Edge 使用 Linux host network，容器内 `127.0.0.1` 与宿主机回环一致。它不挂载 Docker socket，不发布应用端口，不与应用合并 Compose。项目名称始终为 `mb-ai-infra`，唯一服务为 `edge`。Compose 操作明确指定项目、文件与服务，没有全局 stop/prune/down。

```text
/opt/mb-ai-infra/
  bin/infra.py, firewall.py       主机操作工具
  releases/<version-hash-hash>/  配置、契约、Compose、校验清单
  current -> releases/<id>       原子切换指针
  transactions/                 root-only 事务记录、旧 Edge 归档
  reports/                      本机验收报告
  deployment.lock              部署/回滚/续期 reload 互斥锁
```

部署保留候选和历史配置，不自动删除发布目录或镜像。发布路径写入 Compose，使更换指针后 `compose up` 明确识别新挂载路径。候选先进行语法校验，服务启动和 TLS/路由检查失败后，恢复旧指针并重新启动旧 Edge；无旧版本则停止新 Edge。恢复失败记录为 `recovery-failed` 并返回非零，不能当作部署成功。

迁移额外保存旧容器 ID 和 restart policy，关闭旧 Edge 的自动重启，避免重启后争抢 80/443。恢复使用保存的同一容器，不重建或合并旧应用。发布 ID 不依赖应用镜像版本。

仓库 `docs/` 是 Infra 自身运行文档，和 `mb-ai-docs` 应用无关。v1 安全目标为服务器安全基线；不承诺替代 EDR、SIEM、IAM、SOC 或完整 WAF。

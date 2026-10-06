# 分阶段部署

运维命令在 Linux/WSL 控制机通过 Docker Runner 执行，无需本机 Python/Ansible/Make。目标为 Ubuntu 22.04/24.04、systemd、SSH、公钥 sudo 账号和网络；系统 Python 初始可缺失。目标机不克隆仓库、不运行 Runner、不安装 Ansible/pip/venv/开发工具链。先从一个新 SSH 会话确认公钥登录和 sudo 可用，保留另一个管理会话及云控制台恢复入口。详见 [Runner/CLI](runner.md)。

完成 Inventory、SSH key/agent 和独立核验的 known_hosts 配置后，先 `./infra init`。PR 分支或 GHCR 发布前使用 `./infra init --build`。preflight 缺少 Python 时只读阻止；显式执行 `./infra bootstrap-zero` 仅引导系统 Python/python3-apt，再预检。bootstrap/provision 自动包含该阶段；check 模式不执行包安装，也不能模拟没有 Python 的事实收集。

1. 复制 example inventory 到被忽略的 local 目录，填写真实值。`admin_cidrs` 是操作员公网出口地址，不是控制端的 NAT 内网地址；公网网卡使用实际名称，可填写多个接口。
2. 云防火墙允许管理员到 SSH，公网 TCP 80/443，其他入站拒绝；A 与 AAAA 均按真实 IPv4/IPv6 地址配置。尚未就绪的 AAAA 应由 DNS owner 处理。
3. 执行 `./infra preflight`，再执行 `./infra check` 看计划。首次安装时，check 模式不能模拟未安装程序的执行结果；可先审阅 bootstrap 计划，再 bootstrap 后复查。
4. 执行 `./infra bootstrap`。现有 Docker 仅启动/设为开机启动，不改 daemon.json、不升级、不重启；已有 CLI 但缺少 Compose 时会阻止继续，使用原软件来源单独安装插件。新主机只在没有冲突运行时的情况下安装官方 Docker。
5. 执行 `./infra security-check` 查看缺项，再 `./infra security-apply`。先添加 SSH 允许规则，再启用默认拒绝；核对当前 SSH peer 在管理员 CIDR 中，禁止密码账号驱动自动加固，结束后重连验证。
6. 由应用 owner 独立部署 Sub2API 和 Docs。确保两者监听回环，健康状态满足 `contracts/`。Infra 不操作数据库、Redis、应用目录或镜像版本。
7. 新主机执行 `./infra tls-bootstrap`。普通 `./infra deploy` 要求证书已存在。HTTP 初始阶段只开放 ACME，其他请求 503；拿到证书后切 TLS。
8. 执行 `./infra verify`；在另一台机器执行 `./infra external-verify`；最后按 [验收步骤](verification.md) 验证重启和重复执行。

步骤确认后，新主机可用 `./infra provision` 串联 4–8 的本机部分。应用未就绪时会阻止 Edge 部署，但前面的主机准备可能已完成。旧 Edge 主机使用 migrate，不使用 provision 自动替换。

日常基础设施升级：审阅 PR 和 CHANGELOG、拉取已确认的提交或 tag，`./infra check`、`./infra deploy`、`./infra verify`、外部验证。应用日常升级走其各自发布流程，Infra 不需要提交或运行。更新主机基线时显式执行 security-apply，Edge 部署不会顺带修改主机安全参数。

部署会有短暂 Edge 重建窗口，不是零停机方案。镜像摘要需通过 Infra PR 更新并重新扫描；当前版本不制作自定义 Nginx 镜像。没有配置 GitHub 自动 SSH 部署或生产密钥。

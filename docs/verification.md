# 验收清单与证据

CI 校验不替代生产主机验收。目标服务器阶段性验证以下事实，逐步保存结果；不要把未执行的重启、真实 ACME 或云防火墙检查写成 PASS。

| 阶段 | 命令/证据 | 通过条件 |
|---|---|---|
| 控制端 | ./infra init；固定 image ID | 本地 Inventory/SSH 材料、工具链匹配；不把 init 作为主机通过证据 |
| 最小引导 | ./infra bootstrap-zero；再次执行 | 缺失时仅系统 Python/python3-apt；重复 changed=0；无控制端工具链 |
| 只读预检 | ./infra preflight；inventory diff | 正确 OS、SSH 端口、全量公网网卡、CIDR、Docker backend |
| 部署计划 | ./infra check --ask-become-pass（密码 sudo 时） | 正式 Inventory、直接终端执行；unreachable=0、failed=0；预计变化经审阅 |
| 主机准备 | ./infra bootstrap；docker/compose version | 复用既有 daemon，缺失能力明确阻止，不变更应用 |
| 加固 | ./infra security-check；security-apply；security-verify；sshd -T | 新公钥会话可用，UFW/双栈链/服务正确，未公开应用端口 |
| 应用契约 | ./infra verify 前的 contract 检查 | 两个回环上游精确响应声明状态 |
| Edge | ./infra deploy 或 migrate；事务 | compose config/nginx -t/health/TLS/路由通过 |
| TLS | ./infra tls-check | 单个证书 staging dry-run 和 deploy hook 通过 |
| 公网 | 独立机器 ./infra external-verify | 每个 A/AAAA 的 80/443 正向检查通过、保护端口不可连接 |
| 幂等 | 再次 security-apply/infra-deploy | 没有额外规则、无需重建相同配置的 Edge、应用不被重启 |
| 重启恢复 | 人工维护窗口重启；复查服务与公网 | guard 先于 Docker，Edge 恢复，旧 Edge 不争抢端口 |
| 业务 | 应用 owner 的真实请求、流式、WebSocket、文档深链接 | 业务流量正常，应用发布仍独立 |

本机报告：`/opt/mb-ai-infra/reports/security.json`；事务：`/opt/mb-ai-infra/transactions/*.json`；外部报告：控制端 `reports/external.json`。报告不包含证书私钥或应用环境变量。

Runner CI 额外通过真实 SSH 连接无 Python 的隔离 Ubuntu 22.04/24.04 容器，验证 preflight/check 不安装包、bootstrap-zero 引导和重复 changed=0、公钥与 agent 两种认证，以及目标没有 Ansible/pip/venv/Make/GCC/Git。应用目录使用测试标记确认未被改写。该测试覆盖引导，不替代 systemd 主机基线、真实 ACME 或服务器重启验收。

外部探测先验证 80 的跳转和两个 HTTPS 应用路由，避免把 DNS/网络故障误报为防火墙成功。随后检查契约端口、5432、6379、2375、2376 是否能建立新 TCP 连接。无法连接仅证明从该探测位置不可连接，不证明具体哪一层防火墙阻挡；云规则需与云控制台证据一起验收。本机探测不证明公网封锁，独立机器与双栈覆盖是最终验收的一部分。

CI 的实际 Linux 测试：两模式 Nginx 配置、Compose config、可信测试证书、Docs 深链接和转发头、SSE 首事件时延、WebSocket handshake、Edge 重启；隔离网络命名空间模拟 Docker DNAT，检查公开 80、受限 SSH、被禁止的原始 8080 发布端口，覆盖 IPv4/IPv6、重复 apply 和 hook 丢失恢复。事务单元测试覆盖预校验失败、切换失败、初次失败、迁移 restart policy 恢复、被保护路径和清单损坏。

支持范围没有通过真实 Ubuntu 主机的完整 package/service 幂等性或 OS reboot 测试前，不做“生产已验证”结论。当前没有自带云 API、EDR/SIEM、零停机切换或完整互联网端口扫描。

完整计划测试另覆盖 Ubuntu 22.04/24.04 与密码 sudo/免密码 sudo 四种组合。目标具备系统 Python、真实 systemd 和已有 Docker，但尚无 Infra 目录和安全包；应用只用黑盒 HTTP fixture 表示。两次 check 要求 `unreachable=0`、`failed=0`，主机包、服务状态、规则、管理配置和应用目录快照保持一致。读取不到真实 SSH 来源、连接记录不合法或来源不在 `admin_cidrs` 时必须失败。密码使用随机测试值，经真实终端交互且验证未回显。该证据不替代生产上的真实应用、ACME、云网络与变更后的服务验证。

修复合并后，在控制端更新正式 checkout 并重新 `./infra init`，等待对应完整提交的 Runner 发布；发布前可 `./infra init --build`。使用正式 Inventory 删除临时的诊断覆盖后，直接执行 `./infra preflight --ask-become-pass` 和 `./infra check --ask-become-pass`，不接管道或重定向。只有完整计划通过、变更经审阅后才进入原有服务器部署步骤。

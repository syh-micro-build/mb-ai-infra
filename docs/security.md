# 主机安全基线

| 层 | 策略 | 验证 |
|---|---|---|
| 云边界 | SSH 仅管理员，公网 80/443，其余拒绝，IPv4/IPv6 一致 | 云控制台记录 + 独立外部探测 |
| 主机 | UFW incoming deny / outgoing allow；INPUT 命名链约束公网接口 | active 状态、实际链、监听端口审计 |
| Docker | DOCKER-USER 第一条进入 `MB_AI_INFRA`，仅放行原始公开端口 80/443 | 双栈规则、Docker bindings、网络命名空间测试 |
| SSH | 公钥、非 root、禁密码/交互式认证、3 次认证尝试 | sshd -T、新连接、Fail2ban |
| 系统 | 安全 sysctl、审计、仅 security origins 的自动更新、不自动重启 | 生效参数/配置、auditd、APT 日志 |
| Edge/TLS | TLS 1.2/1.3、HSTS、nosniff、转发头覆盖、连接数限制、流式支持 | 本机可信 TLS、CI、外部探测 |

Docker 的 NAT 流量可以绕过 UFW；因此不能把 UFW active 视为应用端口已被保护。[Docker firewall 文档](https://docs.docker.com/engine/network/packet-filtering-firewalls/) 和 [iptables 文档](https://docs.docker.com/engine/network/firewall-iptables/) 说明了 DOCKER-USER 与 DNAT 后过滤的关系。

`firewall.py` 只替换 `MB_AI_HOST`、`MB_AI_INFRA` 链，并保证 INPUT、DOCKER-USER、FORWARD 的入口位于第一条；保留其他规则。转发链用 `--ctorigdstport` 匹配宿主发布端口，避免把容器内部端口误当公网端口。IPv4、IPv6 均执行，失败返回非零。不清空 ruleset，不禁用 Docker 的 iptables，不关闭 IP forwarding 或 IPv6。

INPUT 链允许回环、已有连接、ICMP/ICMPv6、DHCP 回复、管理员 CIDR 到 SSH、80/443；对声明的公网接口拒绝其余新入站。DOCKER-USER 拒绝这些公网接口上的其他新转发流量。其他私网接口保留既有策略；必须把全部公网入站接口列入 inventory。策略不适用于承担通用路由/VPN 网关的主机。

`mb-ai-docker-guard.service` 在 Docker 启动前加载规则。Docker systemd drop-in 将 guard 作为启动依赖，并在 daemon 启动后再次检查/修复入口。安装该 drop-in 只执行 daemon-reload，不重启应用。Docker 使用 nftables backend、rootless、Swarm 或其他网络模型时，本版本不会自动转换。

已经建立的连接会保留，负向端口验证使用新连接。网络防护不等同于正确绑定：如果发现 Docker 发布 `0.0.0.0:8080`、`[::]:8081`、数据库端口或应用 host networking，即使防火墙可阻挡，也报告 FAIL。应用 owner 必须在其独立部署中修复，Infra 不改应用 Compose。Edge 是唯一允许的 host-network Compose 服务。

主机日志：`journalctl -u mb-ai-docker-guard -u docker`、`fail2ban-client status sshd`、`ausearch -k mb_ai_infra`、`/var/log/unattended-upgrades/`。Nginx 输出到 Docker json-file，10 MiB ×5；不记录 Authorization、查询参数和 body，但访问路径仍可能包含应用标识，按组织政策保留和访问控制。观察入口 `127.0.0.1:18080/healthz`、`/nginx_status` 不公开。

部署备份、事务和证书均为主机资产，不提交 Git，不上传 CI。保持云控制台可用；更改 SSH/防火墙前使用 plan/check 和第二个管理会话。自定义主机主配置可能覆盖 drop-in，实际 sshd -T 验证失败时需在原会话恢复备份，不能宣告加固成功。

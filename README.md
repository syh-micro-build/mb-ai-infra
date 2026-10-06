# mb-ai-infra

MicroBuild AI 基础设施工程，目标版本 **1.0.0**。管理 Edge、TLS、主机安全基线、Docker 暴露治理、Ansible IaC、迁移、部署、回滚、运行验证和 CI。

**应用升级不等于基础设施变更。** Sub2API 与 `mb-ai-docs` 通过 HTTP 部署契约连接 Infra，拥有独立仓库、镜像、部署目录和发布流程。本仓库不包含应用源码、镜像版本、数据库管理或应用 Compose，不写入 `/opt/sub2api`、`/opt/mb-ai-docs`。

```text
Internet :80/:443 → Infra Nginx (Linux host network)
                    ├─ /docs/ → 127.0.0.1:8081/docs/
                    └─ /      → 127.0.0.1:8080/
```

支持 Ubuntu **22.04 / 24.04**、systemd、Python 3、Docker **iptables backend** 和 Compose **≥2.18**。控制端需要 Linux 或 WSL，Python ≥3.12、GNU Make、SSH 公钥和 sudo 权限。现有 Docker 不会被替换、升级或重启；不支持的运行时会阻止自动安装。

## 开始

```bash
python3 -m venv .venv
source .venv/bin/activate
make deps
cp -R ansible/inventory/example ansible/inventory/local
# 修改 local/hosts.yml 和 local/group_vars/mb_ai.yml。
# 示例地址均为保留地址，不能直接用于生产。
make preflight
```

填写真实主机、非 root sudo 账号、SSH 端口、公网网卡、管理员 IPv4/IPv6 CIDR、域名和 ACME 邮箱。主机密钥检查开启，SSH 仅使用公钥。`local/` 被 Git 忽略；密钥保留在 SSH agent，其他凭据使用 Ansible Vault 或外部密钥服务。

新主机：先配置云防火墙、验证管理账号，再按应用各自流程部署两个应用，使契约可用，最后执行 `make provision`。该命令准备主机、安全基线、HTTP-01/TLS、Edge 和本机验证，不安装应用。DNS 的 A/AAAA 必须指向目标主机，公网 80 必须可达。完整外部验收仍需从另一台机器执行 `make external-verify`。

现有 `/opt/mb-ai-edge`：使用 [迁移流程](docs/migration.md)。不要直接在已有 Edge 上运行 `provision`。

| 入口 | 行为 |
|---|---|
| `make preflight` | 只读检查 OS、接口、SSH 端口、配置和 Docker backend |
| `make check` | Ansible `--check --diff`，展示计划；新主机缺失依赖时需先分阶段 bootstrap |
| `make bootstrap` | 安装缺失的运行时、Infra 工具与 Certbot；复用现有 Docker |
| `make security-check` / `security-verify` | 只读安全审计；需要先 bootstrap 安装审计工具 |
| `make security-apply` | SSH、UFW、双栈 INPUT/DOCKER-USER、Fail2ban、审计、内核及安全更新 |
| `make tls-bootstrap` | 首次 HTTP-01 申请证书，再切 TLS；不会降级现有 TLS |
| `make tls-check` / `tls-adopt` | 续期 dry-run / 显式接管单个证书续期配置 |
| `make infra-deploy` | 候选校验、仅 Edge 切换、失败恢复 |
| `make provision` | bootstrap → security → TLS → Edge → 本机验证 |
| `make verify` | 应用契约、Edge、TLS、ACME 映射和主机安全报告 |
| `make external-verify` | 从独立机器检查公网 HTTPS 和保护端口；覆盖所有解析到的 A/AAAA |
| `make migrate` / `migrate-verify` | 独立旧 Edge 切换 / 本机及外部迁移验收 |
| `make rollback RELEASE=<id>` | 恢复保留的 Edge 配置和镜像 |
| `make legacy-rollback RECEIPT=<id.json>` | 恢复指定迁移记录中的旧 Edge 和 restart policy |
| `make validate` | 单元测试、渲染、Lint、Ansible 语法校验 |

可以传入 `INVENTORY=... LIMIT=edge01`。外部验证指定新主机、不改变 DNS：

```bash
make external-verify PROBE_ARGS='--address 203.0.113.10 --address 2001:db8::10'
```

## 实现与验收

- Edge：官方 Nginx 镜像锁定摘要；只读文件系统、能力收敛、进程/内存/日志限制；保留 `/docs/`；支持 SSE 和 WebSocket；丢弃伪造转发头。
- 安全：主机 INPUT 和 Docker DOCKER-USER 双栈治理，匹配 DNAT 前的原始发布端口；只管理命名链，不清空其他规则；在 Docker 启动前加载并在启动后复核。
- 发布：配置与源码确定发布 ID，校验清单、`compose config`、`nginx -t` 后切换；部署和证书 reload 共用锁；保留事务记录和恢复入口。
- CI：YAML/Ansible/ShellCheck、配置及恢复逻辑、真实 Nginx/Compose、SSE/WebSocket、隔离网络命名空间双栈过滤、仓库 secret 扫描、锁定镜像的 HIGH/CRITICAL 可修复漏洞扫描。Actions 固定提交，权限仅 `contents: read`，不访问生产主机。

CI 证明配置及受控测试行为；服务器幂等性、真实 ACME、云防火墙、重启恢复和业务流量验收需要在目标服务器逐阶段完成。安全审计发现应用公开绑定时会失败，修复由应用拥有者在其独立部署流程中完成；Infra 仅提供网络防护，不改应用文件。

[架构](docs/architecture.md) · [部署](docs/deployment.md) · [安全](docs/security.md) · [TLS](docs/tls.md) · [迁移](docs/migration.md) · [回滚](docs/rollback.md) · [验收](docs/verification.md) · [版本记录](CHANGELOG.md)

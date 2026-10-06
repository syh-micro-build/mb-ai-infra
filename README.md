# mb-ai-infra

MicroBuild AI 基础设施工程，目标版本 **1.0.0**。管理 Edge、TLS、主机安全基线、Docker 暴露治理、Ansible IaC、迁移、部署、回滚、运行验证和 CI。

**应用升级不等于基础设施变更。** Sub2API 与 `mb-ai-docs` 通过 HTTP 部署契约连接 Infra，拥有独立仓库、镜像、部署目录和发布流程。本仓库不包含应用源码、镜像版本、数据库管理或应用 Compose，不写入 `/opt/sub2api`、`/opt/mb-ai-docs`。

```text
控制机 Bash + Docker → Runner (Python / Ansible / Collections)
                          │ SSH/sudo
                          ▼
                     Ubuntu Managed Node

Internet :80/:443 → Infra Nginx (Linux host network)
                    ├─ /docs/ → 127.0.0.1:8081/docs/
                    └─ /      → 127.0.0.1:8080/
```

生产机为纯 Managed Node，最低要求 Ubuntu **22.04 / 24.04**、SSH、公钥 sudo 账号和网络；系统 Python 缺失时由 bootstrap-zero 引导。Infra runtime 另需 systemd、Docker **iptables backend** 和 Compose **≥2.18**。现有 Docker 不会被替换、升级或重启；不支持的运行时会阻止自动安装。

运维控制端需要 Linux/WSL、Bash、可用的 Docker 和 SSH 材料；Python/Ansible/Collections 封装在 Runner 中。目标机不运行 CLI/Runner、不克隆仓库，不安装 Ansible、pip、venv、Make 或开发工具链。

## 开始

```bash
cp -R ansible/inventory/example ansible/inventory/local
# 修改 local/hosts.yml 和 local/group_vars/mb_ai.yml。
# 示例地址均为保留地址，不能直接用于生产。
# 先独立核验服务器指纹并写入 ~/.ssh/known_hosts。
export INFRA_SSH_KEY="$HOME/.ssh/infra_ed25519"
./infra init
./infra preflight
# 缺少 Python 时，预检只读阻止；显式引导后再次预检。
./infra bootstrap-zero
./infra preflight
./infra check
```

填写真实主机、非 root sudo 账号、SSH 端口、公网网卡、管理员 IPv4/IPv6 CIDR、域名和 ACME 邮箱。主机密钥检查始终开启，不自动信任未知指纹。加密私钥先加入 SSH agent 并取消 INFRA_SSH_KEY，其他凭据使用 Vault。`local/` 被 Git 忽略。init 只校验控制环境，不连接目标。

Runner 默认使用当前完整提交的 GHCR 镜像，main 合并后 CI 发布。PR 分支或发布前可用 `./infra init --build` 在控制端构建；后续命令复用固定本地 image ID。源代码包或指定摘要使用 `--image <ref或digest>`。详见 [Runner/CLI](docs/runner.md)。

新主机：先配置云防火墙、验证管理账号，再按应用各自流程部署两个应用，使契约可用，最后执行 `./infra provision`。该命令准备主机、安全基线、HTTP-01/TLS、Edge 和本机验证，不安装应用。DNS 的 A/AAAA 必须指向目标主机，公网 80 必须可达。完整外部验收仍需从另一台机器执行 `./infra external-verify`。

现有 `/opt/mb-ai-edge`：使用 [迁移流程](docs/migration.md)。不要直接在已有 Edge 上运行 `provision`。

| 入口 | 行为 |
|---|---|
| `./infra init [--build]` | 准备并固定控制端 Runner，验证本地 Inventory/SSH 材料 |
| `./infra bootstrap-zero` | 仅引导缺失的系统 Python 与 python3-apt；bootstrap/provision 自动包含 |
| `./infra preflight` | 只读检查 OS、接口、SSH 端口、配置和 Docker backend |
| `./infra check` | Ansible `--check --diff`，展示计划；新主机缺失依赖时需先分阶段 bootstrap |
| `./infra bootstrap` | 安装缺失的运行时、Infra 工具与 Certbot；复用现有 Docker |
| `./infra security-check` / `security-verify` | 只读安全审计；需要先 bootstrap 安装审计工具 |
| `./infra security-apply` | SSH、UFW、双栈 INPUT/DOCKER-USER、Fail2ban、审计、内核及安全更新 |
| `./infra tls-bootstrap` | 首次 HTTP-01 申请证书，再切 TLS；不会降级现有 TLS |
| `./infra tls-check` / `tls-adopt` | 续期 dry-run / 显式接管单个证书续期配置 |
| `./infra deploy` | 候选校验、仅 Edge 切换、失败恢复 |
| `./infra provision` | bootstrap → security → TLS → Edge → 本机验证 |
| `./infra verify` | 应用契约、Edge、TLS、ACME 映射和主机安全报告 |
| `./infra external-verify` | 从独立机器检查公网 HTTPS 和保护端口；覆盖所有解析到的 A/AAAA |
| `./infra migrate` / `migrate-verify` | 独立旧 Edge 切换 / 本机及外部迁移验收 |
| `./infra rollback <id>` | 恢复保留的 Edge 配置和镜像 |
| `./infra legacy-rollback <id.json>` | 恢复指定迁移记录中的旧 Edge 和 restart policy |
| `make validate` | 单元测试、渲染、Lint、Ansible 语法校验 |

可以传入 `--inventory FILE --limit edge01`。外部验证指定新主机、不改变 DNS：

```bash
./infra external-verify --address 203.0.113.10 --address 2001:db8::10
```

## 开发者接口

Makefile 保留为开发者接口。仅控制端开发环境需要 Linux/WSL、Python ≥3.12、venv/pip、Make、OpenSSH、ShellCheck，这些依赖不进入目标机。

```bash
python3 -m venv .venv
source .venv/bin/activate
make deps
make validate
make runner-test
```

## 实现与验收

- Edge：官方 Nginx 镜像锁定摘要；只读文件系统、能力收敛、进程/内存/日志限制；保留 `/docs/`；支持 SSE 和 WebSocket；丢弃伪造转发头。
- 安全：主机 INPUT 和 Docker DOCKER-USER 双栈治理，匹配 DNAT 前的原始发布端口；只管理命名链，不清空其他规则；在 Docker 启动前加载并在启动后复核。
- 发布：配置与源码确定发布 ID，校验清单、`compose config`、`nginx -t` 后切换；部署和证书 reload 共用锁；保留事务记录和恢复入口。
- CI：YAML/Ansible/ShellCheck、配置及恢复逻辑、真实 Nginx/Compose、SSE/WebSocket、双栈过滤、Runner/真实 SSH 引导、secret 与镜像漏洞扫描。Actions 固定提交；检查仅 contents:read，GHCR publish job 单独授予 packages:write。PR 不发布、不访问生产主机。

CI 证明配置及受控测试行为；服务器幂等性、真实 ACME、云防火墙、重启恢复和业务流量验收需要在目标服务器逐阶段完成。安全审计发现应用公开绑定时会失败，修复由应用拥有者在其独立部署流程中完成；Infra 仅提供网络防护，不改应用文件。

[架构](docs/architecture.md) · [部署](docs/deployment.md) · [安全](docs/security.md) · [TLS](docs/tls.md) · [迁移](docs/migration.md) · [回滚](docs/rollback.md) · [验收](docs/verification.md) · [版本记录](CHANGELOG.md)

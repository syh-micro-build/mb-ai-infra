# Runner 与统一运维入口

`./infra` 在 Linux/WSL 控制机运行，把 Ansible、Python ≥3.12、PyYAML、Jinja2 和 Collections 放在一次性的 Docker 容器中。目标机通过 SSH 接受管理，最低条件为 Ubuntu 22.04/24.04、SSH、公钥 sudo 账号和可访问 Ubuntu 软件源的网络。目标机不运行 Runner，不克隆仓库，不安装 Ansible、pip、venv、Make 或 lint 工具；只保留系统 Python、python3-apt 与原有 Infra 运行组件。

## 本地准备

控制机准备 Bash、可用的 Docker Engine/Linux containers，以及已加载的 SSH agent 或一个权限 0600 的未加密私钥。仓库可由 Git 获取；源代码压缩包需要显式选择镜像摘要。Windows 使用 WSL 内的仓库、密钥与 Unix agent socket，不能直接转发 Windows 命名管道。远程 Docker daemon 无法直接读取本机的 bind-mount 文件，因此本入口使用控制机本地 Docker。

```bash
cp -R ansible/inventory/example ansible/inventory/local
# 填写真实主机、账号、端口、接口、管理员 CIDR、域名与 ACME 邮箱。
# 确认 ~/.ssh/known_hosts 中的服务器指纹已通过云控制台等独立通道核验。
export INFRA_SSH_KEY="$HOME/.ssh/infra_ed25519"
# 加密私钥使用 ssh-agent：先 ssh-add，再 unset INFRA_SSH_KEY。
./infra init
./infra preflight
```

`init` 获取 Runner，验证本地 Inventory、SSH 材料、主机指纹文件及 playbook 语法，固定本地镜像 ID。它不连接目标机，不声称 SSH/sudo 或主机状态已经通过。所有实际 SSH 操作强制主机密钥检查和公钥认证，拒绝 root、local/container 连接与回环目标。入口不自动运行 ssh-keyscan 或接受未知指纹。非默认 SSH 端口的 known_hosts 项应为 `[主机]:端口`。

默认镜像是 `ghcr.io/syh-micro-build/mb-ai-infra-runner:sha-<完整 checkout 提交>`。合并到 main 后，发布 workflow 创建该镜像。PR 分支未发布时，或者 GHCR 不可用时，可在控制机本地构建：

```bash
./infra init --build
./infra preflight
```

成功的 init 把提交与镜像 ID 写入被忽略的 `.cache/runner-image`；后续命令复用同一镜像。切换提交后该缓存不再自动选用，应重新 init。镜像内校验 `requirements-runner.txt`、`ansible/requirements.yml` 和 VERSION，发现旧工具链会阻止运行并提示重建。容器运行时不进行 pip/Collections 下载。工作区可以有正在审阅的配置变更；部署使用当前工作区文件。

源代码包、离线镜像或明确发布版本可用 `--image` / `INFRA_RUNNER_IMAGE` 指定。跨控制机复现应保存 registry digest；本地 image ID 只适用于当前 Docker daemon。

```bash
./infra init --image ghcr.io/syh-micro-build/mb-ai-infra-runner@sha256:<已验证摘要>
./infra preflight
```

GHCR 第一次创建的包可能为私有，仓库管理员应设置包可见性/Actions 权限；私有包在控制机先 `docker login ghcr.io`，使用具备 read:packages 的凭据。凭据仅供控制机 Docker 拉取，不进入 Runner 或目标机。init --build 可用于发布前验证，无需 registry 凭据。

## 命令与配置

| CLI | 实际入口/语义 |
|---|---|
| `init` | 本地校验与镜像固定；不接触目标 |
| `version` | 显示容器内 Infra/Python/Ansible/Collections 版本 |
| `preflight` | 只读 raw 检查 Python，存在时再 gather_facts 与主机预检 |
| `check` | provision 的 `--check --diff` 计划；不安装 Python |
| `bootstrap-zero` | raw 引导系统 Python 与 apt bindings，然后 gather_facts |
| `bootstrap` | bootstrap-zero → Infra runtime、Docker、Certbot |
| `provision` | bootstrap → security → TLS/Edge → verify；仅新主机 |
| `deploy` / `infra-deploy` | 已有证书下的 Edge 部署 |
| `verify` | 本机契约、Edge/TLS、安全报告 |
| `security-check` / `security-verify` | 安全审计 |
| `security-apply` | 单独应用主机安全基线 |
| `tls-bootstrap` / `tls-check` / `tls-adopt` | 首次签发 / 续期测试 / 显式接管 |
| `migrate` | 指定旧 Edge 的受控切换 |
| `migrate-verify` | 本机 verify 成功后从控制机执行 external-verify |
| `rollback <release>` | 恢复保留的 Edge 发布 |
| `legacy-rollback <receipt.json>` | 恢复迁移记录中的旧容器 |
| `external-verify` | 从独立控制机检查公网；无需 SSH 密钥挂载 |

`migrate-verify` 只有在控制机处于独立外部网络时才能作为公网证据。它不执行迁移。失败退出码原样返回；未知命令、缺失参数、空的主机选择和无效 Inventory 不被当作成功。

```bash
./infra preflight --inventory /secure/site/hosts.yml --limit edge01
./infra bootstrap-zero --check
./infra security-apply --ask-become-pass
./infra rollback 1.0.0-<source-hash>-<config-hash>
./infra external-verify --address 203.0.113.10 --address 2001:db8::10
```

默认 Inventory 为 `ansible/inventory/local/hosts.yml`，site 为同目录 `group_vars/mb_ai.yml`，LIMIT 为 mb_ai。支持 `--inventory`、`--limit`、`--ssh-key`、`--known-hosts`、`--image` 与 `--vault-password-file`，以及帮助中列出的等价环境变量。允许 Ansible `--check`、`--diff`、`--ask-become-pass`、`--ask-vault-pass`、`-v`…`-vvvv`；高级开发操作仍使用 Makefile。sudo 密码可放在 Vault 中，密码文件单独只读挂载；交互式密码需要控制端终端，自动化应使用 Vault 或已配置的免密码 sudo。

```bash
./infra init --vault-password-file /secure/infra-vault-password
./infra provision --vault-password-file /secure/infra-vault-password
```

Runner 默认无额外 Linux capability、只读根文件系统、no-new-privileges、进程和内存限制。仓库、Inventory、选定私钥/agent socket、known_hosts、Vault 密码文件只读挂载，SSH 临时文件写入 tmpfs，外部报告写入控制机 `reports/`。它不挂载 Docker socket，不使用 privileged 或 host network，也不挂载整个 ~/.ssh。agent 转发只用于控制机内的 Runner，SSH 不启用远端 agent forwarding。共享 agent 仍授权 Runner 使用其中的身份，应只加载本次需要的密钥。

## Bootstrap Zero 与发布

bootstrap-zero 使用 `gather_facts: false` 和 Ansible raw，通过已有 SSH/sudo 检查发行版及 `/usr/bin/python3`。只在系统 Python/apt bindings 缺失时执行 apt update 和 `apt-get install --no-install-recommends python3 python3-apt`，不执行系统升级、不安装控制端工具链。Ubuntu 22.04 的系统 Python 3.10 与 24.04 的 3.12 可直接使用，不要求目标机升级到控制端 Python 版本。现有解释器就绪时重复执行 changed=0。

preflight 不自动引导 Python。没有 Python 时，preflight / check 明确 BLOCKED，需先显式运行 bootstrap-zero；bootstrap / provision 自动包含该阶段。check mode 无法模拟没有解释器的事实收集，不会报告虚假的完整计划。生产主机仍需 systemd；bootstrap-zero 的 SSH 测试不替代完整主机基线验收。

Runner CI 在 PR/分支构建、扫描并通过 SSH 测试隔离 Ubuntu 22.04/24.04；覆盖无 Python、check/preflight 不变更、Unsupported OS 拒绝、重复执行、agent 与应用目录标记。主机测试在 amd64 上执行。main push 或与 VERSION 匹配的 vX.Y.Z tag 才发布 linux/amd64、linux/arm64 镜像，PR 与手动测试不发布。包写入权限只授予 publish job；无生产密钥或 SSH 自动部署。arm64 镜像在发布时构建，不把它描述为已完成真实主机验收。

发布包括完整提交 tag、main tag；版本 tag 仅在显式打 release tag 时创建，不自动覆盖版本。运维默认使用提交 tag，不使用 main 作为版本依据。Runner 发布不部署 Edge、不修改应用版本，不自动创建 release/tag。

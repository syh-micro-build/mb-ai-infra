# 迁移与旧 Edge 切换

应用迁移、备份恢复、数据库升级与 Docs 发布由各自 owner 完成。此工具只迁移 Infra Edge；不会传输或修改应用目录。新服务器需先具备相同应用契约，证书按独立安全流程签发/传输。

现有 `/opt/mb-ai-edge` 到 Infra 的步骤：

1. 记录当前域名、A/AAAA、HTTPS/Docs 状态、证书 cert-name、续期 authenticator/webroot、占用 80/443 的服务和容器。检查 GitHub PR/CI，再填写 inventory。
2. `./infra preflight`、审阅 `./infra check`；执行 `./infra bootstrap`、`./infra security-apply`。旧 Docker 和旧 Nginx 容器继续运行；不要填入未经确认的 legacy_services，也不要先停止旧 Edge。
3. 只读检查 `docker ps` 与旧 Edge 的 Compose labels、Image、restart policy，明确其 container ID/name 和 `com.docker.compose.project`，填 `infra_legacy_edge_container` 与 `infra_legacy_edge_project`。
4. 核对 `/etc/letsencrypt/live/<domain>/fullchain.pem` 与私钥存在，契约可用。`./infra migrate` 先渲染候选、验证配置和应用；在停旧 Edge 前，将旧目录归档并保存容器 ID、restart policy 和事务记录。
5. 工具仅对指定、label 匹配且使用官方 Nginx 镜像的旧 Edge 设置 restart=no、stop。它保留旧目录和容器，启动 Infra Edge 并验证 TLS、路由、ACME；失败时停 Infra 并恢复旧容器与 restart policy。
6. 成功后 `./infra tls-adopt` / 按 tls.md 处理旧 Certbot；`./infra tls-check`；`./infra verify`；从独立机器执行 `./infra external-verify`。记录迁移 receipt 文件名。
7. 受控验证服务器重启，确认新 Edge 恢复、旧 Edge 不自启；再做重复应用/部署的幂等性检查。保留旧目录、容器和私有归档，直到业务验收完成。

如果切换成功但业务验收失败，使用 `./infra legacy-rollback <迁移记录.json>`。该入口恢复已记录的旧容器及 restart policy，不解包覆盖旧目录，不触及应用。恢复后重新验证旧 TLS、续期和公网端口。

旧 Edge 目录若是符号链接，或指定容器属于应用项目，工具拒绝迁移。旧镜像若为自定义镜像或托管服务，应另行制定迁移步骤。工具不猜测容器身份，也不自动停宝塔或其他主机 Nginx。

换服务器：新主机先 bootstrap/security，应用 owner 各自迁移应用；证书通过安全路径准备；部署 Infra；用 `./infra external-verify --address <新IPv4> --address <新IPv6>` 在 DNS 切换前验证；确认 A/AAAA、云安全组和回退窗口后，由 DNS owner 切换。没有 provider API 或跨主机私钥自动复制。

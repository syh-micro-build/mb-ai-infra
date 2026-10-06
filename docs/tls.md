# TLS 与续期

首次签发要求 DNS A/AAAA 正确、公网 TCP 80 可达、ACME 邮箱真实、80/443 没有其他占用者。`make tls-bootstrap` 先运行不代理应用的 HTTP-01 Edge，签发成功后用另一发布 ID 切换 TLS。失败保留 HTTP-01 阶段供修正 DNS/防火墙后重试，不生成假证书，不忽略信任校验，不把已有 TLS 降级。

证书完整目录只读挂载为 `/etc/letsencrypt`，保留 live → archive 链接；私钥由 Nginx root master 读取，worker 使用 nginx 用户。Certbot 在主机运行，不挂 Docker socket。renewal deploy hook 调用 `infra.py reload`，与部署共用锁，先 `nginx -t` 再 reload。`certbot.timer` 由 Ansible启用。

既有证书可以复用，但必须单独验证其续期配置。旧 Edge 的 webroot 或 standalone authenticator 不会被普通 deploy 自动改写。迁移完成后，Certbot ≥2.3 使用 `make tls-adopt`：针对一个 cert-name 以 staging 续期验证新 webroot，成功后保存新设置。再运行 `make tls-check`，完整测试续期和 deploy hook。

Ubuntu 22.04 的旧 Certbot 若不支持 reconfigure，在确认域名和证书名称后，按 [Certbot 官方文档](https://eff-certbot.readthedocs.io/en/stable/using.html#modifying-the-renewal-configuration-of-existing-certificates) 手动分两步：

```bash
sudo certbot renew --cert-name ai.mbuild.top --webroot \
  --webroot-path /var/lib/mb-ai-infra/acme --dry-run
# 上一步通过后，受控执行一次真实续期，保存新续期选项。
sudo certbot renew --cert-name ai.mbuild.top --webroot \
  --webroot-path /var/lib/mb-ai-infra/acme --force-renewal
```

不要反复强制签发，也不要直接编辑 renewal 配置。主机中其他域名证书不被该入口选中。恢复旧 Edge 后，续期 webroot 也应恢复/重新验证，不能仅恢复容器就声称续期完整。

本机 smoke 检查系统信任链、域名、剩余有效期（默认 ≥7 天）、HTTP→HTTPS 目的地址、两应用路由和 HTTP-01 映射。`tls-check` 使用 staging dry-run 证明真实 ACME 可达；本机 ACME 文件映射检查不能替代公网签发验证。CI 的自签名证书仅用于隔离测试，通过显式测试 CA 验证，没有使用 `curl -k`。

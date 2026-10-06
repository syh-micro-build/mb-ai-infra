# 回滚与失败恢复

Edge 发布事务包含配置检查、切换、启动、健康验证。失败时恢复上一有效 Edge；首次部署失败则停止新 Edge；迁移失败额外恢复旧 Edge restart policy 和容器。命令返回非零，事务状态为 reverted 或 recovery-failed。

```bash
# 在目标主机查看现有发布和记录，不编辑文件。
sudo readlink -f /opt/mb-ai-infra/current
sudo ls /opt/mb-ai-infra/releases
sudo ls /opt/mb-ai-infra/transactions
# 控制端选择明确的保留版本。
make rollback RELEASE=1.0.0-<source-hash>-<config-hash>
make verify
make external-verify
```

回滚候选也检查清单、应用契约、Nginx 语法、可信 TLS 和 HTTP 路由；失败则恢复回滚前的 Edge。保留旧镜像缓存或确保镜像 registry 可达；版本被删除、校验不符、证书失效或应用不可达时，不强制切换。

旧 Edge 迁移恢复使用单独入口：

```bash
make legacy-rollback RECEIPT=20261006T080000Z-<id>.json
```

它停止当前 Infra Edge、恢复 receipt 中的同一旧容器和 restart policy，成功后移除 Infra current 指针。如果旧容器启动失败，会尝试重新启动 Infra Edge并返回错误。检查原服务、证书和续期 webroot，再完成外部验收。

`recovery-failed` 不被掩盖。保留当前 SSH 会话，读取 root-only receipt 中的 candidate、previous、legacy ID 和 recovery_errors；修复 Docker/证书/端口占用后，使用明确 release 或 receipt 重新恢复。工具保留全部配置与旧目录，避免靠猜测执行全局 down/prune。

Edge 回滚不回滚系统包、SSH、UFW、云安全组、Docker runtime、Certbot 私钥或应用数据。主机基线变更以独立 inventory 版本重新 plan/apply；SSH drop-in 的原配置由 Ansible backup 保留，可在现有会话/云控制台恢复并用 `sshd -t` 验证后 reload。Docker guard 恢复使用原 inventory 策略并重新 apply，不清空全机规则。证书恢复必须同时验证 live/archive 链接、renewal 设置及权限。

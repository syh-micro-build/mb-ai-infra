# Changelog

## 1.0.0 — 2026-10-06

- 定义 Sub2API、mb-ai-docs 的独立部署契约和不可写应用边界。
- 增加 Nginx Edge、HTTP-01/TLS、SSE/WebSocket、Docs 路径保留及可信转发头策略。
- 增加 Ubuntu Ansible 主机准备、SSH/UFW、双栈 Docker 原始端口治理、Fail2ban、审计及安全更新基线。
- 增加候选预校验、发布清单、原子指针、事务记录、Edge 回滚及独立旧 Edge 迁移恢复。
- 增加 Make 操作入口、本机/外部验收、续期 dry-run/接管流程和服务器分阶段运行文档。
- 增加固定提交的 GitHub Actions、配置/恢复/真实 Edge/双栈 DNAT 测试、secret 与镜像漏洞扫描。

版本为实施目标；生产签发、云安全组、服务器幂等性和重启验收由后续服务器验证确认。未自动部署到生产，也未创建 release/tag。

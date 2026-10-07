# Changelog

## Unreleased

- 默认关闭 SSH pipelining，保留连接复用，补齐需要密码的 sudo 认证测试。
- 从不提权的 raw SSH 会话读取实际连接记录，严格校验地址、端口与管理员 CIDR；缺失或畸形时停止安全操作。
- 移除 reset_connection 不支持的条件判断，修复缺失安全包和 guard unit 时的检查模式依赖。
- 交互式密码要求真实终端，拒绝管道/重定向；CI 用随机临时密码验证无回显。
- 完整 check 覆盖 Ubuntu 双版本、两种 sudo 模式、重复计划、主机零配置写入和来源拒绝测试，Runner 发布等待全部校验。

## 1.0.0 — 2026-10-06

- 增加 Dockerized Infra Runner、统一 ./infra 运维入口、提交镜像固定与只读 SSH 材料挂载，保留 Makefile 开发接口。
- 增加无 Python 的 Ubuntu raw bootstrap-zero；生产机只需系统 Python/apt bindings，不安装 Ansible/pip/venv/开发工具链。
- 增加 Runner 构建、SSH 双版本引导与幂等测试、漏洞扫描，以及 main/release tag 的 GHCR 发布流程。
- 定义 Sub2API、mb-ai-docs 的独立部署契约和不可写应用边界。
- 增加 Nginx Edge、HTTP-01/TLS、SSE/WebSocket、Docs 路径保留及可信转发头策略。
- 增加 Ubuntu Ansible 主机准备、SSH/UFW、双栈 Docker 原始端口治理、Fail2ban、审计及安全更新基线。
- 增加候选预校验、发布清单、原子指针、事务记录、Edge 回滚及独立旧 Edge 迁移恢复。
- 增加 Make 操作入口、本机/外部验收、续期 dry-run/接管流程和服务器分阶段运行文档。
- 增加固定提交的 GitHub Actions、配置/恢复/真实 Edge/双栈 DNAT 测试、secret 与镜像漏洞扫描。

版本为实施目标；生产签发、云安全组、服务器幂等性和重启验收由后续服务器验证确认。未自动部署到生产，也未创建 release/tag。

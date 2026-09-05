# Security Policy

## Supported Versions

| Version | Supported          |
| ------- | ------------------ |
| master  | :white_check_mark: |

## Reporting a Vulnerability

如果你发现 ProjectForge 存在安全风险，请通过 GitHub Security Advisories 私下报告：

- 使用仓库的 **Security > Private security reporting** 功能
- 或发送邮件至仓库维护者，标题统一使用 `[SECURITY] ProjectForge`

请勿在公开 issue 中提交包含 exploit 细节的报告。

## Security Boundaries

ProjectForge 当前的安全边界主要依赖两层：

1. **ProjectForge 应用层**
   - workspace 路径按 `project_id` / `run_id` 隔离
   - execution 前校验 workspace 可用性
   - post-execution 的 `allowed_paths` 检测

2. **Hermes execution sandbox**
   - 真实执行依赖 `bubblewrap` / `bwrap`
   - sandbox 内 Hermes 只能写入绑定挂载的 `/workspace`
   - 未安装 bwrap 时，真实 Hermes execution 会被明确阻止，不会降级运行

## Known Risks

- `bwrap` 未安装时，`run start` / `run resume` / `replan apply` 会直接失败，不会以无隔离方式执行。
- Hermes / coding agent 仍可能通过 sandbox 内的网络访问外部服务；当前未做网络层隔离。
- `.env`、API key、GitHub token 应视为机密，不要提交到版本库。
- workspace 生命周期管理、cleanup 策略仍在完善中。

## Safe Usage

- 不要在 `run_dir` 中手动放置指向外部目录的 symlink。
- 不要对不受信任的 JD / blueprint / task graph 直接执行，未经验证的输入可能诱导 agent 生成高风险操作。
- CI / 自动化环境应单独配置最小权限的 token，不要复用个人密钥。

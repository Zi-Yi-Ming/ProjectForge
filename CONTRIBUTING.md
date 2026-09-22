# Contributing

感谢你对 ProjectForge 感兴趣。以下是参与本项目的最小指引。

## 开发环境

```bash
git clone https://github.com/Zi-Yi-Ming/ProjectForge.git
cd ProjectForge
python -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"    # dev extra 含 fastapi，API 相关测试需要；与 CI 安装方式一致
```

## 运行测试

```bash
python -m compileall app
pytest
```

## 代码风格

- 保持现有模块结构，不要引入新的顶层目录。
- 修改业务代码时，同步检查 `README.md` 是否仍与真实行为一致。
- 不要为了测试通过而修改既有生命周期语义。

## 提交建议

- 建议按独立问题拆分提交：
  - Product Core 修复
  - Workspace isolation
  - CLI/API wiring
  - 文档/开源卫生
- commit message 请使用祈使句、英文、简明。

## 工作流

### 分支模型

trunk-based：`master` 是唯一长期分支，CI 覆盖 push 与 PR。

- 小改动（docs / config / 小 fix）：直接 commit 到 master
- 功能、有风险的改动、**一切 AI agent 产出**：分支 + PR，squash 合并
- 分支命名：`feat/`、`fix/`、`docs/`、`chore/release-x.y.z`

### AI agent 协作规则

- agent 产出永远进 PR，不直推 master——PR 是 agent diff 的 review gate
- 合并前本地必跑 `pytest`
- NPC（cnb-npc-skill）只派「按 spec 执行」的明确任务；探索性工作用本地 agent（Claude Code / AtomCode）

### CHANGELOG 纪律

- 每个 feature / fix 合入时，顺手在 `[Unreleased]` 加一行——不要攒到发布前再回忆
- CHANGELOG 转正是发布流程的**硬性第一步**

## 发布流程

1. `[Unreleased]` 非空 → 按 semver 政策定 minor / patch（0.x 阶段：能力变更 = minor，修复 = patch）
2. CHANGELOG 转正为 `[x.y.z] - YYYY-MM-DD`，并补 Documentation 条目（如元数据/README 变更）
3. `pyproject.toml` 版本号单独一个 `chore(release): x.y.z` commit，与功能 commit 分开
4. 创建 GitHub Release（notes 从 changelog 抄）→ 自动触发 `Publish to PyPI` 与 `Mirror to Gitee`
5. 等 `Publish to PyPI` 绿灯，**并到 pypi.org 核实版本与 summary**——CDN 有传播延迟，看到 workflow 绿不等于已生效

## 已知 CI 边界

- `ci.yml` 不安装 bwrap：真实执行路径的测试（约 20 个）在 CI 中 skip；Hermes 端到端依赖手动 VM 验证
- Windows 开发环境同样 skip 真实执行路径，属预期；文件锁已跨平台（fcntl / msvcrt）

## 注意

- 仓库支持 `pip install -e .`，安装后可直接使用 `projectforge` 命令；开发验证请以仓库 clone 方式为准。
- Hermes / bwrap 相关改动请单独标注，便于后续做 runtime verification。

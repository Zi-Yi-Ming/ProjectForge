# ProjectForge

[![PyPI](https://img.shields.io/pypi/v/jdforge.svg)](https://pypi.org/project/jdforge/)
[![Python](https://img.shields.io/pypi/pyversions/jdforge.svg)](https://pypi.org/project/jdforge/)
[![CI](https://github.com/Zi-Yi-Ming/ProjectForge/actions/workflows/ci.yml/badge.svg)](https://github.com/Zi-Yi-Ming/ProjectForge/actions/workflows/ci.yml)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://github.com/Zi-Yi-Ming/ProjectForge/blob/master/LICENSE)

> **契约优先的任务执行引擎：每条任务绑定可机器核验的验收标准，在沙箱与路径约束内执行，由独立验证者判定"完成"。**

LLM 很擅长写代码，但依然不擅长**证明自己写完了**。ProjectForge 把 "done" 从一句自报变成一份证据：每条任务的验收标准都绑定可机器执行的检查（`TEST` / `COMMAND` / `FILE` / `PATTERN`），执行被限制在 bubblewrap 沙箱与声明的 `allowed_paths` 内，验证器独立于执行器重新核验——全部通过，任务才允许标记完成。失败时生成重新规划提案，经人工批准后应用；蓝图永远不会悄悄改掉自己。

岗位 JD 是目前内置的**参考输入适配器**；契约 / 执行 / 验证这一层对输入来源无感知。

## 它解决什么问题

- **AI 提交 ≠ 满足要求**：验收若全靠人肉 review，"完成"就没有门槛
- **scope 悄悄漂移**：没有边界声明，就没有越界判定
- **"完成"凭当事方自报**：没有独立验证者，done 只是一句话
- **失败无归因**：要么盲目重试，要么蓝图被自动改坏
- **需求无从落到任务**：把需求文档翻译成有计划、有验证的任务路径，目前依赖人肉

## 与其他 AI 编程工具的差异

- 完成需要**证据**：验收标准是可执行的检查，不是自然语言描述
- 执行有**边界**：沙箱 + `allowed_paths`，`enforce` 模式下越界即失败
- 验证**独立于执行**：执行者不能给自己的完成盖章
- 重新规划**需人工批准**：蓝图与已完成任务不被自动修改
- 依赖缺失时 **fail-closed**：缺 sandbox 依赖拒绝启动，而不是降级放行

## 核心循环

```text
需求文档（JD 是当前参考适配器）
  ↓
能力画像（规划层）
  ↓
项目蓝图 → 任务依赖图（每条任务带契约）
  ↓
约束式执行（bwrap 沙箱 + allowed_paths）
  ↓
独立验证（测试 / scope / 逐条验收核验）
  ↓
DONE ｜ 重新规划（人工批准）→ resume
```

## 核心概念

### 契约与机器可验收标准（Acceptance Criteria）

每条任务的验收标准可绑定可机器核验的检查（`criterion_checks`）：

| 检查类型 | 核验内容 |
|---|---|
| `TEST` | 执行任务声明的测试（`test_paths` / `test_command`），以退出码为准 |
| `COMMAND` | 执行任意命令，以退出码为准 |
| `FILE` | 文件存在性 / 内容模式 |
| `PATTERN` | 工作区内容匹配 |

核验结论默认 `observe`（记录但不改终判）；`PROJECTFORGE_CRITERIA_MODE=require` 时，任何一条核验失败即阻断 DONE——声明的套件通过时任务才可达 DONE，否则保持保守 BLOCKED。

### 能力覆盖（规划层）

需求文档的能力画像（必备/加分技能、工程主题）被逐项映射到任务蓝图与任务图，形成"能力 → 任务"的覆盖关系；每条验收标准的核验结论会出现在产出文档里，作为"该能力确实被做出并验证"的证据。（历史上的"项目匹配度"打分随研究/参考库层一同退役，现不再产出。）

### 约束式执行（Constrained Execution）

在 Task Contract 约束内执行任务。真实执行跑在 bubblewrap sandbox 里，工作区之外的文件系统是只读的，
执行器无法越出工作区；此外任务可以声明 `allowed_paths` 来收窄可修改范围——
声明后即按声明校验（`PROJECTFORGE_SCOPE_MODE=enforce` 时越界判失败，
默认 `warn` 只记录不判死）。未声明 `allowed_paths` 的任务以工作区为边界。

### 验证（Validation）

独立验证任务产出，包括测试执行、scope 检查、验收标准核对，只有验证通过才能标记任务完成。
验证器在真实执行路径下同样运行于 bwrap 沙箱内，把工作区设为唯一可写、其余宿主只读挂载。

### 重新规划（Replan）

当任务失败或受阻时，生成失败分析、影响范围和重做建议，用户明确批准后才应用，不自动修改蓝图或已完成任务。

## 项目生命周期

```text
CREATED
  ↓
ANALYZING
  ↓
PLANNING
  ↓
READY
  ↓
EXECUTING
  ↓
COMPLETED / FAILED / BLOCKED
```

## 安装

要求 Python 3.10+。

**从 PyPI 安装（推荐）：**

```bash
pip install jdforge                 # CLI + 约束执行引擎（不含 Web API 栈）
pip install "jdforge[api]"          # 追加 REST API（FastAPI）支持
```

**开发方式（源码安装）：**

```bash
git clone https://github.com/Zi-Yi-Ming/ProjectForge.git
cd ProjectForge
pip install -e .
```

安装后可用 `projectforge` 命令（也可通过 `python -m app.cli.app` 调用）。

## 快速开始

### 1. 从需求文档到 READY（规划 + 审批）

```bash
# 规划：需求文档 -> PLANNING（生成蓝图与任务图，等待人工审批）
projectforge plan new ./jd.txt --planner rule --base-dir .runtime

# 审批计划：PLANNING -> READY（审批后才能执行）
projectforge plan approve <project_id> --base-dir .runtime
```

- `--planner rule`：离线规则 planner（默认，无需任何 key）
- `--planner llm`：LLM 生成蓝图与任务图，配置任意 OpenAI 兼容厂商即可：

```bash
export PROJECTFORGE_LLM_BASE_URL=https://api.stepfun.com/v1
export PROJECTFORGE_LLM_API_KEY=<your-key>
export PROJECTFORGE_LLM_MODEL=step-3.7-flash
```

LLM 输出经 schema 与任务图双重校验，失败自动回退规则版，命令不会失败。

### 2. 约束式执行

```bash
# 离线体验（无需 Hermes/bwrap）
projectforge run start <project_id> --base-dir .runtime --executor mock

# 真实执行（默认 hermes，要求 Linux + Hermes CLI + bwrap，见下）
projectforge run start <project_id> --base-dir .runtime

projectforge run show <project_id> <run_id> --base-dir .runtime
projectforge run cancel <project_id> <run_id> --base-dir .runtime
```

### 3. 失败 → replan → resume（人工审批）

```bash
projectforge replan create <project_id> <run_id> --base-dir .runtime
projectforge replan approve <project_id> <proposal_id> --base-dir .runtime
projectforge replan apply <project_id> <proposal_id> <run_id> --base-dir .runtime
projectforge run resume <project_id> <run_id> <proposal_id> --base-dir .runtime
```

完整离线演示（含注入失败与人工审批）：`python scripts/demo.py`，详见 [docs/demo.md](docs/demo.md)。
REST API 同样可用（`app.api.app:create_api`），运行与重新规划可由 HTTP 驱动。

### 运行真实执行（可选）

约束式执行通过 [Hermes Agent](https://github.com/NousResearch/hermes-agent) 在 bubblewrap sandbox 中完成，需要：

- Hermes CLI（`hermes` 在 PATH 中，且已完成模型提供商认证）
- bubblewrap（`bwrap`，Linux；Ubuntu 24.04+ 需为 bwrap 配置允许 unprivileged user namespace 的 AppArmor profile）

缺少任一依赖时执行会 fail-closed 拒绝启动；测试套件会自动跳过真实执行用例。

## 示例：JD 作为参考输入

### 输入 JD

```
Java 后端开发实习生

岗位要求：
- Java
- Spring Boot
- MySQL

加分项：
- Redis
- 单元测试
```

### JD 能力画像

岗位必备技能：
- Java
- Spring Boot
- MySQL

加分技能：
- Redis
- 单元测试

### 项目蓝图

1. 基础工程
2. 核心业务
3. 工程深度
4. 进阶能力

### 任务依赖图

- T01 项目初始化
- T02 数据模型设计
- T03 核心 REST API
- T04 Redis 缓存
- T05 单元测试

> 以上为概念示例。实际输出取决于需求文档输入、planner 后端（rule 或 llm）与用户选择的 Scope。

## 架构

```text
              需求文档（JD 为当前参考适配器）
                            │
                            ▼
                      ┌───────────┐
                      │ JDAnalyzer │
                      └─────┬─────┘
                            │
                            ▼
                    ┌─────────────────┐
                    │ Project Blueprint│
                    └────────┬────────┘
                             │
                             ▼
                       ┌───────────┐
                       │ TaskEngine │
                       └─────┬─────┘
                             │
                             ▼
                        Task Graph
                             │
                             ▼
                     Constrained Run
                             │
                   ┌─────────┴─────────┐
                   ▼                   ▼
              Validation            Replan
```

## 开发

```bash
# 运行测试
pytest

# 仅运行 Product Core 相关测试
pytest tests/test_project_core.py tests/test_workflow.py tests/test_run_control.py
```

## 配置

- `PROJECTFORGE_RUNTIME_DIR`：运行时根目录（默认 `./.runtime`）
- `PROJECTFORGE_TASK_TIMEOUT_SECONDS`：单任务执行器超时（默认 300 秒；最坏执行时间 = 超时 × 重试次数 3），也可用 `run start/resume --timeout` 覆盖
- `PROJECTFORGE_LLM_BASE_URL` / `PROJECTFORGE_LLM_API_KEY` / `PROJECTFORGE_LLM_MODEL`：配置任意 OpenAI 兼容厂商后，`plan new --planner llm` 可用；不配置则 LLM planner 自动回退规则版
- `PROJECTFORGE_SCOPE_MODE`：任务级路径约束的强制模式。`warn`（默认）只把越界记录进验证 warning，不判失败；`enforce` 才把越界判为 `SCOPE_VIOLATION`。仅对声明了 `allowed_paths` 的任务生效
- `PROJECTFORGE_CRITERIA_MODE`：可机器核验的验收标准（`criterion_checks`）模式。`observe`（默认）记录每条准则的核验结论但不改变任务终判；`require` 才让失败的核验阻断 DONE
- `PROJECTFORGE_VALIDATOR_SANDBOX`：验证器是否在 bwrap 沙箱内执行 agent 写出的测试。默认开（仅在有 bwrap 的 Linux 真实执行路径生效，mock/无 bwrap 自动不沙箱）；`0|false|no|off` 显式关闭
- `PROJECTFORGE_PARALLEL`：`1|true|yes|on` 时，一个 ready wave 里的独立任务用 git worktree 并发执行、再合并回共享工作区并做集成重验证。默认关（保持串行）；需 Linux + bwrap
- `PROJECTFORGE_MAX_PARALLEL_WORKERS`：并发 wave 的最大 worker 数（默认由 wave 宽度决定）
- `PROJECTFORGE_ROLLBACK_ON_FAILURE`：`1|true|yes|on` 时失败任务回滚其半成品（`git reset --hard` + 工作树清理，**破坏性**，默认关）
- `PROJECTFORGE_MAX_RUN_SECONDS`：整轮运行的墙钟预算，超限以 `TIME_BUDGET_EXCEEDED` 收束。未设=不限（默认）
- `PROJECTFORGE_EVENT_MAX_FILE_BYTES`：事件日志按大小滚动为 `events-*.jsonl` 分片。未设=不滚动（默认，因会改变磁盘布局）

## 项目状态

- Product Core（需求 → 蓝图 → 任务图）：stable，测试覆盖完整
- CLI / API：stable（Python 3.10–3.12 CI）
- 约束式执行：**v0.2 起可用**。mock 后端全链路已验证；Hermes 后端在 Linux + bwrap sandbox 内端到端验证（含真实 LLM 调用），见 [docs/demo.md](docs/demo.md)
- 确定性验证：任务可声明 `test_paths` / `test_command`，验证器真实执行测试；声明的套件通过时任务可达 DONE，否则保持保守 BLOCKED。验收标准还可绑定 `criterion_checks`（TEST/COMMAND/FILE/PATTERN）逐条机器核验，默认 `observe`（只记录裁决），`require` 才会让失败的核验阻断 DONE
- 沙箱隔离：真实执行路径下 agent 与验证器都在 bwrap 内运行（文件系统 / pid / ipc 隔离，**与宿主共享网络**）。验证器沙箱把工作区设为唯一可写、其余宿主**只读挂载**——越界写会被挡住，但宿主文件（含家目录）对沙箱内测试仍可读；真网络/读隔离未实现
- 并行执行（opt-in）：`PROJECTFORGE_PARALLEL=1` 时，就绪波内互相独立的任务在各自 git worktree 并发执行、合并回共享工作区，并**对集成后的工作区重跑验证**（合并冲突或集成失败 → 该任务 FAILED）；worktree/分支在异常路径也会兜底回收。需 Linux + bwrap，默认关
- 项目匹配度 / 研究-参考库层：**已退役**（研究层不再产出，`project_fit` 不再计算）；能力覆盖改由"能力→任务"映射与逐条验收核验体现
- cancel：自 v0.2 起真正中断执行（任务间检查点，取消标志跨进程持久）
- v0.2.0 破坏性变更：`--base-dir` 语义改为运行时根（`projects/`、`runs/`、`workspaces/`）；v0.1.x 自定义布局不自动迁移
- Web UI / 多用户 / 云执行：未实现

## 相关项目

同作者的 verification-first agent tooling 系列：

- [step-pilot](https://github.com/Zi-Yi-Ming/step-pilot)：为小模型设计的终端 coding agent，完成前必须跑验收命令、交证据
- [miniprogram-automator-next](https://github.com/Zi-Yi-Ming/miniprogram-auto-test)：修复官方小程序自动化 SDK 两处坏掉能力的适配层

## License

MIT

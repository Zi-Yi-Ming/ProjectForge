# ProjectForge

> 基于岗位 JD 的工程项目教练与约束式执行引擎

ProjectForge 将一份岗位 JD 转化为结构化、可验证的工程项目路径：分析能力画像、计算项目匹配度、生成项目蓝图与任务依赖图，并在约束下推进执行与重新规划。它的目标不是生成“能跑就行”的代码，而是帮你从岗位要求出发，得到一条可以向面试官展示的、经过计划与验证的真实项目路径。

## 它能解决什么问题

- 看到 JD 后不知道应该做一个什么样的项目才能精准命中岗位要求
- 自己从零设计项目容易 scope 失控，要么太简单无法体现深度，要么过于宏大无法完成
- 即使有了项目 idea，也不知道如何拆解成可执行、可验证的学习任务
- 让 AI 直接写代码容易失控：代码可能跑偏、超出 scope、或缺少工程约束
- 无法判断生成的代码是否真的满足 JD 要求，也缺少独立验证机制

## 与通用 AI 编程助手的差异

- 起点是真实 JD，不是凭空想需求
- 项目设计来自能力匹配与工程约束，不是拍脑袋
- 任务拆解、执行、验证、重新规划全部受工程控制面约束
- 用户可以审查、确认、调整，不是黑箱

## 核心流程

```text
岗位 JD
  ↓
JD 能力画像
  ↓
项目匹配度
  ↓
项目蓝图
  ↓
任务依赖图
  ↓
约束式执行
  ↓
验证 / 重新规划
```

## 核心概念

### JD 能力画像（JD Profile）

从岗位描述中提取结构化能力要求，包括技术栈、工程经验、软技能等，作为后续匹配与规划的输入。

### 项目匹配度（Project Fit）

将 JD 能力画像与项目研究结果对照，输出匹配强度、能力缺口、建议的工程方向。

### 项目蓝图（Project Blueprint）

定义项目的工程架构、核心模块、技术选型、交付边界和面试表达点，是任务拆解的上游依据。

### 任务依赖图（Task Graph）

将蓝图拆成有依赖关系、可执行、可验证的任务序列，明确每个任务的输入、输出、验收标准和工程边界。

### 约束式执行（Constrained Execution）

在 Task Contract 约束内执行任务，限制允许修改的文件、测试范围和工程边界，避免执行过程偏离目标。

### 验证（Validation）

独立验证任务产出，包括测试执行、scope 检查、验收标准核对，只有验证通过才能标记任务完成。

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

```bash
git clone https://github.com/Zi-Yi-Ming/ProjectForge.git
cd ProjectForge
pip install -e .
```

安装后可用 `projectforge` 命令（也可通过 `python -m app.cli.app` 调用）。

## 快速开始

### 1. 从 JD 到 READY（一条命令）

```bash
projectforge plan ./jd.txt --planner rule --base-dir .runtime
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

## 示例

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

### 项目匹配度

匹配较强：
- Java
- Spring Boot
- MySQL

能力缺口：
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

> 以上为概念示例。实际输出取决于 JD 输入、研究结果和用户选择的 Scope。

## 架构

```text
                    Job Description
                           │
                           ▼
                     ┌───────────┐
                     │ JDAnalyzer │
                     └─────┬─────┘
                           │
                           ▼
                     ┌────────────┐
                     │ProjectMatch│
                     └─────┬──────┘
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
- `PROJECTFORGE_LLM_BASE_URL` / `PROJECTFORGE_LLM_API_KEY` / `PROJECTFORGE_LLM_MODEL`：配置任意 OpenAI 兼容厂商后，`plan --planner llm` 可用；不配置则 LLM planner 自动回退规则版

## 项目状态

- Product Core（JD → 蓝图 → 任务图）：stable，测试覆盖完整
- CLI / API：stable（Python 3.10–3.12 CI）
- 约束式执行：**v0.2 起可用**。mock 后端全链路已验证；Hermes 后端在 Linux + bwrap sandbox 内端到端验证（含真实 LLM 调用），见 [docs/demo.md](docs/demo.md)
- 确定性验证：任务可声明 `test_paths` / `test_command`，验证器真实执行测试；声明的套件通过时任务可达 DONE，否则保持保守 BLOCKED
- cancel：自 v0.2 起真正中断执行（任务间检查点，取消标志跨进程持久）
- 沙箱隔离：文件系统 / pid / ipc 隔离，**与宿主共享网络**（真网络隔离需 slirp4netns，未实现）
- v0.2.0 破坏性变更：`--base-dir` 语义改为运行时根（`projects/`、`runs/`、`workspaces/`）；v0.1.x 自定义布局不自动迁移
- Web UI / 多用户 / 云执行：未实现

## License

MIT

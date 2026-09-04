# 项目架构

## 产品架构

ProjectForge 采用 Product Core 作为产品级唯一 mutation 入口，所有 CLI 和 API 操作都必须经过 Product Core。

```text
Future CLI
     │
Future API
     │
     ▼
Product Core
     │
     ▼
Existing P5–P21
```

CLI 和 API 都必须经过 Product Core。禁止绕过 Product Core 直接调用底层 Agent / Orchestrator / Persistence。

## Project Aggregate Root

Project 是产品级 Aggregate Root。

```text
Project
 ├── JDProfile (reference)
 ├── ProjectFit (reference)
 ├── ProjectBlueprint (reference)
 ├── TaskGraph (reference)
 ├── ExecutionRun(s) (reference)
 ├── ReplanProposal(s) (reference)
 ├── Artifact(s) (reference)
 └── Event(s) (append-only)
```

Project 不复制完整对象，而是持有稳定引用。底层对象仍由各自模块管理。

## 项目生命周期

### 项目状态

```text
CREATED → ANALYZING → PLANNING → READY → EXECUTING → COMPLETED
                                                    ↘ FAILED / BLOCKED
```

| 状态 | 含义 | 允许的操作 |
|------|------|------------|
| CREATED | 项目已创建，JD 未分析 | 编辑 JD、分析 JD、删除 |
| ANALYZING | JD 分析中 | 等待 |
| PLANNING | 项目蓝图与任务依赖图生成中 | 等待 |
| READY | 用户已确认，等待启动执行运行 | 启动执行、编辑计划 |
| EXECUTING | 执行运行进行中 | 查看任务、查看事件 |
| COMPLETED | 所有 required 任务已完成 | 查看结果 |
| FAILED | 执行运行失败 | 查看错误、重试 |
| BLOCKED | 等待重新规划批准 | 审核重新规划、取消 |

### 执行运行状态

```text
PENDING → RUNNING → COMPLETED
                      ↘ FAILED / BLOCKED
```

## 状态迁移规则

Project 状态迁移必须经过集中式生命周期控制。

合法迁移：
- CREATED → ANALYZING
- ANALYZING → PLANNING
- PLANNING → READY
- READY → EXECUTING
- EXECUTING → COMPLETED
- EXECUTING → FAILED
- EXECUTING → BLOCKED
- BLOCKED → EXECUTING（用户批准重新规划后恢复执行）
- BLOCKED → FAILED（用户拒绝重新规划后）

非法迁移示例：
- COMPLETED → ANALYZING
- READY → CREATED
- EXECUTING → CREATED

终端状态保护：
- COMPLETED / FAILED 为终端状态，不允许迁移到其他状态。

## 活跃执行运行约束

一个 Project 同时只能存在一个活跃执行运行。

再次创建执行运行时，如果已有 RUNNING 的执行运行，必须被 Product Core 拒绝。

## 事件模型

Event 是 immutable audit log，不是 Event Sourcing。

当前 JSON persistence 仍是 state source of truth。

Event 必须支持：
- 追加写入
- 不允许修改
- 不允许删除
- crash 后通过文件存在性恢复

## 错误模型

统一产品级错误：

| Error Code | 用户含义 | 底层原因 | 可恢复 |
|------------|----------|----------|--------|
| PROJECT_NOT_FOUND | 项目不存在 | load 时 missing | 否 |
| INVALID_PROJECT_STATE | 项目状态不允许此操作 | state transition 非法 | 否 |
| INVALID_STATE_TRANSITION | 状态迁移非法 | transition 不在合法矩阵 | 否 |
| PROJECT_ALREADY_EXISTS | 项目已存在 | create 时 duplicate | 否 |
| ACTIVE_RUN_EXISTS | 已有活跃执行运行 | active run invariant | 是（Cancel 后） |
| COMMAND_NOT_ALLOWED | 命令不允许 | precondition 不满足 | 否 |
| PERSISTENCE_ERROR | 持久化错误 | IO / JSON 错误 | 否 |

## 持久化架构

```text
.runtime/
└── projects/
    └── <project_id>/
        ├── project.json
        ├── jd.json
        ├── blueprint.json
        ├── task_graph.json
        └── runs/
            └── <run_id>/
                ├── execution.json
                ├── tasks/
                ├── events/
                ├── replans/
                └── artifacts/
```

Product Core 不直接操作文件 IO，通过 persistence abstraction 访问。

## MVP Scope

### MUST HAVE
1. Project 创建与加载
2. Project lifecycle 状态机
3. Command validation
4. Active Run invariant
5. Domain errors
6. Persistence integration
7. CLI 完整闭环

### NOT MVP
- FastAPI / HTTP API
- Web UI
- Event Store / Event persistence
- Run Control（resume/cancel）
- Replan approval
- Pause
- Auth / Multi-user
- Cloud execution

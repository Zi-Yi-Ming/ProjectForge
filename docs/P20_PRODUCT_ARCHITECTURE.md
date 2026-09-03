# P20 Product Architecture

> 本阶段为产品核心架构与契约冻结，不实现业务代码。

---

## 1. Product Core 定位

Product Core 是整个产品的唯一产品级 mutation 入口。

```text
Future CLI
     │
Future API
     │
     ▼
Product Core
     │
     ▼
Existing P5–P18
```

CLI 和 API 都必须经过 Product Core。禁止绕过 Product Core 直接调用底层 Agent / Orchestrator / Persistence。

---

## 2. Project Aggregate Root

Project 是产品级 Aggregate Root。

### Project 引用关系

```text
Project
 ├── JDProfile (reference)
 ├── ResearchOutput (reference)
 ├── ProjectFit (reference)
 ├── ProjectBlueprint (reference)
 ├── TaskGraph (reference)
 ├── ExecutionRun(s) (reference)
 ├── ReplanProposal(s) (reference)
 ├── Artifact(s) (reference)
 └── Event(s) (append-only)
```

Project 不复制完整对象，而是持有稳定引用。底层对象仍由各自模块管理。

---

## 3. Project Lifecycle

### Project Status

```text
CREATED → ANALYZING → PLANNING → READY → EXECUTING → COMPLETED
                                                    ↘ FAILED / BLOCKED
```

| 状态 | 含义 | 允许的操作 |
|------|------|------------|
| CREATED | 项目已创建，JD 未分析 | Edit JD, Analyze JD, Delete |
| ANALYZING | JD 分析中 | 等待 |
| PLANNING | Blueprint + TaskGraph 生成中 | 等待 |
| READY | 用户已确认，等待启动 Run | Start Run, Edit Plan |
| EXECUTING | Run 进行中 | Pause（future）, View Tasks, View Events |
| COMPLETED | 所有 required tasks DONE | View Results |
| FAILED | Run 失败 | View Errors, Retry |
| BLOCKED | 等待 Replan Approval | Review Replan, Cancel |

### Run Status

复用 `ExecutionStatus`：

| 状态 | 含义 |
|------|------|
| PENDING | Run 已创建，未开始 |
| RUNNING | Run 进行中 |
| COMPLETED | 所有 required tasks DONE |
| FAILED | required task FAILED 且不可恢复 |
| BLOCKED | 等待用户 Replan Approval |

产品层新增语义：
- Task FAILED → Run 不立即 FAILED，检查 retry budget / active proposal。
- 只有当所有 remaining required tasks 都无法继续时，Run 才 FAILED。
- Run BLOCKED 时，用户 Approve Replan → Resume → 继续执行。

### Task Status

复用 `TaskStatus`：PENDING / READY / IN_PROGRESS / VALIDATING / DONE / FAILED / BLOCKED。

DONE Task 不可逆，不可修改，不可删除。

---

## 4. State Transition 规则

Project 状态迁移必须经过集中式生命周期控制。

合法迁移：
- CREATED → ANALYZING
- ANALYZING → PLANNING
- PLANNING → READY
- READY → EXECUTING
- EXECUTING → COMPLETED
- EXECUTING → FAILED
- EXECUTING → BLOCKED
- BLOCKED → EXECUTING（用户 Approve Replan 后 Resume）
- BLOCKED → FAILED（用户 Reject Replan 后）

非法迁移示例：
- COMPLETED → ANALYZING
- READY → CREATED
- EXECUTING → CREATED

终端状态保护：
- COMPLETED / FAILED 为终端状态，不允许迁移到其他状态。

---

## 5. Active Run Constraint

一个 Project 同时只能存在一个 active Run。

再次创建 Run 时，如果已有 RUNNING Run，必须被 Product Core 拒绝。

---

## 6. Event Model

Event 是 immutable audit log，不是 Event Sourcing。

当前 JSON persistence 仍是 state source of truth。

Event 目录：`.runtime/runs/<run_id>/events/`

Event 必须支持：
- 追加写入
- 不允许修改
- 不允许删除
- crash 后通过文件存在性恢复

P20 不实现 Event persistence，仅定义契约。

---

## 7. Error Model

统一产品级错误：

| Error Code | 用户含义 | 底层原因 | 可恢复 |
|------------|----------|----------|--------|
| PROJECT_NOT_FOUND | 项目不存在 | load 时 missing | 否 |
| INVALID_PROJECT_STATE | 项目状态不允许此操作 | state transition 非法 | 否 |
| INVALID_STATE_TRANSITION | 状态迁移非法 | transition 不在合法矩阵 | 否 |
| PROJECT_ALREADY_EXISTS | 项目已存在 | create 时 duplicate | 否 |
| ACTIVE_RUN_EXISTS | 已有活跃 Run | active run invariant | 是（Cancel 后） |
| COMMAND_NOT_ALLOWED | 命令不允许 | precondition 不满足 | 否 |
| PERSISTENCE_ERROR | 持久化错误 | IO / JSON 错误 | 否 |

---

## 8. API Surface

### Project

```text
POST   /projects
GET    /projects/{project_id}
DELETE /projects/{project_id}
```

### Analysis / Planning

```text
POST /projects/{project_id}/analyze
POST /projects/{project_id}/plan
```

### Execution

```text
POST /projects/{project_id}/run
GET  /projects/{project_id}/runs
GET  /projects/{project_id}/runs/{run_id}
POST /projects/{project_id}/resume
POST /projects/{project_id}/cancel
```

### Tasks

```text
GET /projects/{project_id}/tasks
GET /projects/{project_id}/tasks/{task_id}
```

### Events

```text
GET /projects/{project_id}/events
GET /projects/{project_id}/runs/{run_id}/events
```

### Replan

```text
GET  /projects/{project_id}/replans
POST /projects/{project_id}/replans/{proposal_id}/approve
```

### 统一错误模型

```json
{
  "error": {
    "code": "INVALID_PROJECT_STATE",
    "message": "Human-readable explanation",
    "project_id": "proj-123",
    "details": []
  }
}
```

---

## 9. CLI Surface

```bash
project create <name>
project analyze <project_id>
project plan <project_id>
project run <project_id>
project status <project_id>
project tasks <project_id>
project events <project_id>
project resume <project_id>
project cancel <project_id>
project replans <project_id>
project replan approve <project_id> <proposal_id>
```

命令行为定义：
- 非法状态 → 明确 error code + message，exit code != 0
- 重复命令 → idempotent 或明确拒绝
- 幂等命令：create（duplicate → error）、resume（无 run → error）、approve（已 approved → no-op）

---

## 10. Persistence Architecture

继续使用 P16 JSON Persistence，新增 events/ 目录。

```
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

---

## 11. MVP Scope

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

---

## 12. P20 Implementation Breakdown

```text
P20.0 Architecture / Contract Freeze
P20.1 Project Core ← 当前阶段
P20.2 Persistence / Event Integration
P20.3 API
P20.4 CLI
P20.5 Run Control
P20.6 Replan / Resume
P20.7 E2E
```

---

## 13. Architecture Concerns（来自 P19）

| # | Concern | Impact | Recommended Change | P20 Status |
|---|---------|--------|-------------------|------------|
| 1 | 全量 pytest 组合超时 | CI 效率 | 定位 root cause | 记录，不阻塞 |
| 2 | ExecutionRun 不携带 version | schema evolution | 增加 version | 记录，P20.2 评估 |
| 3 | HermesAdapter workspace 与 WorkerPool 未完全对齐 | 并行 workspace 冲突 | WorkerPool 显式传入 workspace_factory | P18 已部分解决 |
| 4 | DeterministicValidator 硬编码 pytest -q | 不同项目测试命令不同 | TaskContract.test_scope 驱动 | MVP 可接受 |
| 5 | ArtifactStore 无 task_id 目录隔离 | 大规模并行混淆 | 增加 task_id 子目录 | 记录，P20.2 评估 |

---

## 14. ADR

### ADR-01: Project 作为 Aggregate Root
Project 是产品级 Aggregate Root，所有产品级 mutation 以 Project 为边界。底层领域对象（JDProfile、TaskGraph 等）保持独立生命周期。

### ADR-02: Project / Run / Task 三层状态分离
Project 状态、Run 状态、Task 状态各有独立状态机，互不混淆。Task Status 复用 TaskStatus，Run Status 复用 ExecutionStatus，Project Status 为产品级状态。

### ADR-03: Event 是 Audit Log，不是 Source of Truth
Event 用于 audit / timeline / 通知，不是 event sourcing。当前 JSON persistence 仍是 state source of truth。

### ADR-04: CLI / API 必须经过 Product Core
所有产品级操作必须通过 Product Core，禁止绕过直接调用底层 Agent / Orchestrator / Persistence。

### ADR-05: 一个 Project 同时只允许一个 Active Run
MVP 禁止同一 Project 并行 Run。Product Core 维护此 invariant。

### ADR-06: Cancel 语义
Cancel = 停止调度 + 等待 active workers 完成 + 持久化 CANCELLED 状态，不等于 kill Hermes 子进程。

### ADR-07: Replan Approve 与 Resume 分离
用户 Approve Replan 和 Resume 是两个独立动作，必须显式依次执行。

### ADR-08: JSON Persistence 继续保留
P16 JSON Persistence 继续作为 state source，新增 events/ 目录。不引入数据库。

### ADR-09: 当前不做 Web UI
先通过 CLI / API 验证 Product Core，再通过 Web UI 包装。降低风险。

### ADR-10: 当前不做 Auth / Billing / Cloud Execution
MVP 聚焦本地单用户场景，多用户 / 云执行待 P24 扩展。

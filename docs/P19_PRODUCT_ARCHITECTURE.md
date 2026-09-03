# P19 Product Architecture & MVP Definition

> 本阶段为产品架构规划，不修改 P5-P18 核心实现，不新增业务代码，不接入真实 LLM / 数据库 / UI。

---

## 1. Product Vision

让准备实习 / 校招的软件工程学生，能够根据一份真实 JD，快速生成一个**有针对性的、可运行的工程项目**，并让 AI Coding Agent 按计划逐步实现、验证、解释和迭代这个项目。

系统的本质不是“又一个 AI 编程助手”，而是 **“JD 驱动的结构化项目教练 + 受约束的实现引擎”**。

---

## 2. Target User

### Target User
准备实习 / 校招的软件工程学生，通常具备基础编程能力，但对真实项目架构、工程化实践和面试深度问题缺乏系统落地经验。

### User Problem
1. 看到 JD 后不知道“我应该做一个什么样的项目”才能精准命中岗位要求。
2. 自己从零设计项目容易 scope 失控，要么太简单无法体现深度，要么过于宏大无法完成。
3. 即使有了项目 idea，也不知道如何拆解成可执行、可验证的学习任务。
4. 让 AI 直接写代码容易失控：代码可能跑偏、超出 scope、或缺少工程约束。
5. 无法判断 AI 生成的代码是否真的满足 JD 要求，也缺少独立验证机制。

### Why Existing AI Coding Tools Do Not Fully Solve It
- ChatGPT / Copilot：适合单点编码，但不从 JD 反推项目设计，不保证工程 scope，不提供独立验证。
- 低代码 / 模板平台：缺少针对特定 JD 的匹配，不生成可阅读、可扩展的真实代码。
- 在线课程 / 面试题：只给知识碎片，不给“从 JD 到完整项目”的闭环。
- 通用 AI Agent：缺少 DAG 约束、状态机、Validation、Replan、Persistence 等工程控制面。

### Product Value Proposition
> **输入一份 JD，输出一个你可以向面试官展示的、按计划实现并验证过的真实项目。**

核心差异：
- 起点是真实 JD，不是用户凭空想需求。
- 项目设计来自开源项目研究 + JD 匹配，不是拍脑袋。
- 任务拆解、执行、验证、Replan 全部受工程约束，不是裸 LLM。
- 用户可以审查、确认、调整，不是黑箱。

---

## 3. Core User Journey

```text
用户输入 JD / 粘贴 JD
        ↓
JD Analyzer
        ↓
生成 JDProfile
        ↓
Research + Matching
        ↓
生成 ProjectFit（Top 推荐）
        ↓
生成 ProjectBlueprint
        ↓
用户查看 / 调整 Blueprint
        ↓
选择 Scope Level
        ↓
生成 TaskGraph
        ↓
用户确认 Task Plan
        ↓
Start Run
        ↓
Worker Pool 并行执行
        ↓
Validation
        ↓
成功 → 下一 Task
失败 → Failure Analysis → Replan Proposal → User Review → Resume
        ↓
全部 DONE → 项目完成
```

### 阶段明细

| 阶段 | 用户看到 | 系统做 | 用户可修改 | 需要用户确认 | 可自动执行 |
|------|----------|--------|------------|--------------|------------|
| JD Input | JD 原文 / 上传 | 解析为 JDProfile | 可以编辑 JDProfile | 否 | 是 |
| Research/Matching | 推荐开源项目列表 / 匹配分数 | 分析 repo → ProjectFit | 否 | 否 | 是 |
| Blueprint | 项目设计文档 | 生成 ProjectBlueprint | 可以调整 design_decisions / tradeoffs | 是 | 否 |
| Scope Selection | 四级 Scope 选项 | 根据时间推荐 | 选择 Core / JD Alignment / Engineering Depth / Advanced | 是 | 否 |
| Task Plan | Task 列表 / 依赖图 | 生成 TaskGraph | 可以调整优先级 / 增删 Task | 是 | 否 |
| Implementation | 当前 Task / 进度条 | Worker 执行 + Validation | 否 | 否 | 是 |
| Validation Review | 验证结果 / 证据 | 独立验证 | 否 | 否 | 是 |
| Replan | 失败分析 / 建议 / 影响范围 | 生成 ReplanProposal | Approve / Reject | 是 | 否 |
| Completion | 项目总览 / 已完成 Task | 汇总结果 | 否 | 否 | 是 |

---

## 4. Product Domain Model

直接复用 P5-P18 已有 Schema，不重复造轮子。

| 实体 | 已有 Schema | Product Role | 说明 |
|------|-------------|--------------|------|
| JD | 无结构化 schema，原始文本 | 用户输入 artifact | 不持久化为结构化实体，只作为输入源 |
| JDProfile | `app/schemas/jd.py` | Source of Truth for JD | 只由 JD Analyzer 生成 |
| ResearchOutput | `app/schemas/research.py` | Source of Truth for GitHub facts | 只由 Researcher 生成 |
| RepositoryScore | `app/schemas/scoring.py` / `ranking.py` | 匹配输入 | 不独立暴露给用户 |
| ProjectFit | `app/schemas/matching.py` | Matching result | 用户可查看，不可直接编辑 |
| ProjectBlueprint | `app/schemas/blueprint.py` | 项目设计核心 | 用户可查看 / 有限调整 |
| Task / TaskGraph | `app/schemas/task.py` | 项目计划核心 | 用户可确认 / 有限调整 |
| TaskContract | `app/schemas/implementation.py` | Worker 执行契约 | 系统内部使用，用户不直接编辑 |
| AgentExecutionResult | `app/schemas/implementation.py` | 执行结果 | 系统内部使用 |
| ValidationResult | `app/schemas/validation.py` | 验证结果 | 用户可查看 |
| ExecutionRun | `app/schemas/execution.py` | Run 状态核心 | 用户可查看 / 控制 |
| ReplanProposal | `app/schemas/replan.py` | Replan 核心 | 用户可 Approve / Reject |
| Artifact | `app/schemas/persistence.py` | 产物存储 | 用户可查看 |
| Event | **新增 Product Event Schema** | 审计 /  timeline / 通知 | 系统 append-only |

### Product View / Projection（非 Source of Truth）
- Project Overview：从 Blueprint + ExecutionRun 聚合而来
- Task Timeline：从 TaskExecutionRecord + Event 聚合
- Dashboard：从 ExecutionRun + ValidationResult 聚合
- Interview Guide：从 Blueprint.interview_* 字段投影

---

## 5. Source of Truth Matrix

| 数据 | Source of Truth | 是否允许 LLM 修改 | 是否允许 User 修改 |
|------|-----------------|-------------------|--------------------|
| JD | JD Input | No | Yes |
| JDProfile | JD Analyzer | No | No / 通过重新分析 |
| Research | ResearchOutput | No | No |
| ProjectFit | ProjectMatcher | No | No |
| Blueprint | ProjectBlueprint | No | Yes，受边界限制 |
| TaskGraph | TaskEngine | No | Limited |
| Task State | Scheduler / Execution | No | Limited |
| Validation | Validator | No | No |
| Replan | ReplanProposal | No | Approve / Reject |
| Artifacts | ArtifactStore | Agent generates | Review |
| Execution Events | Event Store | No | No |

**调整说明：**
- Blueprint 允许用户修改，但受边界限制：不能修改 core problem / core features / architecture style 等结构性字段，只能调整 design_decisions / tradeoffs / interview 相关字段。
- TaskGraph 允许用户有限调整：可以重新排序优先级、标记 optional task 为 skipped，但不能修改 dependencies 造成 cycle，不能删除 DONE task。
- Task State 不允许用户直接修改，只能通过系统动作（Start / Pause / Resume / Retry / Approve Replan）间接改变。

---

## 6. Product State Model

### Project State

```text
DRAFT → ANALYZING → PLANNED → READY → RUNNING → PAUSED → COMPLETED
                                                    ↘ FAILED / BLOCKED
```

| 状态 | 含义 | 允许的操作 |
|------|------|------------|
| DRAFT | 仅保存 JD，未分析 | Edit JD, Analyze JD, Delete |
| ANALYZING | JD 分析中 | 等待 |
| PLANNED | Blueprint + TaskGraph 已生成，等待用户确认 | Confirm Plan, Edit Scope, Start Run |
| READY | 用户已确认，等待启动 | Start Run, Edit Plan |
| RUNNING | Run 进行中 | Pause, View Tasks, View Events |
| PAUSED | Run 暂停 | Resume, Cancel |
| COMPLETED | 所有 required tasks DONE | View Results, Export |
| FAILED | Run 失败 | View Errors, Retry Failed Tasks, New Run |
| BLOCKED | 等待 Replan Approval | Review Replan, Cancel |

### Run State

复用 `ExecutionStatus`，增加产品层语义：

| 状态 | 对应 ExecutionStatus | 含义 |
|------|---------------------|------|
| PENDING | PENDING | Run 已创建，未开始 |
| RUNNING | RUNNING | Run 进行中 |
| PAUSED | — | Run 暂停（产品层新增） |
| COMPLETED | COMPLETED | 所有 required tasks DONE |
| FAILED | FAILED | required task FAILED 且不可恢复 |
| BLOCKED | BLOCKED | 等待用户 Replan Approval |

**状态转换规则：**
- Task FAILED → Run 不立即 FAILED，而是检查是否有 active proposal 或 retry budget。
- 只有当所有 remaining required tasks 都无法继续时，Run 才 FAILED。
- Run BLOCKED 时，用户 Approve Replan → Run RESUME → 继续执行。
- 同一时间 Run 只能处于一个状态。

### Task State

复用 `TaskStatus`：

| 状态 | 含义 |
|------|------|
| PENDING | 未开始 |
| READY | 依赖已满足，等待调度 |
| IN_PROGRESS | Worker 执行中 |
| VALIDATING | Validation 进行中 |
| DONE | Validation PASS |
| FAILED | Agent 或 Validation FAIL |
| BLOCKED | 依赖失败 / 等待 Replan |

**重要：** DONE Task 不可逆，不可修改，不可删除。这是产品层的硬约束，不是可选项。

---

## 7. Event Model

统一 Product Event Schema，用于 audit、timeline、通知、replay。

```text
event_id: str
event_type: EventType
project_id: str
run_id: str | None
task_id: str | None
timestamp: str
actor: Actor  # USER / SYSTEM / AGENT / VALIDATOR
payload: JsonValue  # 限制为 primitives / arrays / objects，禁止任意 blob
```

### 事件类型

| 事件 | Actor | 触发时机 |
|------|-------|----------|
| PROJECT_CREATED | USER | 用户创建项目 |
| JD_ANALYSIS_STARTED | SYSTEM | 开始分析 JD |
| JD_ANALYSIS_COMPLETED | SYSTEM | JD 分析完成 |
| RESEARCH_STARTED | SYSTEM | 开始 Research |
| RESEARCH_COMPLETED | SYSTEM | Research 完成 |
| PROJECT_MATCHED | SYSTEM | Matching 完成 |
| BLUEPRINT_GENERATED | SYSTEM | Blueprint 生成 |
| SCOPE_SELECTED | USER | 用户选择 Scope |
| TASK_GRAPH_CREATED | SYSTEM | TaskGraph 生成 |
| TASK_GRAPH_CONFIRMED | USER | 用户确认 Task Plan |
| RUN_CREATED | USER | 创建 Run |
| RUN_STARTED | SYSTEM | Run 开始 |
| RUN_PAUSED | USER | 用户暂停 |
| RUN_RESUMED | USER | 用户恢复 |
| TASK_READY | SYSTEM | Task 变为 READY |
| TASK_STARTED | SYSTEM | Task 开始执行 |
| AGENT_STARTED | AGENT | Worker 开始 |
| AGENT_FINISHED | AGENT | Worker 完成 |
| VALIDATION_STARTED | VALIDATOR | Validation 开始 |
| VALIDATION_PASSED | VALIDATOR | Validation PASS |
| VALIDATION_FAILED | VALIDATOR | Validation FAIL |
| TASK_COMPLETED | SYSTEM | Task DONE |
| TASK_FAILED | SYSTEM | Task FAILED |
| TASK_BLOCKED | SYSTEM | Task BLOCKED |
| REPLAN_PROPOSED | SYSTEM | Replan Proposal 生成 |
| REPLAN_APPROVED | USER | 用户批准 |
| REPLAN_REJECTED | USER | 用户拒绝 |
| REPLAN_APPLIED | SYSTEM | Replan 应用 |
| ARTIFACT_CREATED | AGENT | 产物生成 |
| RUN_BLOCKED | SYSTEM | Run 等待 Replan |
| RUN_COMPLETED | SYSTEM | Run 完成 |
| RUN_FAILED | SYSTEM | Run 失败 |

**Payload 设计原则：**
- 不存储任意 `dict[str, Any]`
- 每个 event_type 对应一个小的 Typed Payload Schema
- 例如 `ValidationFailedPayload` 只包含 `task_id`, `validation_status`, `failed_criteria_count`

---

## 8. Product Control Plane

用户真正能控制的操作，按产品层 Action 设计：

| Action | Preconditions | Allowed States | Resulting State | Side Effects | 需要用户确认 |
|--------|--------------|----------------|-----------------|--------------|--------------|
| Create Project | 无 | — | DRAFT | 创建 Project 记录 | 否 |
| Edit JD | DRAFT | DRAFT | DRAFT | 更新 JD 文本 | 否 |
| Analyze JD | DRAFT | DRAFT | ANALYZING | 调用 JD Analyzer | 否 |
| Generate Blueprint | ANALYZING | ANALYZING | PLANNED | 调用 Blueprint + TaskEngine | 否 |
| Select Scope | PLANNED | PLANNED | PLANNED | 更新 selected_scope | 否 |
| Confirm Plan | PLANNED | PLANNED | READY | 锁定 TaskGraph 基础结构 | 是 |
| Start Run | READY | READY | RUNNING | 创建 ExecutionRun，调度 Worker | 是 |
| Pause Run | RUNNING | RUNNING | PAUSED | 停止调度，等待 active workers | 是 |
| Resume Run | PAUSED | PAUSED | RUNNING | 恢复调度 | 是 |
| Cancel Run | RUNNING / PAUSED | RUNNING / PAUSED | FAILED | 停止所有 workers | 是 |
| Review Validation | — | TASK_FAILED | — | 展示 ValidationResult | 否 |
| Retry Task | TASK_FAILED | TASK_FAILED | READY | 重置 Task，重新调度 | 是 |
| Review Replan | — | RUN_BLOCKED | — | 展示 ReplanProposal | 否 |
| Approve Replan | RUN_BLOCKED | RUN_BLOCKED | RUNNING | 调用 ReplanApplier，Resume | 是 |
| Reject Replan | RUN_BLOCKED | RUN_BLOCKED | FAILED | 标记 Proposal REJECTED | 是 |
| View Artifact | — | 任意 | — | 展示 ArtifactStore 内容 | 否 |
| View Timeline | — | 任意 | — | 展示 Event 流 | 否 |

**核心原则：** 用户控制 ≠ 用户可以随便修改内部状态。所有状态变更必须通过 Action 触发，每个 Action 有 preconditions 和 allowed states。

---

## 9. LLM Boundary

### 绝对不能让 LLM 决定的事情
1. **Task State 最终状态** — 只有 Validation PASS 才能 DONE。
2. **Validation Final Decision** — 必须经过 Deterministic Validator 独立验证。
3. **Replan Apply** — 必须用户显式 Approve。
4. **Source of Truth 写入** — JDProfile / ResearchOutput / ProjectFit / TaskGraph 只能由确定性模块生成。
5. **DAG 修改** — 不能自动删除 / 修改 DONE Task，不能重写 Blueprint。
6. **Scope 决策** — 用户选择 Scope Level，LLM 只能推荐。

### 适合 LLM 的事情
1. **Hermes Worker** — 在 TaskContract 约束内实现代码。
2. **Future: Failure Hypothesis 生成** — 当前 P17 用确定性规则，未来可让 LLM 在 failure evidence 基础上提出更丰富的 hypothesis，但仍需用户确认。
3. **Future: Interview Assistant** — 基于 Blueprint 生成面试题、回答点评。
4. **Future: Review 增强** — 在 Deterministic Validator 基础上增加 LLM Review，但只是 Reviewer，不是 Decider。

### Human-in-the-loop 必须介入的场景
1. Blueprint 生成后的确认。
2. Scope Level 选择。
3. Task Plan 确认。
4. Replan Approval。
5. Run Cancel。

### 为什么 LLM 不应该拥有这些权限
- LLM 输出非确定性，同一输入可能产生不同输出。
- 核心状态一旦被 LLM 误改，可能导致 DAG 破坏、DONE Task 被篡改、scope 越界。
- 产品层需要可审计、可回滚的状态机，LLM 的自由文本不适合作为状态迁移的唯一依据。
- 用户需要“可解释”的失败原因，而不是 LLM 直接 silently retry。

---

## 10. Project Workspace

用户进入一个 Project 后看到的核心信息，第一屏必须回答 5 个问题：

### 第一屏：Project Dashboard

```text
Project: AI Agent Backend (matched from spring-boot-demo)
JD Match Score: 87 / 100
Scope: JD Alignment

1. 我现在在做什么？
   → Current Task: T3 - Implement idempotency
   → Status: VALIDATING
   → Worker: Worker-2

2. 项目完成多少了？
   → Progress: ████████████░░░░ 72%
   → 8 / 11 tasks DONE

3. AI 正在做什么？
   → T3: Validation in progress (2/3 criteria passed)
   → T4: READY, waiting for T3
   → T5: BLOCKED by T4

4. 有没有问题需要我处理？
   → 1 Replan Proposal pending approval (T2)
   → [Review Replan]

5. 下一步是什么？
   → If T3 PASS → T4 will start
   → If T3 FAIL → Replan Proposal ready
```

### 信息层级

| 层级 | 内容 | 默认可见 |
|------|------|----------|
| Overview | Project name, JD match score, Scope, overall progress | 是 |
| Progress | Task completion %, phase breakdown | 是 |
| Current Task | Current task title, goal, acceptance criteria, worker status | 是 |
| Task Plan | Full TaskGraph, dependencies, status per task | 是 |
| Timeline | Event stream, chronological view | 否，折叠 |
| Validation | Latest validation results, criterion breakdown | 按需 |
| Replan | Active proposals, history | 仅当存在时 |
| Artifacts | Changed files, diffs, test outputs | 按需 |
| Interview / Resume | Generated from Blueprint | P22+ |

---

## 11. Execution Console

AI Coding 执行界面的核心信息，避免直接把 Hermes 原始日志作为主 UI。

```text
Project Progress
██████████████░░░ 72%

Current Task
Idempotency & Duplicate Message Handling

Worker
Worker-2 | workspace: .runtime/runs/run-123/workspaces/T3/

Status
VALIDATING

Recent Events
✓ Agent completed (2.3s)
✓ Tests executed (1.1s)
⚠ Validation failed (1 criterion)

Validation
2 / 3 criteria passed
- Self-test execution: PASS
- Scope check: PASS
- Acceptance criterion #1: NEEDS_REVIEW

Suggested Action
[ Retry Task ]
[ Review Replan ]

Artifacts
- T3_agent_output.json
- T3_validation_result.json
- T3.diff
```

**原始 stdout/stderr 的处理：**
- 不作为主 UI 内容。
- 作为 Artifact 存储，在 Advanced Debug 页面可查看。
- 用户默认看到结构化结果，不是 raw logs。

---

## 12. Replan UX

这是 P17 最重要的用户交互之一。

### 用户看到的 Replan Review 界面

```text
Task T2: Redis Cache Integration
Why Failed
→ Validation failed: 1/3 acceptance criteria not met

Evidence
→ Test output: test_cache_invalidations failed
→ Changed files: src/cache.py, tests/test_cache.py
→ Scope: WITHIN_SCOPE

Recommended Action
→ RETRY (1/2 retries used)

Affected Tasks
→ T2 only

What Will Change
→ Re-execute T2 with same TaskContract
→ Worker will attempt up to 3 Hermes iterations

What Will NOT Change
→ Blueprint architecture
→ TaskGraph dependencies
→ T3/T4/T5 definitions
→ DONE Tasks

[ Approve Retry ]
[ Reject ]
```

**明确禁止：**
- 不让 Agent 自动修改 Blueprint / Architecture / DONE Tasks。
- 不展示“AI 建议重写整个项目”之类的选项。
- 不自动 Apply Replan，必须用户点击 Approve。

---

## 13. Scope UX

P10 已经定义四级 Scope，P19 把它产品化。

### 用户看到的 Scope Selection

```text
Recommended Scope
JD Alignment

Why:
Your available time is ~10h/week.
This scope covers all JD required skills plus key engineering topics.

Included:
✓ Core backend service
✓ JD required skills: Java, Spring Boot, MySQL, Redis
✓ REST API design
✓ Unit testing
✓ Basic documentation

Not included:
○ Distributed transaction
○ Multi-region deployment
○ Advanced observability
○ Performance optimization beyond JD requirements

[ Core ] [ JD Alignment ← Recommended ] [ Engineering Depth ] [ Advanced ]
```

**系统行为：**
- 推荐 Scope 基于 UserProfile.weekly_hours + JD required_skills + ProjectBlueprint.recommended_scope。
- 用户选择任意 Scope Level 后，TaskEngine 重新生成 TaskGraph。
- 用户不能“手动往 Scope 里加一项再删一项”，只能选整级。
- 如果用户选 Advanced 但 weekly_hours 不够，系统给出 warning，但不阻止。

---

## 14. MVP Boundary

### MUST HAVE
第一版产品上线必须具备：

1. JD Input → JDProfile 分析
2. GitHub Research + Project Matching → ProjectFit
3. ProjectBlueprint 生成
4. Scope Level 选择
5. TaskGraph 生成 + 用户确认
6. Run 执行：Serial / Parallel Worker
7. Validation：Deterministic + 独立
8. Replan：Failure Analysis → Proposal → User Approve/Reject → Resume
9. Persistence：JSON-based，支持 Resume
10. CLI / API 入口
11. 基础 Event 记录

### SHOULD HAVE
有价值但第二阶段：

1. Web Workspace MVP（P21）
2. LLM Reviewer 增强 Validation
3. Failure Hypothesis LLM 增强
4. Interview / Resume Guide 生成
5. 更丰富的 Blueprint 模板
6. 多项目 Dashboard

### NICE TO HAVE
未来功能：

1. 多 Coding Agent 支持（不限于 Hermes）
2. GitHub PR Automation
3. 团队协作
4. 云执行环境
5. 市场 / 模板共享
6. Analytics / 学习路径推荐

### NOT MVP
明确禁止现在做：

- Web UI（P21）
- Authentication / Multi-user
- Billing
- Cloud execution
- Database migration
- 分布式基础设施
- Agent marketplace
- 自动架构重设计
- 开放式 Agent 框架

---

## 15. API Surface

先设计，不实现。P20 实现。

### 项目级

```text
POST   /projects               # 创建项目
GET    /projects/{id}          # 项目概览
PATCH  /projects/{id}/jd       # 更新 JD
POST   /projects/{id}/analyze  # 触发 JD 分析
POST   /projects/{id}/research # 触发 Research + Matching
POST   /projects/{id}/blueprint # 生成 Blueprint
PATCH  /projects/{id}/blueprint # 调整 Blueprint
POST   /projects/{id}/scope    # 选择 Scope
POST   /projects/{id}/tasks    # 生成 TaskGraph
PATCH  /projects/{id}/tasks    # 调整 TaskGraph
```

### Run 级

```text
POST   /projects/{id}/runs     # 创建 Run
POST   /runs/{id}/start        # 启动 Run
POST   /runs/{id}/pause        # 暂停 Run
POST   /runs/{id}/resume       # 恢复 Run
POST   /runs/{id}/cancel       # 取消 Run
GET    /runs/{id}              # Run 状态
GET    /runs/{id}/events       # Run 事件流
GET    /runs/{id}/tasks        # Run 内 Task 状态
```

### Task 级

```text
POST   /tasks/{id}/retry       # Retry Task
GET    /tasks/{id}/validation  # 查看 ValidationResult
GET    /tasks/{id}/artifacts   # 查看 Artifacts
```

### Replan 级

```text
GET    /runs/{id}/replans      # 列出 Replan Proposals
POST   /replans/{id}/approve   # 批准 Replan
POST   /replans/{id}/reject    # 拒绝 Replan
```

### 统一错误模型

```text
{
  "error": {
    "code": "VALIDATION_FAILED",
    "message": "Human-readable explanation",
    "task_id": "T3",
    "details": []
  }
}
```

**不应存在的 API：**
- 不允许直接修改 Task.state 的 PATCH API。
- 不允许直接修改 TaskGraph.dependencies 的自由 API。
- 不允许“让 LLM 自动修复并重试”的单按钮 API。

---

## 16. Persistence Architecture

基于 P16 现有 JSON Persistence，不引入数据库。

```
.runtime/
└── projects/
    └── <project_id>/
        ├── project.json          # Project metadata
        ├── jd.json               # JDProfile
        ├── blueprint.json        # ProjectBlueprint
        ├── task_graph.json       # TaskGraph
        └── runs/
            └── <run_id>/
                ├── execution.json         # ExecutionRun
                ├── tasks/
                │   └── <task_id>.json     # TaskExecutionRecord
                ├── events/
                │   └── <event_id>.json    # Product Event
                ├── replans/
                │   └── <proposal_id>.json # ReplanProposal
                └── artifacts/
                    └── <artifact_id>.*    # Artifact files
```

**合理性判断：**
- 该结构与 P16 现有 `JsonExecutionPersistence` 完全兼容。
- `ArtifactStore` 已按 run_dir 绑定，无需修改。
- `ReplanPersistence` 已写入 `.runtime/runs/<run_id>/replans/`，无需修改。
- 新增 `events/` 目录用于 Product Event，不冲突。
- 无需立即引入数据库；JSON 文件在 MVP 规模下足够。

**如果需要修改：**
- 未来当事件量增大时，events/ 可拆分为按日期分片。
- 未来多用户场景下，需在 project_id 前增加 user_id 分层。
- 当前不需要。

---

## 17. Security Boundary

### Workspace Isolation
- 每个 Task 的 Worker 使用独立 workspace，路径由 `workspace_factory(task_id)` 生成。
- 禁止两个 Worker 共享同一个 mutable workspace。
- workspace 路径必须通过 `relative_to(run_dir)` 防逃逸。

### Subprocess / Hermes
- Hermes 通过 `subprocess.run(shell=False, list args)` 执行，禁止 shell injection。
- timeout 必须设置，默认 900s。
- stdout/stderr 只作为 Artifact 存储，不直接展示给用户。
- 如果 Hermes CLI 不可用，系统返回 ERROR，不伪造成功。

### API Keys / Secrets
- 所有 API keys 从环境变量加载，不写入代码 / JSON。
- Prompt 中禁止包含 API keys / tokens / credentials。
- Artifact 存储前做 secret redaction（P16 Audit 已建议，P20 实现）。

### User Input
- JD 输入长度限制，防止 prompt injection 或内存溢出。
- 用户输入的 Blueprint 调整字段经过 schema validation，不直接拼接到 prompt。

### Git Operations
- 禁止 `git reset / clean / checkout / commit` 自动化。
- 只做 `git status` / `git diff` 只读检查。
- 不覆盖用户已有修改。

### Path Traversal
- 所有文件操作基于 `run_dir` / `workspace` 前缀检查。
- `ArtifactStore.relative_to` 已实现防逃逸。

---

## 18. Observability

MVP 优先：Event + structured logs + persisted execution metadata。

### 核心指标

| 指标 | 来源 | 用途 |
|------|------|------|
| run_duration | ExecutionRun.started_at / finished_at | 性能监控 |
| task_duration | TaskExecutionRecord.started_at / finished_at | 瓶颈识别 |
| agent_duration | AgentExecutionResult.started_at / finished_at | Worker 效率 |
| validation_duration | ValidationResult.validated_at | 验证效率 |
| retry_count | ExecutionRun / TaskExecutionRecord | 质量指标 |
| replan_count | ExecutionRun.replan_count | 复杂度指标 |
| failure_rate | ValidationResult.status == FAIL | 稳定性 |
| success_rate | ValidationResult.status == PASS | 价值证明 |
| worker_utilization | Event: AGENT_STARTED / AGENT_FINISHED | 并行效率 |

### 不做的
- 不做分布式 tracing。
- 不做 metrics aggregation 服务。
- 不做实时 dashboard 后端。
- P21 Web UI 只消费已持久化的 Event 和 ExecutionRun，不接入额外 telemetry。

---

## 19. Product Success Criteria

不使用“代码写出来了”作为成功标准。

| 指标 | 定义 | 为什么重要 |
|------|------|------------|
| JD → Project Plan 时间 | 从 JD input 到 TaskGraph 确认的时间 | 证明 pipeline 效率 |
| JD → First Implemented Task 时间 | 从 JD input 到第一个 Task DONE 的时间 | 证明端到端价值 |
| Project → Completed MVP 比例 | 成功完成所有 required tasks 的项目占比 | 证明系统可靠性 |
| Validation Success Rate | PASS / (PASS + FAIL) | 证明 Implementation 质量 |
| User Replan Approval Rate | Approved / (Approved + Rejected) | 证明 Replan 建议质量 |
| Task Retry Rate | Retry count / Total tasks | 证明首次成功率 |

---

## 20. P19 → P20 → P21 → P22 Roadmap

```text
P19  Product Architecture & MVP Definition
        ↓
P20  Product Core / API / CLI
        ↓
P21  Web Workspace MVP
        ↓
P22  Real Project E2E + Polish
        ↓
P23  LLM Intelligence Layer
        ↓
P24  Deployment / Reliability
```

### P19（当前）
- 产品架构规划
- Domain Model、State Model、Event Model、Control Plane
- API Surface 设计
- MVP Scope 定义
- 输出 `docs/P19_PRODUCT_ARCHITECTURE.md`

### P20
- 实现 Core Service 层
- FastAPI / CLI 入口
- Project / Run / Task CRUD 操作
- Event 持久化
- 不实现 Web UI

### P21
- Web Workspace MVP
- Project Dashboard
- Execution Console
- Replan Review UI
- 只读 View，不新增业务逻辑

### P22
- 真实项目 E2E：用真实 JD + 真实开源项目跑通完整流程
- 稳定性 / 性能优化
- Error handling 完善

### P23
- LLM Reviewer 增强 Validation
- Failure Hypothesis LLM 生成
- Interview Assistant

### P24
- Deployment
- 多用户
- 可观测性增强
- 生产就绪

**为什么不是直接做 Web UI？**
- P5-P18 已经建立了完整的核心能力，但还没有经过真实项目验证。
- 先通过 P20 CLI / API 验证 Core，再通过 P21 Web UI 包装，风险更低。
- 如果 Core 本身有问题，Web UI 只会放大问题。

---

## 21. Architecture Concerns（现有 P5-P18 问题记录）

以下问题 P19 不做修改，仅记录供 P20 决策：

| # | Architecture Concern | Impact | Recommended Change | Why Not Fixed Before P20 |
|---|---------------------|--------|-------------------|--------------------------|
| 1 | 全量 pytest 组合超时 | 影响 CI 效率 | 定位 test collection / fixture 泄漏 | 非功能阻塞，P5-P17 分块测试通过 |
| 2 | ExecutionRun 不携带 version | 未来 schema evolution 困难 | 增加 version 字段 | P16 Audit 已识别，不阻塞当前功能 |
| 3 | HermesAdapter workspace 未与 WorkerPool workspace isolation 完全对齐 | P18 并行时可能共用 workspace | WorkerPool 显式传入 workspace_factory | P18 已部分解决，待 P20 统一 |
| 4 | DeterministicValidator 硬编码 `pytest -q` | 不同项目测试命令不同 | TaskContract.test_scope 驱动 test_command | 当前 MVP 范围内可接受 |
| 5 | ArtifactStore 按 artifact_id 存储，无 task_id 目录隔离 | 大规模并行时可能混淆 | 增加 task_id 子目录 | 当前 Artifact 数量可控 |

---

## 22. 需要人工决策的问题

| # | 问题 | 选项 | 建议 | 决策者 |
|---|------|------|------|--------|
| 1 | P20 API 框架选型 | FastAPI / Flask / 其他 | FastAPI | 用户 |
| 2 | P21 Web 前端技术 | React / Vue / 其他 | 轻量 Vue / Svelte | 用户 |
| 3 | 是否在 MVP 支持多 Coding Agent | 只 Hermes / 多 Adapter | 只 Hermes，P23 扩展 | 用户 |
| 4 | 是否接入真实 LLM Reviewer | P22 接入 / P23 接入 | P23 接入 | 用户 |
| 5 | 用户数据存储 | 本地 JSON / 云存储 | 本地 JSON，P24 扩展 | 用户 |

---

## 23. P5-P18 是否修改

**否。**

本阶段为纯规划阶段，不修改任何 P5-P18 核心实现、Schema、Agent 或测试。

---

## 24. 测试

本阶段无代码变更，无测试运行。

---

## 25. compileall

不适用。

---

## 26. git diff --check

不适用。

---

## 27. git status

不适用。

---

## 28. 最终结论

P19 是否 PASS：**PASS**

新增文件：
- `docs/P19_PRODUCT_ARCHITECTURE.md`

修改文件：
- 无

是否适合进入 P20：**是**

P19 已经把 P5-P18 的技术能力收敛为明确的产品架构：
- 目标用户清晰（准备实习/校招的学生）
- 用户旅程完整（JD → 项目 → 实现 → 验证 → Replan → 完成）
- Source of Truth 明确，LLM 边界清晰
- State / Event / Control Plane 设计完成
- MVP Scope 收敛，NOT MVP 明确
- API Surface 可指导 P20 实现
- Persistence / Security / Observability 边界清晰
- Roadmap 可执行

下一步：P20 Product Core / API / CLI。

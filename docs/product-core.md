# Product Core

## 定位

Product Core 是整个产品的唯一产品级 mutation 入口。

CLI 和 API 都必须经过 Product Core。禁止绕过 Product Core 直接调用底层 Agent / Orchestrator / Persistence。

## 核心模块

- `app/product/service.py`：ProjectService，产品级入口
- `app/product/run_control.py`：RunControl，管理 ExecutionRun
- `app/product/replan_control.py`：ReplanControl，管理重新规划
- `app/product/lifecycle.py`：ProjectLifecycle，项目状态机
- `app/product/event_store.py`：EventStore，不可变审计日志
- `app/product/project_persistence.py`：ProjectPersistence，项目 JSON 持久化
- `app/product/project_artifact_store.py`：ProjectArtifactStore，产物引用持久化
- `app/product/workflow.py`：ProjectWorkflow，分析、匹配、蓝图、任务图工作流

## 调用边界

```text
API
  │
  ▼
ProjectService
  │
  ▼
ProjectWorkflow
RunControl
ReplanControl
ProjectPersistence
EventStore
```

## 执行链

```text
RunControl
  │
  ▼
ExecutionOrchestrator
  │
  ▼
TaskScheduler
  │
  ▼
Worker
  │
  ▼
CodingAgent
  │
  ▼
HermesAdapter
  │
  ▼
Real Hermes CLI
  │
  ▼
Validation
  │
  ▼
Task DONE / FAILED / BLOCKED
```

## 项目生命周期

- CREATED
- ANALYZING
- PLANNING
- READY
- EXECUTING
- COMPLETED / FAILED / BLOCKED

## 设计原则

- Project 是产品级 Aggregate Root
- Event 是 immutable audit log，不是 Event Sourcing
- JSON persistence 是 state source of truth
- 一个 Project 同时只能有一个 active Run
- Cancel 不强杀正在运行的 Hermes
- DONE Task 不可逆，不可修改，不可删除
- Replan 必须经过用户明确批准

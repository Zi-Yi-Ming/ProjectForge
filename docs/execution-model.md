# 执行模型

## 执行入口

执行入口位于 `app/cli/app.py`。

```text
python -m app.cli run start <project_id>
python -m app.cli run show <project_id> <run_id>
python -m app.cli run cancel <project_id> <run_id>
python -m app.cli run resume <project_id>
```

## Run 与 Project 的关系

- 一个 Project 同时只能存在一个活跃 Run
- Run 不能跨 Project 复用
- Cancel 不强杀正在运行的 Hermes 子进程，而是停止调度并等待 active workers 完成

## Task 生命周期

```text
PENDING
  ↓
READY
  ↓
IN_PROGRESS
  ↓
VALIDATING
  ↓
DONE / FAILED / BLOCKED
```

## 验证

每个 Task 在完成后进入 VALIDATING，由 Validator 独立验证：
- 测试执行
- scope 检查
- 验收标准核对

只有验证通过才能标记为 DONE。

## Replan

当任务失败或受阻时：
1. 生成失败分析
2. 输出影响范围
3. 提供重做建议
4. 用户明确批准后应用
5. 用户明确批准后恢复执行

Replan 不会自动修改蓝图或已完成任务。

## Hermes 约束

- Hermes 通过 HermesAdapter 调用真实 Hermes CLI
- HermesAdapter 通过 TaskContract 约束执行范围
- Hermes v0.20.6 的文件操作根路径限制仍然存在，因此当前 execution engine 可用性依赖本地环境

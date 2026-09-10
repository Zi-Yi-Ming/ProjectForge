# Demo：约束式执行全链路（离线可跑）

本演示展示 ProjectForge 的完整产品闭环：

```
项目生命周期 → 任务依赖图 → 受约束执行 → 注入失败 → replan 提案 → 人工审批 → resume → COMPLETED
```

全程使用 `--executor mock`（或 `scripts/demo.py`），**不需要 Hermes、bubblewrap 或网络**——
mock executor 走的是真实的 orchestrator + validator 路径，只是把代码生成换成确定性写文件。

## 一键运行

```bash
git clone https://github.com/Zi-Yi-Ming/ProjectForge.git
cd ProjectForge
pip install -e .
python scripts/demo.py
```

预期输出以 `DEMO COMPLETE` 结尾，5 个阶段依次是：

1. 项目生命周期推进（`CREATED → ANALYZING → PLANNING → READY`）
2. 持久化任务依赖图（T2 依赖 T1，任务声明 `test_paths=["tests"]`）
3. 约束式 run #1：T1 完成并通过确定性验证，T2 被注入失败 → run 终止
4. replan 三步：`create_proposal → approve → apply`（T2 重置为 PENDING；**人工审批是强制关卡**）
5. resume：T1 保持 DONE 不重跑，T2 重试并通过验证 → run `COMPLETED`

## 用 CLI 体验（从 JD 到执行，纯命令行）

```bash
# 从 JD 文本规划到 PLANNING（规则版离线 planner，无需任何 key）
projectforge plan new ./jd.txt --planner rule --base-dir .runtime

# 审批计划（PLANNING -> READY，审批后才能执行）
projectforge plan approve <project_id> --base-dir .runtime

# 查看生成的任务图（导出 JSON）
projectforge plan new ./jd.txt --planner rule --base-dir .runtime --json-out graph.json

# 约束式执行
projectforge run start <project_id> --base-dir .runtime --executor mock
projectforge run show <project_id> <run_id> --base-dir .runtime
```

`plan new` 默认用离线规则 planner；配置三个环境变量
`PROJECTFORGE_LLM_BASE_URL / PROJECTFORGE_LLM_API_KEY / PROJECTFORGE_LLM_MODEL`
（任何 OpenAI 兼容厂商：StepFun、DeepSeek、OpenRouter、本地 ollama）后加 `--planner llm`，
LLM 会按 JD 生成蓝图与任务图，输出经 schema 与任务图双重校验，失败自动回退规则版、命令不会失败。

真实执行把 `--executor mock` 换成 `hermes`（默认），要求 Linux + Hermes CLI + bwrap，
见 README 的「运行真实执行」。

## 录制 asciinema

```bash
pip install asciinema
asciinema rec -o demo.cast
python scripts/demo.py          # 或逐条跑上面的 CLI 命令
exit                            # 或 Ctrl-D 结束录制
asciinema upload demo.cast
```

## 演示背后的真实行为

- mock executor 走的是**生产** orchestrator + DeterministicValidator，不是测试桩
- 任务声明 `test_paths` 后，validator 会在 workspace 里真实执行 `pytest`；
  通过时人工验收标准不再阻塞任务（`NEEDS_REVIEW` → 记入 `manual_review_items`），
  任务才能到 `DONE`
- scope 检查把 workspace 相对路径与合同里的绝对 `allowed_paths` 做解析比对，
  越界修改会被判 `SCOPE_VIOLATION`
- replan 提案必须人工 `approve` 后才能 `apply`，`forbidden_changes` 保护蓝图与架构不被执行器擅改

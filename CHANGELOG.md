# Changelog

All notable changes to this project are documented in this file.
Format: Keep a Changelog; versioning: SemVer（0.x 阶段 minor = 能力/破坏性变更，patch = 修复）。

## [0.5.1] - 2026-09-15
### Added
- **scope 生产者落地（步骤 ③）**：`LlmPlanner` 现在在 system prompt 中要求 LLM 为每个任务产出
  `allowed_paths`（相对目录、禁用绝对路径与 `..`），并经过 `normalize_declared_paths` 做语法校验后
  写入 `Task.allowed_paths`。此前该字段虽已在 schema 中存在，但 LLM 路径从不产出 → 约束机制就位却
  从未被真实触发。编排器 `_build_contract` 消费该字段：声明且可用 → 按声明校验（叠加共享文件）；
  声明但不可信 → 留空（scope policy 判 `NEEDS_REVIEW`，**不可验证绝不等于违规**）；未声明 → 维持
  工作区根为唯一边界的历史行为。

### Fixed
- **warn 模式被聚合器悄悄推翻**：`ValidationAggregator` 曾经直接从 `deterministic_result.scope_result`
  重算 `scope_violation → FAIL`，导致即便 `PROJECTFORGE_SCOPE_MODE=warn` 也会把任务判失败，使"先观察、
  再强制"的分阶段上线形同虚设。改为：判定标准的唯一来源是 validator 产出的 criteria，scope 是否在
  warn 下失败由 validator 据 `SCOPE_MODE` 自行决定（仅 enforce 才发 FAIL criterion）。
- **warn 模式误伤任务**：validator 在 warn 下原先对越界发出 `NEEDS_REVIEW` criterion（仍会阻断任务），
  与"观察期不判死"矛盾。改为只把越界写进 `warnings` / `evidence`，由真实运行先收集假阳性率，再切 enforce。

## [0.5.2] - 2026-09-15
### Fixed（P2 小裂缝批量清理，均有证据）
- **`shell=True` 执行 `test_command`（注入面）**：验证器用 shell 跑来自 LLM planner 的
  `test_command`，P19 明令禁止。改为：默认 pytest 调用以安全 argv 列表下发（同时在 Windows 上
  避开带空格的 `sys.executable` 被切碎的问题），自定义命令经 `shlex.split(..., posix=True)`
  转为 argv 且 `shell=False` → `;`、`&&`、`|` 退化为字面参数而非被执行。
  注：曾用 `posix=False` 保 Windows 反斜杠，实测**引号不被剥离**导致
  `python -c "…"` 变成空转的字符串表达式、瞬时"通过"，改回 `posix=True`。
- **产物 id 复用导致重试覆盖**：`{task_id}_output` 等固定 id 让同一任务的多次尝试只留最后一份，
  历史丢失。改为 `{task_id}_{kind}_{token_hex(4)}`——保留 `{task_id}_` 前缀以兼容
  `ArtifactStore.list_for_task`，多次尝试各自成档。
- **`validated_at` 恒为空**：写入 ISO-8601 UTC 时间戳，P19 的 `validation_duration` 才可计算。
  （顺带：`test_deterministic_validator_deterministic` 的全量 dump 对比排除该时间戳。）
- **自测超时 120s 硬编码**：改为 `DeterministicValidator(self_test_timeout=...)` 构造参数，默认仍 120s。
  **并接上 `--timeout` 体系**：`ProjectService._build_executor` 现在把解析后的 `task_timeout`
  注入验证器，即 `--timeout` / `PROJECTFORGE_TASK_TIMEOUT_SECONDS` 同时管住"任务内所有子进程"
  （含自测）。（注：经 service 走的自测预算随之由 120s 变为配置的 task_timeout，默认 300s。）

### Added
- **`EventStore` 去掉 O(n²)**：`append` 原每次重读整个 jsonl 建 id 集（n 大时 O(n²)），
  改为实例级惰性 id 缓存 + 增量更新。保留幂等去重，并补测"换实例重开仍能对既有事件去重"。
- **主循环加全局时长预算**：`ExecutionOrchestrator(max_run_seconds=...)`，主循环以
  `time.monotonic()` 卡预算，超限即以 `TIME_BUDGET_EXCEEDED` 收束（与用户 `CANCELLED` 区分）。
  默认 `None` 维持原不受限行为，属**显式启用**；配套 env `PROJECTFORGE_MAX_RUN_SECONDS`
  （`resolve_max_run_seconds()`，未设/非法值即不受限），无需改代码即可打开闸门。

### 核实后未改动的项
- `ArtifactStore.list_for_task` 的"T1 匹配 T10_x"**实测不重现**：现有实现用
  `startswith(f"{task_id}_")` 的 `_` 边界，`T10_output` 对 `T1_` 为假。
  不改生产代码，补一条 T1/T10 回归测试锁定该边界行为。

## [0.5.0] - 2026-09-15
### Added
- **任务级路径约束（可选启用）**：`Task.allowed_paths` 可声明任务允许修改的路径。
  声明后按声明校验（并自动放行 `requirements.txt` / `pyproject.toml` / `README.md`
  等跨切文件与任意层级的 `__init__.py`）；未声明则维持原行为（以工作区为边界）。
- `PROJECTFORGE_SCOPE_MODE`：`warn`（默认）只把越界记录进验证 warning、不判任务失败；
  `enforce` 才判 `SCOPE_VIOLATION`。**分阶段上线**，避免假阳性一次摧毁约束系统的信任。

### Changed
- scope 判定逻辑抽到 `app/agents/scope_policy.py`：此前 `validator` 与 `cli_adapter`
  各有一份实现（存在漂移风险），现统一委托，并保留薄壳以兼容既有调用。

### Fixed
- 声明路径校验漏掉 Windows 无盘符的根路径（`/abs/path` 的 `is_absolute()` 为 `False`），
  可被解析到工作区之外；改用 `anchor` 判定，同时覆盖盘符相对路径（`C:foo`）。

### Documentation
- README 与 `docs/demo.md` 的 scope 表述改为准确描述：原先宣称"限制允许修改的文件"、
  "越界修改会被判 SCOPE_VIOLATION"，但生产路径中 `allowed_paths` 恒为工作区根，
  该拦截从不触发。现如实说明边界来源与 `warn`/`enforce` 的差别。

## [0.4.2] - 2026-09-14
### Fixed
- **`--planner llm` 完全不可用**：`planner_factory_from_name` 把规则版 planner 的
  import 关在 `"rule"` 分支内，`"llm"` 分支引用它触发 `UnboundLocalError`，
  命令直接崩溃。导入提到函数作用域后修复。
- **LLM planner 缺省 client 缺失**：`LlmPlanner` 在未注入 client 时 `_client` 为 `None`
  （工厂正是这样构造的），触发 `AttributeError` 逃出 `plan()` 的降级捕获，
  破坏"永不抛错、失败回退规则版"契约。改为 `client or httpx.Client(...)`。
- **LLM 调用超时过短**：`LlmPlanner` 与 `InterviewDocBuilder` 使用 httpx 默认 5 秒超时，
  真实 LLM 往返必然超时并静默降级到模板。改为显式 300 秒。
- **审计产物污染任务 checkpoint**：编排器把 artifacts 写进执行工作区，被 CLI 适配器的
  逐任务 `git add -A` 卷入提交，导致每个任务的 diff 夹带上一个任务的产物、
  违背"逐任务精确 diff"的承诺。修复：产物改存 `runs/<run_id>/artifacts`（文档约定布局），
  且适配器提交显式排除 `artifacts`。

### Added
- 回归测试：`tests/test_planner_factory.py`（工厂四条路径 + 降级契约）、
  `tests/test_artifact_isolation.py`（产物位置与 checkpoint 隔离）。

## [0.4.1] - 2026-09-13
### Fixed
- 任务工作区与外层宿主仓库的 git 隔离：工作区若嵌套在无关仓库内，
  原先会复用该仓库（`--is-inside-work-tree` 对任意嵌套路径都返回 true），
  导致执行器的逐任务提交污染宿主仓库历史、checkpoint diff 跨到无关文件。
  现由 orchestrator 比对 `--show-toplevel` 并初始化为自有嵌套仓库，
  adapter 侧 `_workspace_owns_repo()` 双重守卫拒绝读写外部仓库。

## [0.4.0] - 2026-09-08
### Added
- `projectforge interview <project_id>`：面试前突击复习文档（①项目速览 ②架构讲法 ③逐任务深挖 ④执行证据 ⑤红线；LLM 润色 + 模板兜底双路径）
- 计划审批关卡：`plan new` 停在 PLANNING，`plan approve` 后才可执行

## [0.3.0] - 2026-09-08
### Added
- LLM Planner：`projectforge plan <jd_file> --planner llm`（OpenAI 兼容 API，坏输出重试后回退规则版）
- git checkpoint：workspace 自动基线化 + 执行器逐任务提交 + validator GIT 判据
- 超时参数化：`run start/resume --timeout` 与 `PROJECTFORGE_TASK_TIMEOUT_SECONDS`
### Changed
- BREAKING: `--base-dir` 语义改为运行时根（projects/、runs/、workspaces/）

## [0.2.0] - 2026-09-07
### Added
- executor 可插拔（`--executor {hermes,mock}`）+ 离线 MockExecutor
- cancel 真正中断执行（持久粘滞标志 + 任务间检查点）
- 确定性验证真实执行（test_paths/test_command 贯通）
### Changed
- BREAKING: base_dir 单一贯通（v0.3.0 顺带完成同一语义迁移）

## [0.1.2] - 2026-09-07
### Fixed
- replan 支持执行期失败（无 validation/execution 结果的 run）
- run 持久化保留 replan 控制字段
- 事件 id 碰撞导致丢事件（随机后缀 + 稳定排序）

## [0.1.1] - 2026-09-06
### Fixed
- 打包依赖闭包、执行链路修复（ProjectMap/validator workspace）
- sandbox 网络修复（去 --unshare-all，保留宿主网络 + 完整 bind）

## [0.1.0] - 2026-09-05
### Added
- 首个开源版本：JD → 蓝图 → 任务图 → 约束执行 → 验证 / replan

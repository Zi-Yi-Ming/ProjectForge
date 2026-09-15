# Changelog

All notable changes to this project are documented in this file.
Format: Keep a Changelog; versioning: SemVer（0.x 阶段 minor = 能力/破坏性变更，patch = 修复）。

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

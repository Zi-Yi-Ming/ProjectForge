# Changelog

All notable changes to this project are documented in this file.
Format: Keep a Changelog; versioning: SemVer（0.x 阶段 minor = 能力/破坏性变更，patch = 修复）。

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

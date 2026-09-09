# v0.4.0 设计：`projectforge interview` 面试叙事输出

日期：2026-09-08 ｜ 状态：已批准 ｜ 主菜依据：竞品调研确认"面试叙事"为无人占领差异化

## 背景与目标

v0.3.0 完成了 JD → LLM 规划 → 沙箱执行 → 真测试验证 → 审批 replan → git 可审计的闭环，但 blueprint 里积累的面试资产（`interview_depth_points`、`likely_questions`、`claims_to_avoid`、`tradeoffs`）没有任何用户可见输出物。本设计交付 `projectforge interview <project_id>`：生成面试前突击复习文档。

核心场景：**面试前突击复习**——项目怎么讲（30 秒/3 分钟）、每任务深挖问题与回答要点、哪些话不能说。执行证据（git checkpoint 背书）让"项目是真的"有据可查。

## 架构

### 新模块 `app/agents/interview.py`

`InterviewDocBuilder`：
- 输入：`PlanningResult`（从 artifacts 加载）、可选的 run 执行记录（最新 run 的 task_records）
- 输出：markdown 文档字符串
- 两个实现策略，与 planner 降级模式一致：
  - `LlmPolish`：配了 `PROJECTFORGE_LLM_*` 时，把 schema 字段喂给 LLM 加工成流畅叙述（复用 `resolve_llm_config()` 与 LlmPlanner 的 httpx 客户端/JSON 提取模式）
  - 模板兜底：无 key / LLM 失败 → 直接渲染 schema 字段，**永不失败**
- 五小节见下表；④⑤有硬原则：⑤红线原样保留不做 LLM 润色，④证据直接引用 git checkpoint 数据不加工

### 文档结构

| 小节 | 数据来源 | 条件 |
|---|---|---|
| ① 项目速览（30 秒版） | blueprint：one_line_description、business_scenario、technology_stack | 必有 |
| ② 3 分钟架构讲法 | architecture_style、data_flow、core_workflows、design_decisions、tradeoffs | 必有 |
| ③ 逐任务深挖卡 | 每任务 goal、acceptance_criteria、technical_points、interview_points + blueprint.likely_questions | 必有 |
| ④ 执行证据 | 每 DONE 任务的 git commit 区间（head_before..head_after）、变更文件数、验证状态 | 存在 run 记录才出现 |
| ⑤ 红线 | claims_to_avoid、credibility_risks | 必有 |

### CLI 与 service

- `projectforge interview <project_id> [--base-dir] [--out FILE] [--no-llm]`：写 `<base>/projects/<pid>/interview_prep.md`（`--out` 可覆盖）并打印全文；`--no-llm` 强制模板路径
- `ProjectService.interview_prep(project_id, use_llm=True) -> str`：加载 artifacts（`ProjectWorkflow.load_blueprint` 等）+ 最新 run 记录（`JsonExecutionPersistence`）→ `InterviewDocBuilder` 产出

### 搭车项

1. **计划审批关卡**（生命周期语义变更）：`plan_to_ready` 拆为 `plan`（停在 PLANNING，打印任务图）+ `plan approve <project_id>`（到 READY）。`run start` 校验 READY 不变；现有 `plan→READY` 测试改 3-4 处。
2. **CHANGELOG.md**：从 v0.1.0–v0.3.0 release notes 汇总，Keep a Changelog 格式。
3. **删除 ADD_DEPENDENCY 死代码**：`Replanner` 无此生产者（用户已确认两次），删 `app/agents/replanner.py` 与 `app/agents/replan_applier.py`、`app/product/replan_applier.py` 中的 ADD_DEPENDENCY 分支及 schema 相关测试引用。

### 并行活动（不在本 spec 实现范围）

VM 试点 run：将冒烟产生的 12 任务 RAG 计划在 VM 建项并配置 hermes 执行器待命，启动执行由用户决定（真实 token 消耗）。其产出的逐任务 checkpoint 数据将自动充实 ④ 执行证据小节。

## 测试

- 模板路径：确定性 golden 测试（固定 blueprint → 断言文档含五小节、红线原文保留、无 LLM 调用）
- LLM 路径：httpx MockTransport（成功加工 / 坏输出回退模板 / 无 key 回退）
- 审批关卡：plan 停 PLANNING；approve 后 READY；未 approve 时 `run start` 报非 READY
- CLI：`interview` 命令 exit 0、`--out`、`--no-llm`
- VM：对试点项目生成真实文档（真实 LLM 冒烟）

## 不做（YAGNI）

简历/STAR 模式（v0.5 候选）、多文档拆分、Web UI、面试文档的 HTML/PDF 导出。

## 风险

- LLM 润色虚构内容 → prompt 约束"只基于给定字段，不添加未提及的技术"；⑤红线绕过 LLM
- 计划审批关卡破坏现有用户习惯 → 语义变更有 CHANGELOG 说明；`plan` 命令默认行为改为停 PLANNING 属 breaking-minor，v0.4.0 minor 载荷合理

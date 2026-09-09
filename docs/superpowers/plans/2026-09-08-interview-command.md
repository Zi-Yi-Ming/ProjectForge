# v0.4.0 面试叙事输出 实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 交付 `projectforge interview <project_id>`（面试前突击复习文档，LLM 加工 + 模板兜底），加计划审批关卡（plan 停 PLANNING + `plan approve`）、CHANGELOG.md、删除 ADD_DEPENDENCY 死代码，升版 0.4.0。

**Architecture:** 新模块 `app/agents/interview.py`（InterviewDocBuilder：模板渲染 + 可选 LLM 润色，与 planner 同款降级模式）；service 拆 `plan_to_ready` 为 `plan_to_planning` + `approve_plan`；CLI 把 `plan` 改为 typer 子命令组（`plan new` / `plan approve`）并新增 `interview` 命令。

**Tech Stack:** Python 3.10+、pydantic v2、typer、httpx（LLM 润色复用 `resolve_llm_config()`）、pytest。

**Spec:** `docs/superpowers/specs/2026-09-08-interview-command-design.md`

**约定：** 本地测试命令一律 `D:/common/ProjectForge/.venv/Scripts/python.exe -m pytest`（下文简写 `pytest`）；每个 Task 结束跑一次全量 `pytest -q` 确认无回归；VM 全量取证在 Task 7。

---

### Task 1: 删除 ADD_DEPENDENCY 死代码

**Files:**
- Modify: `app/product/replan_applier.py`（删 ADD_DEPENDENCY 分支 :57-67 与 `_product_validate_proposal` 中 :93-96）
- Modify: `app/agents/replan_applier.py`（如含 ADD_DEPENDENCY 处理同样删除）
- Test: `tests/test_validation_criteria.py`（新增守卫测试）

- [ ] **Step 1: 写守卫测试（先确认现状）**

```python
def test_add_dependency_proposal_is_rejected_as_unknown() -> None:
    graph = _graph()
    proposal = _proposal(RecommendedAction.BLOCK, graph)
    # 手工构造一个 ADD_DEPENDENCY 提案（生产者已不存在，属遗留输入兼容）
    from app.schemas.replan import ReplanAction, ReplanChange, ReplanChangeType
    proposal = ReplanProposal(
        proposal_id="prop-add-dep", run_id="run-test", task_id="T1",
        action=ReplanAction.ADD_DEPENDENCY, reason="r", evidence=[],
        affected_task_ids=["T1"],
        proposed_changes=[ReplanChange(change_type=ReplanChangeType.ADD_DEPENDENCY, task_id="T2", target_task_id="T1", title="dep", description="d")],
        forbidden_changes=[], requires_user_approval=True, status=ReplanProposalStatus.APPROVED, created_at="",
    )
    result = ProductReplanApplier().apply(proposal, graph)
    assert not result.success
```

- [ ] **Step 2: 跑测试确认当前行为**

Run: `pytest tests/test_validation_criteria.py -v`
Expected: 若现在走 "unknown action" 失败路径则 PASS；若 ADD_DEPENDENCY 分支存在则可能 PASS（success=False 因 DONE 检查）——记录现状后进入 Step 3。

- [ ] **Step 3: 删除两个 applier 中的 ADD_DEPENDENCY 分支**

`app/product/replan_applier.py`：删除 `elif proposal.action == "ADD_DEPENDENCY":` 到下一个 `elif` 之间的整段（约 :57-67），以及 `_product_validate_proposal` 中 `if change.change_type == "ADD_DEPENDENCY":` 分支（约 :93-96）。`app/agents/replan_applier.py` 中如有同样分支一并删除。**保留** `ReplanChangeType.ADD_DEPENDENCY` 枚举成员（存量 proposal 兼容）。

- [ ] **Step 4: 跑全量测试**

Run: `pytest -q`
Expected: 360+ passed, 0 failed（守卫测试断言 not success）

- [ ] **Step 5: Commit**

```bash
git add -A && git commit -m "refactor: remove ADD_DEPENDENCY apply branches (no producer exists)"
```

---

### Task 2: 计划审批关卡（service 层）

**Files:**
- Modify: `app/product/service.py`（`plan_to_ready` → `plan_to_planning` + `approve_plan`）
- Test: `tests/test_service_plan.py`

- [ ] **Step 1: 改写测试**

`tests/test_service_plan.py` 中 `test_plan_to_ready_*` 三个测试改为：

```python
def test_plan_to_planning_stops_before_ready(tmp_path: Path) -> None:
    service = _service(tmp_path)
    project = service.create("plan-demo")
    planner = FakePlanner()
    result = service.plan_to_planning(project.project_id, SAMPLE_JD, planner=planner)
    assert result.status == ProjectStatus.PLANNING
    assert result.task_graph_ref and result.blueprint_ref and result.jd_profile_ref


def test_approve_plan_moves_to_ready(tmp_path: Path) -> None:
    service = _service(tmp_path)
    project = service.create("plan-demo")
    service.plan_to_planning(project.project_id, SAMPLE_JD, planner=FakePlanner())
    result = service.approve_plan(project.project_id)
    assert result.status == ProjectStatus.READY


def test_approve_plan_requires_planning(tmp_path: Path) -> None:
    service = _service(tmp_path)
    project = service.create("plan-demo")
    with pytest.raises(InvalidProjectStateError):
        service.approve_plan(project.project_id)
```

- [ ] **Step 2: 跑测试确认失败**

Run: `pytest tests/test_service_plan.py -v`
Expected: FAIL — `plan_to_planning` / `approve_plan` 属性不存在

- [ ] **Step 3: 实现 service 拆分**

`app/product/service.py`：把 `plan_to_ready` 整体改名为 `plan_to_planning`，方法体把最后两行

```python
        self.transition_to(project_id, ProjectStatus.READY)
        return self.load(project_id)
```

改为：

```python
        self.transition_to(project_id, ProjectStatus.PLANNING)
        return self.load(project_id)
```

并在其后新增：

```python
    def approve_plan(self, project_id: str) -> Project:
        """Move a PLANNING project (plan gate) to READY after human review."""
        project = self.load(project_id)
        if project.status != ProjectStatus.PLANNING:
            raise InvalidProjectStateError(
                f"Project {project_id} is not PLANNING; cannot approve from {project.status}."
            )
        if not project.task_graph_ref:
            raise InvalidProjectStateError(f"Project {project_id} has no task graph to approve.")
        return self.transition_to(project_id, ProjectStatus.READY)
```

- [ ] **Step 4: 跑测试**

Run: `pytest tests/test_service_plan.py -v && pytest -q`
Expected: PASS；全量可能暴露 `plan_to_ready` 其他引用（grep 确认）——全部改为新 API。

- [ ] **Step 5: Commit**

```bash
git add -A && git commit -m "feat!: split planning into plan_to_planning + approve_plan gate"
```

---

### Task 3: 计划审批关卡（CLI 层）

**Files:**
- Modify: `app/cli/app.py`（`plan` 命令改为 typer 子命令组：`plan new` / `plan approve`）
- Modify: `tests/test_cli_plan.py`、`tests/test_mock_e2e.py`（CLI 调用点）
- Modify: `docs/demo.md`、`README.md`（命令示例加 approve 步骤）

- [ ] **Step 1: 改 CLI 测试**

`tests/test_cli_plan.py` 所有 `["plan", str(jd_path), ...]` 改为 `["plan", "new", str(jd_path), ...]`；`test_cli_plan_rule_end_to_end` 在 plan new 后加：

```python
    result = runner.invoke(app, ["plan", "new", str(jd_path), "--planner", "rule", "--base-dir", str(base)])
    assert result.exit_code == 0
    assert "Status: PLANNING" in result.output
    pid = [line.split(": ", 1)[1] for line in result.output.splitlines() if line.startswith("Project ID: ")][0]
    result = runner.invoke(app, ["plan", "approve", pid, "--base-dir", str(base)])
    assert result.exit_code == 0
    assert "Status: READY" in result.output
```

（原 "Status: READY" 断言从 plan new 移除。）`test_mock_e2e.py::test_cli_run_start_with_mock_executor` 同样加 approve 步骤。

- [ ] **Step 2: 实现 CLI**

`app/cli/app.py`：删掉 `@app.command() def plan(...)`，改为：

```python
plan_app = typer.Typer(help="从 JD 规划项目并审批")
app.add_typer(plan_app, name="plan")


@plan_app.command("new")
def plan_new(jd_file: Path, planner_name: str = typer.Option("rule", "--planner"), base_dir: Path | None = typer.Option(None, "--base-dir"), json_out: Path | None = typer.Option(None, "--json-out")) -> None:
    # 原 plan 命令体：create + plan_to_planning + 打印任务图
    # Status 行改为 PLANNING，末尾追加提示：
    typer.echo("下一步: projectforge plan approve <project_id>")


@plan_app.command("approve")
def plan_approve(project_id: str, base_dir: Path | None = typer.Option(None, "--base-dir")) -> None:
    service = _build_service(base_dir)
    try:
        result = service.approve_plan(project_id)
    except ProjectNotFoundError as exc:
        typer.echo(f"Error: {exc}", err=True)
        raise typer.Exit(code=1) from exc
    except InvalidProjectStateError as exc:
        typer.echo(f"Error: {exc}", err=True)
        raise typer.Exit(code=1) from exc
    typer.echo(f"Plan approved")
    typer.echo(f"Project ID: {result.project_id}")
    typer.echo(f"Status: {result.status.value}")
```

- [ ] **Step 3: 更新 docs/demo.md 与 README**

demo.md「用 CLI 体验」与 README「快速开始 §1」的 `projectforge plan ./jd.txt` 后插入：

```bash
projectforge plan approve <project_id> --base-dir .runtime
```

- [ ] **Step 4: 跑全量**

Run: `pytest -q`
Expected: 0 failed

- [ ] **Step 5: Commit**

```bash
git add -A && git commit -m "feat!: plan command stops at PLANNING; add plan approve gate"
```

---

### Task 4: InterviewDocBuilder 模板路径

**Files:**
- Create: `app/agents/interview.py`
- Test: `tests/test_interview.py`

- [ ] **Step 1: 写失败测试**

```python
from __future__ import annotations

from app.agents.interview import InterviewDocBuilder
from app.agents.planner import RuleBasedPlanner
from app.schemas.blueprint import UserProfile

SAMPLE_JD = "岗位：Java 后端工程师。要求：熟悉 Java、Spring Boot、MySQL。"


def _planning_result():
    return RuleBasedPlanner().plan(SAMPLE_JD)


def test_template_doc_contains_all_sections() -> None:
    r = _planning_result()
    doc = InterviewDocBuilder().build(r.jd_profile, r.blueprint, r.task_graph, records=None)
    for section in ("项目速览", "3 分钟架构讲法", "逐任务深挖", "红线"):
        assert section in doc
    # 红线原样保留
    for claim in r.blueprint.claims_to_avoid:
        assert claim in doc
    assert "执行证据" not in doc  # 无 run 记录时不出现


def test_execution_evidence_section_appears_with_records() -> None:
    from app.schemas.execution import TaskExecutionRecord
    from app.schemas.implementation import (
        AgentExecutionResult, ExecutionStatus as ImplExec, GitCheckpoint, ScopeStatus,
    )
    from app.schemas.validation import ValidationResult, ValidationStatus

    r = _planning_result()
    record = TaskExecutionRecord(
        task_id=r.task_graph.tasks[0].id, phase=r.task_graph.tasks[0].phase_id,
        title=r.task_graph.tasks[0].title, status="DONE",
        execution_result=AgentExecutionResult(
            task_id=r.task_graph.tasks[0].id, agent="mock",
            status=ImplExec.IMPLEMENTED, iterations=1, changed_files=["a.py"],
            scope_status=ScopeStatus.WITHIN_SCOPE, test_results=[],
            git_checkpoint=GitCheckpoint(head_before="a" * 40, head_after="b" * 40, changed_files=["a.py"]),
        ),
        validation_result=ValidationResult(
            task_id=r.task_graph.tasks[0].id, status=ValidationStatus.PASS,
            criterion_results=[], test_results=[], scope_result="WITHIN_SCOPE",
            changed_files=["a.py"], evidence=[], failures=[], warnings=[],
            manual_review_items=[], llm_review=None, repair_cycle=0, validated_at="",
        ),
    )
    doc = InterviewDocBuilder().build(r.jd_profile, r.blueprint, r.task_graph, records=[record])
    assert "执行证据" in doc
    assert "a.py" in doc
```

- [ ] **Step 2: 跑测试确认失败**

Run: `pytest tests/test_interview.py -v`
Expected: FAIL — `No module named 'app.agents.interview'`

- [ ] **Step 3: 实现模板渲染**

`app/agents/interview.py`：

```python
from __future__ import annotations

from app.schemas.blueprint import ProjectBlueprint
from app.schemas.execution import TaskExecutionRecord
from app.schemas.jd import JDProfile
from app.schemas.task import TaskGraph


class InterviewDocBuilder:
    """Renders the pre-interview cram document. LLM polish is layered on
    top by `build_with_llm`; this class itself is fully deterministic."""

    def build(
        self,
        jd_profile: JDProfile,
        blueprint: ProjectBlueprint,
        task_graph: TaskGraph,
        records: list[TaskExecutionRecord] | None = None,
    ) -> str:
        lines: list[str] = []
        lines.append("# 面试准备：{name}".format(name=blueprint.name))
        lines.append("")
        lines.append("## 项目速览（30 秒版）")
        lines.append("")
        lines.append(blueprint.one_line_description)
        lines.append("")
        lines.append(f"- 业务场景：{blueprint.business_scenario}")
        lines.append(f"- 目标用户：{'、'.join(blueprint.target_users) or '—'}")
        lines.append(f"- 技术栈：{'、'.join(blueprint.technology_stack)}")
        lines.append("")
        lines.append("## 3 分钟架构讲法")
        lines.append("")
        lines.append(f"- 架构风格：{blueprint.architecture_style}")
        lines.append(f"- 数据流：{blueprint.data_flow}")
        for flow in blueprint.core_workflows:
            lines.append(f"- 核心流程：{flow}")
        for prob, sol in zip(blueprint.engineering_problems, blueprint.engineering_solutions):
            lines.append(f"- 工程亮点：{prob} → {sol}")
        for decision in blueprint.design_decisions:
            lines.append(f"- 设计决策：{decision}")
        for t in blueprint.tradeoffs:
            lines.append(f"- 权衡：{t}")
        lines.append("")
        lines.append("## 逐任务深挖")
        lines.append("")
        for task in task_graph.tasks:
            lines.append(f"### {task.id} {task.title} [{task.scope}]")
            lines.append(f"- 目标：{task.goal}")
            for c in task.acceptance_criteria:
                lines.append(f"- 验收：{c}")
            for p in task.technical_points:
                lines.append(f"- 技术点：{p}")
            for ip in task.interview_points:
                lines.append(f"- 面试表达：{ip}")
            lines.append("")
        done = [r for r in (records or []) if r.status == "DONE"]
        if done:
            lines.append("## 执行证据")
            lines.append("")
            for r in done:
                ck = r.execution_result.git_checkpoint if r.execution_result else None
                ran = f"{(ck.head_before or '')[:8]}..{(ck.head_after or '')[:8]}" if ck else "—"
                lines.append(f"- {r.task_id} {r.title}: 验证 {r.validation_result.status.value if r.validation_result else '—'}，提交 {ran}，变更 {len(ck.changed_files) if ck else 0} 个文件")
            lines.append("")
        lines.append("## 红线（这些话不能说）")
        lines.append("")
        for claim in blueprint.claims_to_avoid:
            lines.append(f"- ❌ {claim}")
        for risk in blueprint.credibility_risks:
            lines.append(f"- ⚠️ {risk}")
        return "\n".join(lines)
```


- [ ] **Step 4: 跑测试**

Run: `pytest tests/test_interview.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add app/agents/interview.py tests/test_interview.py && git commit -m "feat: InterviewDocBuilder template renderer"
```

---

### Task 5: LLM 润色路径

**Files:**
- Modify: `app/agents/interview.py`
- Test: `tests/test_interview.py`

- [ ] **Step 1: 写 LLM 路径测试**

```python
import httpx

from app.agents.llm_planner import LlmConfig


def test_llm_polish_replaces_quick_pitch(tmp_path) -> None:
    r = _planning_result()
    llm_json = json.dumps(
        {"quick_pitch": "这是一个把岗位 JD 变成可验证工程项目的 RAG 系统。",
         "architecture_story": "整体采用 FastAPI + LangChain 的分层架构，数据从文档解析进入向量库。"},
        ensure_ascii=False,
    )

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"choices": [{"message": {"content": llm_json}}]})

    config = LlmConfig(base_url="https://api.test/v1", api_key="k", model="m")
    builder = InterviewDocBuilder(config=config, client=httpx.Client(transport=httpx.MockTransport(handler)))
    doc = builder.build(r.jd_profile, r.blueprint, r.task_graph, records=None)
    assert "这是一个把岗位 JD 变成可验证工程项目的 RAG 系统。" in doc


def test_llm_polish_failure_falls_back_to_template() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500)

    config = LlmConfig(base_url="https://api.test/v1", api_key="k", model="m")
    builder = InterviewDocBuilder(config=config, client=httpx.Client(transport=httpx.MockTransport(handler)))
    r = _planning_result()
    doc = builder.build(r.jd_profile, r.blueprint, r.task_graph, records=None)
    assert "项目速览" in doc  # 模板兜底成功


def test_no_llm_config_skips_polish() -> None:
    r = _planning_result()
    builder = InterviewDocBuilder(config=None, client=None)
    doc = builder.build(r.jd_profile, r.blueprint, r.task_graph, records=None)
    assert "项目速览" in doc
```

- [ ] **Step 2: 实现 LLM 润色**

`InterviewDocBuilder` 增加构造参数 `config: LlmConfig | None = None, client: httpx.Client | None = None`；`build()` 改为：

```python
    def build(self, jd_profile, blueprint, task_graph, records=None) -> str:
        pitches: dict[str, str] | None = None
        if self._config is not None:
            pitches = self._llm_pitch(jd_profile, blueprint)
        return self._render(jd_profile, blueprint, task_graph, records, pitches)
```

`_llm_pitch` 用 `self._client.post(f"{config.base_url}/chat/completions", ...)`（system prompt：把 blueprint JSON 加工成 quick_pitch/architecture_story 两个字符串，**只允许使用给定字段中的技术**；temperature 0.3），异常/坏 JSON 返回 None（回退模板）。`_render` 接受 `pitches` 参数：非 None 时 ①② 小节用 LLM 文案，否则模板文案。⑤红线与 ③④ 永远模板渲染。50 行以内。

- [ ] **Step 3: 跑测试**

Run: `pytest tests/test_interview.py -v && pytest -q`
Expected: 全 PASS

- [ ] **Step 4: Commit**

```bash
git add -A && git commit -m "feat: LLM polish for interview doc with template fallback"
```

---

### Task 6: service + CLI 接线

**Files:**
- Modify: `app/product/service.py`（`interview_prep` 方法）
- Modify: `app/cli/app.py`（`interview` 命令）
- Test: `tests/test_service_plan.py`、`tests/test_cli_plan.py`

- [ ] **Step 1: service 测试**

```python
def test_interview_prep_writes_doc(tmp_path: Path) -> None:
    from tests.fakes import FakePlanner

    service = _service(tmp_path)
    project = service.create("plan-demo")
    service.plan_to_planning(project.project_id, SAMPLE_JD, planner=FakePlanner())
    service.approve_plan(project.project_id)
    # 用 mock 执行器产生一条带执行证据的 run（沿用 v0.2.0 的模式）
    graph = ProjectWorkflow(base_dir=tmp_path).load_task_graph(project.project_id)
    from app.agents.orchestrator import ExecutionOrchestrator

    run_dir = tmp_path / "workspaces" / project.project_id
    run_dir.mkdir(parents=True, exist_ok=True)
    run = service.run_control.start_run(
        project, graph, run_dir,
        ExecutionOrchestrator(adapter=MockExecutor(workspace=run_dir)),
    )
    service.run_control.complete_run(project.project_id, run.run_id, run.status)

    out = service.interview_prep(project.project_id, use_llm=False)
    assert "interview_prep.md" in out
    text = Path(out).read_text(encoding="utf-8")
    assert "项目速览" in text
    assert "执行证据" in text
```

（`MockExecutor` 从 `app.agents.mock_executor` 导入；`ProjectWorkflow` 已在文件顶部导入。）

- [ ] **Step 2: 实现 service**

```python
    def interview_prep(self, project_id: str, use_llm: bool = True, out_path: Path | None = None) -> str:
        from app.agents.interview import InterviewDocBuilder
        from app.agents.llm_planner import resolve_llm_config

        workflow = ProjectWorkflow(base_dir=self.base_dir)
        jd_profile = workflow.load_jd_profile(project_id)
        blueprint = workflow.load_blueprint(project_id)
        task_graph = workflow.load_task_graph(project_id)
        records = self._latest_run_records(project_id)
        config = resolve_llm_config() if use_llm else None
        doc = InterviewDocBuilder(config=config).build(jd_profile, blueprint, task_graph, records)
        target = out_path or self.base_dir / "projects" / project_id / "interview_prep.md"
        Path(target).write_text(doc, encoding="utf-8")
        return str(target)

    def _latest_run_records(self, project_id: str) -> list[TaskExecutionRecord] | None:
        project = self.load(project_id)
        if not project.last_run_id:
            return None
        try:
            return list(self.run_control.execution_persistence.load_run(project.last_run_id).task_results)
        except FileNotFoundError:
            return None
```

（`TaskExecutionRecord` 从 `app.schemas.execution` 导入。）

- [ ] **Step 3: CLI 命令**

```python
@app.command()
def interview(project_id: str, base_dir: Path | None = typer.Option(None, "--base-dir"), out: Path | None = typer.Option(None, "--out", help="输出文件路径"), no_llm: bool = typer.Option(False, "--no-llm", help="跳过 LLM 润色")) -> None:
    service = _build_service(base_dir)
    try:
        path = service.interview_prep(project_id, use_llm=not no_llm, out_path=out)
    except ProjectNotFoundError as exc:
        typer.echo(f"Error: {exc}", err=True)
        raise typer.Exit(code=1) from exc
    typer.echo(path)
    typer.echo(Path(path).read_text(encoding="utf-8"))
```

- [ ] **Step 4: CLI 测试**

```python
def test_cli_interview_command(tmp_path: Path) -> None:
    # plan new + approve + run mock 后
    result = runner.invoke(app, ["interview", pid, "--base-dir", str(base), "--no-llm"])
    assert result.exit_code == 0
    assert "项目速览" in result.output
```

- [ ] **Step 5: 全量 + Commit**

Run: `pytest -q` → 0 failed

```bash
git add -A && git commit -m "feat: projectforge interview command (service + CLI)"
```

---

### Task 7: CHANGELOG + 版本收尾 + VM 取证

**Files:**
- Create: `CHANGELOG.md`
- Modify: `pyproject.toml`（version = "0.4.0"）
- Modify: `README.md`（徽章区无需改；确认无过期内容）

- [ ] **Step 1: CHANGELOG.md**

```markdown
# Changelog

All notable changes to this project are documented in this file.
Format: Keep a Changelog; versioning: SemVer (0.x: minor = capability/breaking, patch = fixes).

## [0.4.0] - 2026-09-08
### Added
- `projectforge interview <project_id>`: 面试前突击复习文档（LLM 加工 + 模板兜底，双模式）
- 计划审批关卡：`plan new` 停在 PLANNING，`plan approve` 后才可执行

## [0.3.0] - 2026-09-08
### Added
- LLM Planner：`projectforge plan <jd_file> --planner llm`（OpenAI 兼容，坏输出回退规则版）
- git checkpoint：workspace 自动基线化 + 执行器逐任务提交 + validator GIT 判据
- 超时参数化：`--timeout` 与 `PROJECTFORGE_TASK_TIMEOUT_SECONDS`
### Changed
- BREAKING: `--base-dir` 语义改为运行时根（projects/、runs/、workspaces/）

## [0.2.0] - 2026-09-08
### Added
- executor 可插拔（--executor {hermes,mock}）+ 离线 MockExecutor
- cancel 真正中断执行（持久粘滞标志 + 任务间检查点）
- 确定性验证真实执行（test_paths/test_command 贯通）
### Changed
- BREAKING: base_dir 单一贯通（同上，v0.2.0 内含于 0.3.0 说明保留）

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
```

- [ ] **Step 2: 版本 bump + 全量**

pyproject `version = "0.4.0"`；`pytest -q` ×2 → 0 failed。

- [ ] **Step 3: Commit + push + CI**

```bash
git add -A && git commit -m "chore: prepare v0.4.0 release" && git pull --rebase origin master && git push origin master
```

- [ ] **Step 4: VM 全量取证**

VM 上 `git fetch && git reset --hard origin/master && git clean -fdq app tests docs scripts .github`，nohup 跑全量，预期 380+ passed / 0 skipped。

- [ ] **Step 5: Tag + Release（等用户确认 PyPI 凭证状态后）**

```bash
git tag -a v0.4.0 -m "ProjectForge v0.4.0: interview prep documents, plan approval gate" && git push origin v0.4.0
gh release create v0.4.0 --title "ProjectForge v0.4.0" --notes <release notes>
```

注意：发 Release 会触发 PyPI publish（trusted publishing 已通），自动发布 jdforge 0.4.0。

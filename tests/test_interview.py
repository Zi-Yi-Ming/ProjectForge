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
    for risk in r.blueprint.credibility_risks:
        assert risk in doc
    assert "执行证据" not in doc  # 无 run 记录时不出现


def test_template_doc_includes_task_details() -> None:
    r = _planning_result()
    doc = InterviewDocBuilder().build(r.jd_profile, r.blueprint, r.task_graph, records=None)
    first = r.task_graph.tasks[0]
    assert first.id in doc and first.title in doc
    for c in first.acceptance_criteria:
        assert c in doc
    for ip in first.interview_points:
        assert ip in doc


def test_execution_evidence_section_appears_with_records() -> None:
    from app.schemas.execution import TaskExecutionRecord
    from app.schemas.implementation import (
        AgentExecutionResult, ExecutionStatus as ImplExec, GitCheckpoint, ScopeStatus,
    )
    from app.schemas.validation import ValidationResult, ValidationStatus

    r = _planning_result()
    first = r.task_graph.tasks[0]
    record = TaskExecutionRecord(
        task_id=first.id, phase=first.phase_id, title=first.title, status="DONE",
        execution_result=AgentExecutionResult(
            task_id=first.id, agent="mock",
            status=ImplExec.IMPLEMENTED, iterations=1, changed_files=["a.py"],
            scope_status=ScopeStatus.WITHIN_SCOPE, test_results=[],
            git_checkpoint=GitCheckpoint(head_before="a" * 40, head_after="b" * 40, changed_files=["a.py"]),
        ),
        validation_result=ValidationResult(
            task_id=first.id, status=ValidationStatus.PASS,
            criterion_results=[], test_results=[], scope_result="WITHIN_SCOPE",
            changed_files=["a.py"], evidence=[], failures=[], warnings=[],
            manual_review_items=[], llm_review=None, repair_cycle=0, validated_at="",
        ),
    )
    doc = InterviewDocBuilder().build(r.jd_profile, r.blueprint, r.task_graph, records=[record])
    assert "执行证据" in doc
    assert "a.py" in doc
    assert ("a" * 40)[:8] in doc and ("b" * 40)[:8] in doc


def test_user_profile_fields_rendered() -> None:
    r = _planning_result()
    doc = InterviewDocBuilder().build(
        r.jd_profile, r.blueprint, r.task_graph, records=None,
        user_profile=UserProfile(basic_skills=["Java"], weekly_hours=8),
    )
    assert "Java" in doc

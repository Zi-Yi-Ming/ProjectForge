from __future__ import annotations

import json

import httpx

from app.agents.interview import InterviewDocBuilder
from app.agents.llm_planner import LlmConfig
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
    # 每个任务卡片末尾渲染 blueprint.likely_questions（RuleBasedPlanner 产出非空）
    assert r.blueprint.likely_questions
    assert any(q in doc for q in r.blueprint.likely_questions)


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
    assert "每周 8 小时" in doc


def _llm_builder(content: str) -> InterviewDocBuilder:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"choices": [{"message": {"content": content}}]})

    config = LlmConfig(base_url="https://api.test/v1", api_key="k", model="m")
    return InterviewDocBuilder(config=config, client=httpx.Client(transport=httpx.MockTransport(handler)))


def test_llm_polish_replaces_quick_pitch_and_story() -> None:
    r = _planning_result()
    content = json.dumps({
        "quick_pitch": "这是一个把岗位 JD 变成可验证工程项目的 RAG 系统。",
        "architecture_story": "整体采用 FastAPI + LangChain 分层架构，数据从文档解析进入向量库再回流答案。",
    }, ensure_ascii=False)
    doc = _llm_builder(content).build(r.jd_profile, r.blueprint, r.task_graph, records=None)
    assert "这是一个把岗位 JD 变成可验证工程项目的 RAG 系统。" in doc
    assert "整体采用 FastAPI + LangChain 分层架构" in doc
    # 红线与逐任务深挖不受 LLM 影响
    for claim in r.blueprint.claims_to_avoid:
        assert claim in doc
    assert "逐任务深挖" in doc


def test_llm_polish_failure_falls_back_to_template() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500)

    config = LlmConfig(base_url="https://api.test/v1", api_key="k", model="m")
    builder = InterviewDocBuilder(config=config, client=httpx.Client(transport=httpx.MockTransport(handler)))
    r = _planning_result()
    doc = builder.build(r.jd_profile, r.blueprint, r.task_graph, records=None)
    assert "项目速览" in doc  # 模板兜底成功
    assert builder.last_polish_failed is True


def test_no_llm_config_skips_polish() -> None:
    r = _planning_result()
    builder = InterviewDocBuilder(config=None, client=None)
    doc = builder.build(r.jd_profile, r.blueprint, r.task_graph, records=None)
    assert "项目速览" in doc
    assert builder.last_polish_failed is False

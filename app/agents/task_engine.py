from __future__ import annotations

import re
from collections import deque
from dataclasses import dataclass
from typing import Any

from app.agents.jd_analyzer import _normalize_skill
from app.schemas.blueprint import ProjectBlueprint
from app.schemas.task import (
    Phase,
    ScopeLevel,
    Task,
    TaskGraph,
    TaskGraphValidation,
    TaskStatus,
)


def _safe_id(text: str) -> str:
    cleaned = re.sub(r"[^a-zA-Z0-9_-]+", "_", text.lower()).strip("_")
    return cleaned or "task"


def _next_task_id(phase_id: str, index: int) -> str:
    return f"{phase_id}__t{index + 1:02d}"


def _scope_level(level: str, label: str, description: str) -> ScopeLevel:
    return ScopeLevel(level=level, label=label, description=description)


class TaskEngine:
    def __init__(self) -> None:
        self.phases: list[Phase] = []
        self.tasks: list[Task] = []

    def build(self, blueprint: ProjectBlueprint) -> TaskGraph:
        self.phases = []
        self.tasks = []
        scope_levels = blueprint.scope_levels or [
            _scope_level("L1_core", "Core", "最小业务闭环"),
            _scope_level("L2_jd", "JD Alignment", "补齐 JD 核心能力"),
            _scope_level("L3_engineering", "Engineering Depth", "工程深度与面试表达"),
            _scope_level("L4_advanced", "Advanced", "可选增强"),
        ]
        self._add_phases(scope_levels)
        self._add_foundation_tasks(blueprint)
        self._add_core_business_tasks(blueprint)
        self._add_engineering_tasks(blueprint)
        self._add_advanced_tasks(blueprint)
        self._link_dependencies()
        validation = self._validate()
        required = sum(1 for t in self.tasks if t.scope != "Advanced")
        optional = sum(1 for t in self.tasks if t.scope == "Advanced")
        return TaskGraph(
            project=blueprint.name or blueprint.source_repo or "Project",
            phases=list(self.phases),
            tasks=list(self.tasks),
            total_tasks=len(self.tasks),
            required_tasks=required,
            optional_tasks=optional,
            graph_validation=validation,
        )

    def _add_phases(self, scope_levels: list[Any]) -> None:
        mapping = {
            "L1_core": "Foundation",
            "L2_jd": "Core Business",
            "L3_engineering": "Engineering Depth",
            "L4_advanced": "Advanced",
        }
        for idx, level in enumerate(scope_levels):
            name = mapping.get(level.level, level.label)
            self.phases.append(
                Phase(
                    id=_safe_id(level.level),
                    name=name,
                    description=level.description,
                    order=idx + 1,
                    scope=level.level,
                )
            )

    def _add_foundation_tasks(self, blueprint: ProjectBlueprint) -> None:
        phase = self._phase_by_scope("L1_core")
        if not phase:
            return
        self.tasks.append(
            Task(
                id=_next_task_id(phase.id, len([t for t in self.tasks if t.phase_id == phase.id])),
                phase_id=phase.id,
                title="项目初始化与模块划分",
                goal="建立项目骨架、模块结构与基础配置。",
                why="先有稳定骨架，后续能力才能独立验证。",
                scope="Core",
                prerequisites=[],
                inputs=[blueprint.technology_stack[0] if blueprint.technology_stack else "Java"],
                expected_output="可编译的项目结构与基础配置。",
                implementation_scope="初始化仓库、模块拆分、统一构建配置。",
                acceptance_criteria=[
                    "项目可按依赖顺序编译通过。",
                    "模块边界清晰，核心模块可独立运行。",
                    "基础配置与环境变量可加载。",
                ],
                out_of_scope=[
                    "具体业务功能实现",
                    "数据库生产 schema",
                    "外部服务对接",
                ],
                technical_points=["模块化结构", "构建配置", "环境抽象"],
                interview_points=["为什么这样划分模块？", "核心模块的依赖方向是什么？"],
            )
        )
        self.tasks.append(
            Task(
                id=_next_task_id(phase.id, len([t for t in self.tasks if t.phase_id == phase.id])),
                phase_id=phase.id,
                title="数据模型与存储设计",
                goal="设计核心业务表结构与数据访问边界。",
                why="数据模型决定后续业务实现与扩展成本。",
                scope="Core",
                prerequisites=[self.tasks[-1].id],
                inputs=blueprint.technology_stack,
                expected_output="核心实体、Repository 接口与基础事务边界。",
                implementation_scope="核心表设计、主键策略、索引与事务边界。",
                acceptance_criteria=[
                    "核心业务实体可持久化。",
                    "基础 CRUD 可运行。",
                    "事务边界清晰。",
                ],
                out_of_scope=[
                    "复杂关联关系优化",
                    "分库分表",
                    "数据迁移脚本",
                ],
                technical_points=["表结构设计", "索引策略", "Repository 模式"],
                interview_points=["为什么这样设计主键？", "事务边界为什么放在这一层？"],
            )
        )

    def _add_core_business_tasks(self, blueprint: ProjectBlueprint) -> None:
        phase = self._phase_by_scope("L2_jd")
        if not phase:
            return
        foundation = [t for t in self.tasks if t.scope == "Core"]
        prev = foundation[-1].id if foundation else None
        self.tasks.append(
            Task(
                id=_next_task_id(phase.id, len([t for t in self.tasks if t.phase_id == phase.id])),
                phase_id=phase.id,
                title="核心业务服务实现",
                goal="实现主要业务用例与核心流程。",
                why="把 Blueprint 中的业务场景转化为可运行能力。",
                scope="JD Alignment",
                prerequisites=[prev] if prev else [],
                inputs=blueprint.core_features or ["核心业务服务"],
                expected_output="核心业务接口可调用、主流程可跑通。",
                implementation_scope="按 core_features 实现核心服务与接口。",
                acceptance_criteria=[
                    "核心业务接口可被调用。",
                    "主流程成功完成。",
                    "异常场景有基本处理。",
                ],
                out_of_scope=[
                    "高级工程问题",
                    "性能优化",
                    "容灾与监控",
                ],
                technical_points=blueprint.core_features[:3],
                interview_points=["核心流程的输入输出是什么？", "异常路径如何处理的？"],
            )
        )
        if any("REST API" in s for s in (blueprint.technology_stack or [])) or any(
            "REST API" in s for s in (blueprint.engineering_topic_mapping or {})
        ):
            prev = self.tasks[-1].id
            self.tasks.append(
                Task(
                    id=_next_task_id(phase.id, len([t for t in self.tasks if t.phase_id == phase.id])),
                    phase_id=phase.id,
                    title="接口层与校验规范",
                    goal="统一 REST 风格接口、参数校验与错误响应。",
                    why="接口规范影响联调成本与面试表达。",
                    scope="JD Alignment",
                    prerequisites=[prev],
                    inputs=["REST API"],
                    expected_output="接口文档、统一错误码与参数校验逻辑。",
                    implementation_scope="统一入口、DTO、异常映射与接口说明。",
                    acceptance_criteria=[
                        "接口风格统一。",
                        "参数非法时有明确错误返回。",
                        "核心接口可被前端或测试调用。",
                    ],
                    out_of_scope=[
                        "GraphQL",
                        "权限体系",
                        "限流降级",
                    ],
                    technical_points=["REST 规范", "参数校验", "错误码设计"],
                    interview_points=["为什么用 REST 而不是 RPC？", "错误码为什么这样设计？"],
                )
            )

    def _add_engineering_tasks(self, blueprint: ProjectBlueprint) -> None:
        phase = self._phase_by_scope("L3_engineering")
        if not phase:
            return
        core_tasks = [t for t in self.tasks if t.scope == "JD Alignment"]
        prev = core_tasks[-1].id if core_tasks else None
        if "Redis" in (blueprint.technology_stack or []):
            self.tasks.append(
                Task(
                    id=_next_task_id(phase.id, len([t for t in self.tasks if t.phase_id == phase.id])),
                    phase_id=phase.id,
                    title="热点数据缓存策略",
                    goal="对热点读取增加缓存，并设计失效与降级。",
                    why="缓存是 JD 中常见的工程考察点。",
                    scope="Engineering Depth",
                    prerequisites=[prev] if prev else [],
                    inputs=["Redis"],
                    expected_output="热点数据可被缓存，失效策略明确。",
                    implementation_scope="缓存读写、失效规则与降级路径。",
                    acceptance_criteria=[
                        "热点查询优先走缓存。",
                        "缓存失效后能回源数据库。",
                        "缓存故障时服务仍可用。",
                    ],
                    out_of_scope=[
                        "分布式缓存一致性协议",
                        "多级缓存",
                        "热点 Key 自动发现",
                    ],
                    technical_points=["Cache Aside", "缓存失效", "降级策略"],
                    interview_points=["为什么用 Cache Aside？", "缓存和数据库不一致怎么办？"],
                )
            )
        if any(s in (blueprint.technology_stack or []) for s in {"Kafka", "RabbitMQ", "MQ"}):
            prev = self.tasks[-1].id
            self.tasks.append(
                Task(
                    id=_next_task_id(phase.id, len([t for t in self.tasks if t.phase_id == phase.id])),
                    phase_id=phase.id,
                    title="异步消息投递与消费",
                    goal="引入消息队列解耦核心流程，实现异步投递。",
                    why="MQ 考察异步解耦、削峰与失败处理。",
                    scope="Engineering Depth",
                    prerequisites=[prev],
                    inputs=[s for s in (blueprint.technology_stack or []) if s in {"Kafka", "RabbitMQ", "MQ"}],
                    expected_output="消息可投递、可消费、失败可重试。",
                    implementation_scope="Producer、Consumer、基础重试与监控。",
                    acceptance_criteria=[
                        "主流程发送消息成功。",
                        "Consumer 可处理消息。",
                        "消费失败可重试。",
                    ],
                    out_of_scope=[
                        "Exactly Once 语义",
                        "跨地域容灾",
                        "消息审计",
                    ],
                    technical_points=["异步解耦", "Producer/Consumer", "重试策略"],
                    interview_points=["为什么这里用 MQ？", "消费失败怎么处理？"],
                )
            )
            self.tasks.append(
                Task(
                    id=_next_task_id(phase.id, len([t for t in self.tasks if t.phase_id == phase.id])),
                    phase_id=phase.id,
                    title="幂等与重复消息处理",
                    goal="保证重复消息不会导致重复业务执行。",
                    why="幂等是 MQ 场景的核心工程问题。",
                    scope="Engineering Depth",
                    prerequisites=[self.tasks[-1].id],
                    inputs=["Idempotency"],
                    expected_output="重复消息可被识别，业务只执行一次。",
                    implementation_scope="幂等键设计、去重逻辑与测试。",
                    acceptance_criteria=[
                        "相同消息多次投递只产生一次有效执行。",
                        "并发重复提交行为确定。",
                        "对应测试通过。",
                    ],
                    out_of_scope=[
                        "分布式事务",
                        "跨服务幂等",
                        "全局唯一键基础设施",
                    ],
                    technical_points=["幂等键", "去重表", "并发控制"],
                    interview_points=["幂等为什么放在 Consumer 做？", "重复消息来源有哪些？"],
                )
            )

    def _add_advanced_tasks(self, blueprint: ProjectBlueprint) -> None:
        phase = self._phase_by_scope("L4_advanced")
        if not phase:
            return
        engineering = [t for t in self.tasks if t.scope == "Engineering Depth"]
        prev = engineering[-1].id if engineering else None
        self.tasks.append(
            Task(
                id=_next_task_id(phase.id, len([t for t in self.tasks if t.phase_id == phase.id])),
                phase_id=phase.id,
                title="性能测试与优化",
                goal="对核心路径做性能评估与优化。",
                why="Advanced 层提供可选的性能叙事。",
                scope="Advanced",
                prerequisites=[prev] if prev else [],
                inputs=["Performance"],
                expected_output="核心接口性能基线报告。",
                implementation_scope="压测脚本、瓶颈定位、优化措施。",
                acceptance_criteria=[
                    "核心接口满足预期 QPS。",
                    "关键瓶颈可说明。",
                    "优化措施可回滚。",
                ],
                out_of_scope=[
                    "线上全链路压测",
                    "生产级容灾",
                    "多地域部署",
                ],
                technical_points=["压测", "瓶颈定位", "性能预算"],
                interview_points=["你如何决定先优化数据库还是先加缓存？"],
            )
        )
        self.tasks.append(
            Task(
                id=_next_task_id(phase.id, len([t for t in self.tasks if t.phase_id == phase.id])),
                phase_id=phase.id,
                title="可观测性与排障准备",
                goal="增加结构化日志、关键指标与排障路径。",
                why="面试常问“线上出问题怎么查”。",
                scope="Advanced",
                prerequisites=[self.tasks[-1].id],
                inputs=["Observability"],
                expected_output="日志规范、关键指标与最小排障流程。",
                implementation_scope="日志、指标、告警与故障手册。",
                acceptance_criteria=[
                    "关键流程有结构化日志。",
                    "核心指标可观测。",
                    "故障手册可指导复现。",
                ],
                out_of_scope=[
                    "全链路追踪",
                    "生产监控平台",
                    "自动化告警",
                ],
                technical_points=["结构化日志", "关键指标", "排障手册"],
                interview_points=["线上出现偶发异常时从哪开始排查？"],
            )
        )

    def _phase_by_scope(self, scope_level: str) -> Phase | None:
        for phase in self.phases:
            if phase.scope == scope_level:
                return phase
        return self.phases[0] if self.phases else None

    def _link_dependencies(self) -> None:
        for task in self.tasks:
            task.dependencies = [dep for dep in task.dependencies if any(t.id == dep for t in self.tasks)]

    def _validate(self) -> TaskGraphValidation:
        task_map = {t.id: t for t in self.tasks}
        cycles = _detect_cycles(task_map)
        ready = _ready_tasks(task_map)
        blocked = [t.id for t in self.tasks if t.status == TaskStatus.PENDING and t.id not in ready]
        order = _topological_sort(task_map)
        return TaskGraphValidation(
            valid=not cycles,
            cycle_detected=bool(cycles),
            cycle_path=cycles[:5],
            ready_tasks=sorted(ready),
            blocked_tasks=sorted(blocked),
            total_tasks=len(self.tasks),
            required_tasks=sum(1 for t in self.tasks if t.scope != "Advanced"),
            optional_tasks=sum(1 for t in self.tasks if t.scope == "Advanced"),
            topological_order=order,
        )


def _detect_cycles(task_map: dict[str, Task]) -> list[str]:
    visited: set[str] = set()
    path: list[str] = []

    def _dfs(node: str) -> bool:
        visited.add(node)
        path.append(node)
        for dep in task_map[node].dependencies:
            if dep not in task_map:
                continue
            if dep in path:
                idx = path.index(dep)
                return True
            if dep not in visited and _dfs(dep):
                return True
        path.pop()
        return False

    cycle: list[str] = []
    for node in task_map:
        if node not in visited:
            if _dfs(node):
                cycle = path[path.index(next(iter(set(path) & set([d for t in task_map.values() for d in t.dependencies])))):]
                break
    return cycle


def _ready_tasks(task_map: dict[str, Task]) -> list[str]:
    ready = []
    for task in task_map.values():
        if task.status not in {TaskStatus.PENDING, TaskStatus.BLOCKED}:
            continue
        if all(task_map[dep].status == TaskStatus.DONE for dep in task.dependencies if dep in task_map):
            ready.append(task.id)
    return ready


def _topological_sort(task_map: dict[str, Task]) -> list[str]:
    in_degree = {tid: 0 for tid in task_map}
    for task in task_map.values():
        for dep in task.dependencies:
            if dep in task_map:
                in_degree[task.id] = in_degree.get(task.id, 0) + 1

    queue = deque([tid for tid, degree in in_degree.items() if degree == 0])
    order = []
    while queue:
        node = queue.popleft()
        order.append(node)
        for task in task_map.values():
            if node in task.dependencies:
                in_degree[task.id] -= 1
                if in_degree[task.id] == 0:
                    queue.append(task.id)
    return order

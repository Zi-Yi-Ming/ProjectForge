from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterable

from app.agents.jd_analyzer import _ENGINEERING_TOPIC_MAP, _normalize_skill
from app.schemas.blueprint import ProjectBlueprint, ScopeLevel, UserProfile
from app.schemas.jd import JDProfile
from app.schemas.matching import ProjectFit
from app.schemas.research import ResearchOutput
from app.schemas.scoring import RepositoryScore


_DEFAULT_SCOPE_LEVELS = [
    ScopeLevel(
        level="L1_core",
        label="Core",
        description="最小业务闭环：核心模块可运行，关键技术真正落地。",
    ),
    ScopeLevel(
        level="L2_jd",
        label="JD Alignment",
        description="补齐 JD 明确要求的技能与工程问题。",
    ),
    ScopeLevel(
        level="L3_engineering",
        label="Engineering Depth",
        description="增加值得面试讨论的工程问题与设计决策。",
    ),
    ScopeLevel(
        level="L4_advanced",
        label="Advanced",
        description="性能、容灾、可观测性等增强能力，有时间再做。",
    ),
]


_BUSINESS_DOMAIN_TEMPLATES: dict[str, dict[str, str | list[str]]] = {
    "java": {
        "business_domain": "Enterprise Backend / SaaS",
        "project_type": "Reference-style backend service",
        "one_line": "基于真实开源项目参考，实现一个企业级后端服务，覆盖 JD 要求的核心工程能力。",
        "core_problem": "中小型业务系统需要稳定、可扩展的后端支撑，但常见 Demo 缺少真实工程问题。",
        "target_users": ["后端开发者", "求职者", "技术面试官"],
    },
    "python": {
        "business_domain": "AI Platform / Knowledge Service",
        "project_type": "Reference-style AI service",
        "one_line": "围绕真实 AI/知识库场景，实现可运行的服务，补齐 JD 要求的工程能力。",
        "core_problem": "AI 相关岗位需要真实 RAG/Agent 工程经验，而不是单纯调用 SDK。",
        "target_users": ["AI 后端开发者", "求职者", "技术面试官"],
    },
    "go": {
        "business_domain": "Cloud Native / Microservice",
        "project_type": "Reference-style microservice",
        "one_line": "基于云原生参考模式，实现一个具备真实工程深度的后端项目。",
        "core_problem": "云原生岗位需要理解服务拆分与工程规范，而不是简单 Demo。",
        "target_users": ["云原生开发者", "求职者", "技术面试官"],
    },
    "default": {
        "business_domain": "General Software",
        "project_type": "Reference-style software project",
        "one_line": "基于真实开源项目参考，实现一个可落地、可解释的工程项目。",
        "core_problem": "求职项目需要真实业务场景与工程深度，而不是纯教程 Demo。",
        "target_users": ["开发者", "求职者", "技术面试官"],
    },
}


_ENGINEERING_TOPIC_DESCRIPTIONS: dict[str, dict[str, str]] = {
    "REST API": {
        "problem": "接口设计不规范会导致前后端联调成本高、异常处理混乱。",
        "decision": "统一 REST 风格接口，明确状态码、错误格式与版本策略。",
        "tradeoff": "REST 更通用，但 GraphQL 在某些场景下可减少请求次数。",
        "interview_question": "为什么这里使用 REST API，而不是 RPC 或 GraphQL？",
    },
    "Unit Testing": {
        "problem": "缺乏单测会导致回归成本高，关键逻辑无法快速验证。",
        "decision": "核心服务层与工具类补充单测，优先覆盖边界与异常路径。",
        "tradeoff": "单测提高稳定性，但过度单测低价值代码会增加维护成本。",
        "interview_question": "你如何判断一个模块值得写单测？",
    },
    "Debugging": {
        "problem": "线上问题难以定位会延长故障恢复时间。",
        "decision": "增加结构化日志、关键埋点与最小可复现诊断流程。",
        "tradeoff": "更丰富的日志有助于排障，但会增加存储与噪音。",
        "interview_question": "线上出现偶发异常时，你会从哪开始排查？",
    },
    "Performance Optimization": {
        "problem": "未优化的查询或流程会在流量增长后成为瓶颈。",
        "decision": "识别热点路径，优先优化数据库查询与缓存策略。",
        "tradeoff": "过早优化会引入复杂度，但核心链路必须预留性能预算。",
        "interview_question": "你如何决定先优化数据库还是先加缓存？",
    },
    "High Concurrency": {
        "problem": "并发场景下容易出现超卖、锁冲突与资源耗尽。",
        "decision": "热点操作增加限流、幂等与异步解耦。",
        "tradeoff": "并发控制提高正确性，但会增加延迟与实现复杂度。",
        "interview_question": "如果请求量突增 10 倍，当前设计会先在哪里失败？",
    },
    "Distributed Systems": {
        "problem": "单机能力有限，跨服务调用带来一致性与可用性问题。",
        "decision": "按领域拆分服务，明确接口契约与故障边界。",
        "tradeoff": "微服务提高可扩展性，但会带来运维与一致性问题。",
        "interview_question": "为什么这里拆成两个服务，而不是放在同一个进程？",
    },
    "System Design": {
        "problem": "缺乏系统设计会导致后续扩展困难。",
        "decision": "先定义核心数据流、模块边界与扩展点。",
        "tradeoff": "过度设计浪费资源，设计不足会导致后期重构。",
        "interview_question": "如果业务规模翻 10 倍，你会先改哪一部分？",
    },
    "Code Review": {
        "problem": "缺少评审会放大潜在缺陷与不一致实现。",
        "decision": "关键逻辑必须经过 CR，重点检查边界、异常与可测试性。",
        "tradeoff": "CR 提高代码质量，但会增加交付时间。",
        "interview_question": "你做 Code Review 时最关注什么？",
    },
    "Documentation": {
        "problem": "缺少文档会导致交接困难与面试表达不清。",
        "decision": "README、接口文档与架构说明同步更新。",
        "tradeoff": "文档减少沟通成本，但维护成本高。",
        "interview_question": "你如何向新人解释这个项目的关键设计？",
    },
    "Redis": {
        "problem": "热点数据频繁读取会压垮数据库。",
        "decision": "对热点数据增加 Redis 缓存，并设计失效/降级策略。",
        "tradeoff": "缓存提高读取性能，但会增加一致性与故障复杂度。",
        "interview_question": "为什么这里使用 Redis，而不是直接查询数据库？",
    },
    "Database Design": {
        "problem": "糟糕的表结构会导致查询变慢、一致性难保证。",
        "decision": "按业务边界设计表结构，明确主键、索引与事务边界。",
        "tradeoff": "过度范式化影响查询性能，过度反范式化会影响一致性。",
        "interview_question": "这张表为什么这样设计主键与索引？",
    },
}


@dataclass(frozen=True)
class _BlueprintContext:
    jd: JDProfile
    research: ResearchOutput
    fit: ProjectFit
    score: RepositoryScore
    user: UserProfile
    scope_levels: list[ScopeLevel]


def _pick_language(ctx: _BlueprintContext) -> str:
    language = (ctx.research.github.language or "").strip()
    if language:
        return language
    for skill in ctx.jd.required_skills + ctx.jd.preferred_skills:
        normalized = _normalize_skill(skill)
        if normalized in {"Java", "Python", "Go", "JavaScript", "TypeScript"}:
            return normalized
    return "General"


def _business_template(ctx: _BlueprintContext, language: str) -> dict[str, Any]:
    return _BUSINESS_DOMAIN_TEMPLATES.get(language.lower(), _BUSINESS_DOMAIN_TEMPLATES["default"])


def _scope_by_user(ctx: _BlueprintContext) -> tuple[ScopeLevel, ScopeLevel, str]:
    weekly = ctx.user.weekly_hours or 10
    available_levels = ctx.scope_levels or list(_DEFAULT_SCOPE_LEVELS)
    if weekly <= 8:
        recommended = available_levels[0]
        rationale = "用户每周可用时间较少，优先保证最小业务闭环。"
    elif weekly <= 15:
        recommended = available_levels[1] if len(available_levels) > 1 else available_levels[0]
        rationale = "时间有限，建议补齐 JD 核心能力，暂缓高级工程问题。"
    else:
        recommended = available_levels[2] if len(available_levels) > 2 else available_levels[-1]
        rationale = "时间充足，可进入工程深度与面试表达层。"
    selected = recommended
    return recommended, selected, rationale


def _jd_mappings(ctx: _BlueprintContext) -> tuple[dict[str, str], dict[str, str], str]:
    jd_skill_mapping: dict[str, str] = {}
    for skill in ctx.fit.matched_required_skills:
        jd_skill_mapping[skill] = f"在参考项目中存在 {skill} 相关事实，建议在新项目中保留该能力并给出可验证实现。"
    for skill in ctx.fit.missing_required_skills:
        jd_skill_mapping[skill] = "当前参考项目未发现明确证据，建议作为新项目必须补齐的核心能力。"
    for skill in ctx.fit.matched_preferred_skills:
        jd_skill_mapping[skill] = "属于加分项，建议在实现中增加可展示的扩展能力。"
    for skill in ctx.fit.missing_preferred_skills:
        jd_skill_mapping[skill] = "当前参考项目未发现明确证据，可作为时间充足时的可选增强。"

    engineering_topic_mapping: dict[str, str] = {}
    for topic in ctx.fit.matched_engineering_topics:
        engineering_topic_mapping[topic] = "参考项目已有相关工程线索，建议保留并在新项目中解释设计选择。"
    for topic in ctx.fit.missing_engineering_topics:
        engineering_topic_mapping[topic] = "参考项目未明确体现，建议根据真实业务需要新增工程方案。"

    summary = (
        f"参考项目与 JD 的 required skill 覆盖率为 {ctx.fit.required_skill_coverage}%，"
        f"engineering topic 覆盖率为 {ctx.fit.engineering_topic_coverage}%，"
        f"preferred skill 覆盖率为 {ctx.fit.preferred_skill_coverage}%，"
        f"项目质量分为 {ctx.fit.project_quality_score}，"
        f"最终匹配得分为 {ctx.fit.score}。"
    )
    return jd_skill_mapping, engineering_topic_mapping, summary


def _engineering_entries(ctx: _BlueprintContext) -> tuple[list[str], list[str], list[str], list[str]]:
    problems: list[str] = []
    solutions: list[str] = []
    decisions: list[str] = []
    tradeoffs: list[str] = []

    for topic in ctx.jd.engineering_topics:
        if topic in _ENGINEERING_TOPIC_DESCRIPTIONS:
            desc = _ENGINEERING_TOPIC_DESCRIPTIONS[topic]
            problems.append(desc["problem"])
            solutions.append(desc["decision"])
            decisions.append(desc["decision"])
            tradeoffs.append(desc["tradeoff"])

    if not problems:
        problems.append("项目需要明确的业务边界、异常处理与可观测性设计。")
        solutions.append("定义核心流程、失败恢复路径与日志规范。")
        decisions.append("优先保证最小可运行闭环，再逐步增强工程深度。")
        tradeoffs.append("早期简化实现会降低可扩展性，但可更快形成可讨论的面试素材。")

    return problems, solutions, decisions, tradeoffs


def _interview_entries(ctx: _BlueprintContext) -> tuple[list[str], list[str], list[str]]:
    topics: list[str] = []
    questions: list[str] = []
    expected: list[str] = []

    core_topics = [
        "业务场景与核心流程",
        "技术选型与替换方案",
        "关键模块职责",
        "异常与失败恢复",
        "数据一致性与幂等",
        "可观测性与排障",
    ]
    advanced_topics = [
        "高并发与性能预算",
        "消息堆积与重试策略",
        "缓存失效与击穿",
        "故障演练与容灾",
    ]

    for topic in ctx.jd.engineering_topics:
        if topic in _ENGINEERING_TOPIC_DESCRIPTIONS:
            desc = _ENGINEERING_TOPIC_DESCRIPTIONS[topic]
            topics.append(topic)
            questions.append(desc["interview_question"])
            expected.append(desc["decision"])

    for skill in ctx.jd.required_skills:
        normalized = _normalize_skill(skill)
        if normalized in _ENGINEERING_TOPIC_DESCRIPTIONS and normalized not in topics:
            desc = _ENGINEERING_TOPIC_DESCRIPTIONS[normalized]
            topics.append(normalized)
            questions.append(desc["interview_question"])
            expected.append(desc["decision"])

    if "High Concurrency" in ctx.jd.engineering_topics or "Distributed Systems" in ctx.jd.engineering_topics:
        topics.append("并发与一致性")
        questions.append("如果并发量上升，当前设计会先在哪里出问题？")
        expected.append("识别热点资源、锁范围与异步边界。")

    if not questions:
        questions.append("为什么选择这个业务场景？")
        expected.append("能清晰说明业务问题与技术方案的对应关系。")

    return topics, questions, expected


class BlueprintAgent:
    def __init__(self) -> None:
        self.scope_levels = list(_DEFAULT_SCOPE_LEVELS)

    def build(
        self,
        jd: JDProfile,
        research: ResearchOutput,
        fit: ProjectFit,
        score: RepositoryScore,
        user: UserProfile,
    ) -> ProjectBlueprint:
        ctx = _BlueprintContext(
            jd=jd,
            research=research,
            fit=fit,
            score=score,
            user=user,
            scope_levels=self.scope_levels,
        )
        language = _pick_language(ctx)
        template = _business_template(ctx, language)
        recommended_scope, selected_scope, scope_rationale = _scope_by_user(ctx)
        jd_skill_mapping, engineering_topic_mapping, fit_summary = _jd_mappings(ctx)
        problems, solutions, decisions, tradeoffs = _engineering_entries(ctx)
        interview_topics, likely_questions, expected_understanding = _interview_entries(ctx)

        reference_points = [
            point
            for point in ctx.fit.matched_required_skills[:3]
            if point in {ctx.research.github.language, *ctx.research.github.topics, *ctx.research.key_points, *ctx.research.technical_details}
        ]
        if not reference_points:
            reference_points = ctx.fit.matched_required_skills[:3] or ["项目整体结构"]

        return ProjectBlueprint(
            name=user.target_role or jd.role or "Project Blueprint",
            one_line_description=template["one_line"],
            business_domain=template["business_domain"],
            project_type=template["project_type"],
            source_repo=ctx.research.topic or ctx.fit.repo or "",
            source_mode="reference",
            reference_points=reference_points,
            business_scenario=template["core_problem"],
            target_users=template["target_users"],
            core_problem=template["core_problem"],
            core_features=self._core_features(ctx),
            architecture_style="modular backend",
            services=self._services(ctx),
            major_modules=self._modules(ctx),
            data_flow=self._data_flow(ctx),
            core_workflows=self._workflows(ctx),
            technology_stack=self._tech_stack(ctx),
            infrastructure=self._infrastructure(ctx),
            engineering_problems=problems,
            engineering_solutions=solutions,
            design_decisions=decisions,
            tradeoffs=tradeoffs,
            jd_skill_mapping=jd_skill_mapping,
            engineering_topic_mapping=engineering_topic_mapping,
            project_fit_summary=fit_summary,
            credibility_risks=[
                "不要声称项目已经支撑百万级并发，除非有压测证据。",
                "不要直接复制开源项目代码并声称原创。",
                "不要夸大尚未实现的架构复杂度。",
            ],
            claims_to_avoid=[
                "不要写‘独立设计并实现分布式事务’除非确实实现。",
                "不要写‘千万级消息处理’除非有真实消息链路。",
                "不要写‘从零设计微服务架构’如果实际只有一个服务。",
            ],
            interview_depth_points=self._depth_points(ctx),
            interview_topics=interview_topics,
            likely_questions=likely_questions,
            expected_understanding=expected_understanding,
            recommended_scope=recommended_scope,
            selected_scope=selected_scope,
            scope_rationale=scope_rationale,
            scope_levels=list(self.scope_levels),
        )

    def _core_features(self, ctx: _BlueprintContext) -> list[str]:
        features = []
        if "Java" in ctx.jd.required_skills or "Java" in ctx.research.github.language:
            features.append("核心业务服务：接收请求、校验参数、调用下游。")
        if "Spring Boot" in ctx.jd.required_skills or "spring boot" in ctx.research.summary.lower():
            features.append("Web 层：统一入口、路由、异常映射与接口文档。")
        if "MySQL" in ctx.jd.required_skills or "mysql" in ctx.research.summary.lower():
            features.append("数据层：核心表设计、基础查询与事务边界。")
        if "Redis" in ctx.jd.required_skills:
            features.append("缓存层：热点数据读写与失效策略。")
        if any(skill in ctx.jd.required_skills for skill in {"Kafka", "RabbitMQ"}):
            features.append("异步层：事件发布/消费与失败重试。")
        if not features:
            features = [
                "核心业务服务：接收请求、校验参数、调用下游。",
                "数据层：核心表设计与基础查询。",
                "接口层：REST API 与基础错误处理。",
            ]
        return features

    def _services(self, ctx: _BlueprintContext) -> list[str]:
        services = ["API Gateway / Controller", "Core Service"]
        if "Kafka" in ctx.jd.required_skills or "RabbitMQ" in ctx.jd.required_skills:
            services.append("Async Worker / Consumer")
        if "Redis" in ctx.jd.required_skills:
            services.append("Cache Layer")
        return services

    def _modules(self, ctx: _BlueprintContext) -> list[str]:
        modules = ["domain", "service", "repository"]
        if "Redis" in ctx.jd.required_skills:
            modules.append("cache")
        if any(skill in ctx.jd.required_skills for skill in {"Kafka", "RabbitMQ"}):
            modules.append("messaging")
        return modules

    def _data_flow(self, ctx: _BlueprintContext) -> str:
        return "Client -> API Layer -> Service Layer -> Repository/External -> Response"

    def _workflows(self, ctx: _BlueprintContext) -> list[str]:
        workflows = ["Normal request/response flow"]
        if "Redis" in ctx.jd.required_skills:
            workflows.append("Cache-aside read flow")
        if any(skill in ctx.jd.required_skills for skill in {"Kafka", "RabbitMQ"}):
            workflows.append("Async event processing flow")
        if "REST API" in ctx.jd.engineering_topics:
            workflows.append("Error handling and validation flow")
        return workflows

    def _tech_stack(self, ctx: _BlueprintContext) -> list[str]:
        stack = []
        for skill in ctx.jd.required_skills:
            normalized = _normalize_skill(skill)
            stack.append(normalized)
        if not stack:
            stack = ["Java", "Spring Boot", "MySQL"]
        return stack

    def _infrastructure(self, ctx: _BlueprintContext) -> list[str]:
        infra = ["Local / Docker Compose"]
        if "Docker" in ctx.jd.required_skills or "Docker" in ctx.jd.preferred_skills:
            infra.append("Docker")
        if "Kubernetes" in ctx.jd.required_skills or "K8s" in ctx.jd.preferred_skills:
            infra.append("Kubernetes")
        return infra

    def _depth_points(self, ctx: _BlueprintContext) -> list[str]:
        points = [
            "核心业务场景与真实问题边界。",
            "关键模块的职责划分与调用关系。",
            "至少一个核心技术点的设计理由。",
        ]
        if ctx.fit.matched_engineering_topics:
            points.append(f"围绕 {', '.join(ctx.fit.matched_engineering_topics[:2])} 做深度解释。")
        return points

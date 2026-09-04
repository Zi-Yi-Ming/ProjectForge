# ProjectForge

> 基于岗位 JD 的工程项目教练与约束式执行引擎

ProjectForge 将一份岗位 JD 转化为结构化、可验证的工程项目路径：分析能力画像、计算项目匹配度、生成项目蓝图与任务依赖图，并在约束下推进执行与重新规划。它的目标不是生成“能跑就行”的代码，而是帮你从岗位要求出发，得到一条可以向面试官展示的、经过计划与验证的真实项目路径。

## 它能解决什么问题

- 看到 JD 后不知道应该做一个什么样的项目才能精准命中岗位要求
- 自己从零设计项目容易 scope 失控，要么太简单无法体现深度，要么过于宏大无法完成
- 即使有了项目 idea，也不知道如何拆解成可执行、可验证的学习任务
- 让 AI 直接写代码容易失控：代码可能跑偏、超出 scope、或缺少工程约束
- 无法判断生成的代码是否真的满足 JD 要求，也缺少独立验证机制

## 与通用 AI 编程助手的差异

- 起点是真实 JD，不是凭空想需求
- 项目设计来自能力匹配与工程约束，不是拍脑袋
- 任务拆解、执行、验证、重新规划全部受工程控制面约束
- 用户可以审查、确认、调整，不是黑箱

## 核心流程

```text
岗位 JD
  ↓
JD 能力画像
  ↓
项目匹配度
  ↓
项目蓝图
  ↓
任务依赖图
  ↓
约束式执行
  ↓
验证 / 重新规划
```

## 核心概念

### JD 能力画像（JD Profile）

从岗位描述中提取结构化能力要求，包括技术栈、工程经验、软技能等，作为后续匹配与规划的输入。

### 项目匹配度（Project Fit）

将 JD 能力画像与项目研究结果对照，输出匹配强度、能力缺口、建议的工程方向。

### 项目蓝图（Project Blueprint）

定义项目的工程架构、核心模块、技术选型、交付边界和面试表达点，是任务拆解的上游依据。

### 任务依赖图（Task Graph）

将蓝图拆成有依赖关系、可执行、可验证的任务序列，明确每个任务的输入、输出、验收标准和工程边界。

### 约束式执行（Constrained Execution）

在 Task Contract 约束内执行任务，限制允许修改的文件、测试范围和工程边界，避免执行过程偏离目标。

### 验证（Validation）

独立验证任务产出，包括测试执行、scope 检查、验收标准核对，只有验证通过才能标记任务完成。

### 重新规划（Replan）

当任务失败或受阻时，生成失败分析、影响范围和重做建议，用户明确批准后才应用，不自动修改蓝图或已完成任务。

## 项目生命周期

```text
CREATED
  ↓
ANALYZING
  ↓
PLANNING
  ↓
READY
  ↓
EXECUTING
  ↓
COMPLETED / FAILED / BLOCKED
```

## 快速开始

### 环境要求

- Python 3.10+
- 已安装 Hermes CLI 并可在终端执行 `hermes`
- 可选：StepFun API key、GitHub token

### 安装

```bash
git clone https://github.com/Zi-Yi-Ming/ProjectForge.git
cd ProjectForge
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
```

### CLI 入口

```bash
python -m app.cli --help
```

### 常用命令

```bash
# 创建项目
python -m app.cli create <项目名称>

# 查看项目
python -m app.cli show <project_id>

# 推进项目生命周期
python -m app.cli transition <project_id> <目标状态>

# 查看项目事件
python -m app.cli events <project_id>

# 重新规划
python -m app.cli replan create <project_id> <run_id>
python -m app.cli replan show <project_id> <proposal_id>
python -m app.cli replan approve <project_id> <proposal_id>
python -m app.cli replan reject <project_id> <proposal_id>
python -m app.cli replan apply <project_id> <proposal_id>

# 执行运行
python -m app.cli run start <project_id>
python -m app.cli run show <project_id> <run_id>
python -m app.cli run cancel <project_id> <run_id>
python -m app.cli run resume <project_id>
```

> 注意：部分命令仍处于 scaffold 阶段，请结合实际代码行为使用，不要仅凭 README 推断完整执行能力。

## 示例

### 输入 JD

```
Java 后端开发实习生

岗位要求：
- Java
- Spring Boot
- MySQL

加分项：
- Redis
- 单元测试
```

### 项目匹配度

匹配较强：
- Java
- Spring Boot
- MySQL

能力缺口：
- Redis
- 单元测试

### 项目蓝图

1. 基础工程
2. 核心业务
3. 工程深度
4. 进阶能力

### 任务依赖图

- T01 项目初始化
- T02 数据模型设计
- T03 核心 REST API
- T04 Redis 缓存
- T05 单元测试

> 以上为概念示例。实际输出取决于 JD 输入、研究结果和用户选择的 Scope。

## 架构

```text
                    Job Description
                           │
                           ▼
                     ┌───────────┐
                     │ JDAnalyzer │
                     └─────┬─────┘
                           │
                           ▼
                     ┌────────────┐
                     │ProjectMatch│
                     └─────┬──────┘
                           │
                           ▼
                   ┌─────────────────┐
                   │ Project Blueprint│
                   └────────┬────────┘
                            │
                            ▼
                      ┌───────────┐
                      │ TaskEngine │
                      └─────┬─────┘
                            │
                            ▼
                       Task Graph
                            │
                            ▼
                    Constrained Run
                            │
                  ┌─────────┴─────────┐
                  ▼                   ▼
             Validation            Replan
```

## 开发

```bash
# 运行测试
pytest

# 仅运行 Product Core 相关测试
pytest tests/test_project_core.py tests/test_workflow.py tests/test_run_control.py
```

## 配置

环境变量通过 `.env` 加载，参见 `.env.example`。

| 环境变量 | 用途 |
| --- | --- |
| `STEPFUN_API_KEY` | StepFun API key |
| `GITHUB_TOKEN` | GitHub token |
| `STEPFUN_BASE_URL` | StepFun API 地址 |
| `LOG_LEVEL` | 日志级别 |

## 项目状态

- Product Core：已实现
- CLI：已实现基础入口，部分命令仍在完善
- API：已实现基础接口
- Hermes 集成：已接入真实 Hermes CLI
- Web UI：未实现
- 多用户 / 云执行：未实现

## License

MIT

# 求职匹配 Agent 系统技术设计文档

## 1. 文档目标

本文档定义一个以 **FastAPI + PostgreSQL + SQLAlchemy ORM + Alembic + uv** 为基础的垂直领域 Agent 系统技术方案。

系统目标不是构建一个泛化聊天 Agent 平台，而是构建一个围绕 **简历解析、候选人画像、岗位匹配、匹配解释、定向简历优化** 的可落地系统。

本文档重点回答以下问题：

1. 系统边界是什么
2. Agent 在系统中的职责是什么
3. 业务闭环与 Agent 编排如何统一
4. 数据模型如何设计
5. 项目工程结构如何组织
6. 配置、迁移、测试、观测如何落地
7. 第一阶段应优先实现哪些能力

---

## 2. 设计原则

### 2.1 核心原则

1. **先跑通 Agent 编排下的最小业务闭环**

   * 不先做泛化 Agent 平台
   * 不先做复杂去中心化
   * 不先做大量与当前业务无关的抽象层

2. **流程先于能力点**

   * Agent 不应直接自由发挥
   * 系统应以受控阶段推进任务
   * 各 specialist 只负责阶段内能力，不负责全局主导

3. **证据优先于推断**

   * 简历解析、匹配解释、优化建议都应可回溯到证据
   * 系统必须区分“原文事实”“结构化抽取”“模型推断”

4. **结构化优先于自由文本**

   * 内部状态、Agent 交接、任务产物都以结构化对象为主
   * 自由文本仅作为对用户输出层

5. **分层存储，不把向量库当主库**

   * 原始文档存储
   * 结构化关系存储
   * 检索索引
   * 向量索引

6. **先中心编排，后考虑网络去中心化**

   * 第一阶段采用单 Orchestrator + 多 Specialist
   * 不做点对点 Agent 网络
   * 不引入 ANP 级协议复杂度

### 2.2 非目标

第一阶段明确不做以下内容：

1. 面相、生辰八字进入岗位推荐主决策链
2. 真正的去中心化 Agent 网络
3. 跨组织 Agent 协议互联
4. 自动投递简历
5. 自动代替用户做高风险职业决策
6. 全网无限制招聘数据爬取平台
7. 极复杂的自适应权重学习系统

---

## 3. 产品范围

## 3.1 业务主链路

系统最小业务闭环定义如下：

1. 用户上传简历（PDF / DOCX）
2. 系统解析文档并抽取结构化信息
3. 系统构建候选人画像
4. 系统从岗位知识库召回并排序岗位
5. 系统输出岗位匹配解释与差距分析
6. 用户选择目标岗位
7. 系统生成针对该岗位的简历优化建议与优化稿
8. 系统执行审核与风险校验

## 3.2 Agent 主链路

系统执行主链路定义如下：

1. Orchestrator 接单并创建任务
2. ResumeParseAgent 解析文档并生成区块
3. CandidateProfileAgent 构建候选人画像
4. JobRetrievalMatchAgent 执行过滤、召回、重排
5. ResumeOptimizeAgent 生成通用或定向优化结果
6. ReviewGuardAgent 审核最终输出是否合法、可信、可交付
7. Orchestrator 汇总结果并对外输出

**结论：**

* 业务主链路回答“系统为用户创造什么价值”
* Agent 主链路回答“系统如何组织能力完成价值交付”
* 二者不是替代关系，而是上下层关系

---

## 4. 总体架构

## 4.1 架构总览

建议采用以下分层：

1. **接入层**

   * FastAPI API
   * 文件上传
   * 请求校验
   * 鉴权与限流

2. **编排层**

   * Orchestrator
   * 任务状态机
   * Agent 调度
   * 结果聚合

3. **Agent 能力层**

   * ResumeParseAgent
   * CandidateProfileAgent
   * JobRetrievalMatchAgent
   * ResumeOptimizeAgent
   * ReviewGuardAgent

4. **领域服务层**

   * 简历解析服务
   * 候选人画像服务
   * 岗位检索与评分服务
   * 简历优化服务
   * 审核服务

5. **数据访问层**

   * SQLAlchemy ORM
   * Repository / Gateway
   * PostgreSQL
   * 向量索引访问

6. **基础设施层**

   * 文件存储
   * OCR / 文档转换
   * Embedding / LLM 调用
   * 事件日志
   * 中间件
   * 观测与追踪

## 4.2 架构特征

1. 单主控编排
2. Specialist 边界明确
3. 结构化任务与结构化产物
4. 文件与数据库双轨存储
5. API 层与内部领域模型分离
6. 配置全部从环境变量注入

---

## 5. 技术选型

## 5.1 核心技术栈

* **语言**：Python 3.12+
* **包管理**：uv
* **Web 框架**：FastAPI
* **ORM**：SQLAlchemy 2.x ORM
* **数据库迁移**：Alembic
* **数据库**：PostgreSQL
* **外部接口模型**：Pydantic v2
* **内部模型**：dataclass
* **配置**：pydantic-settings / env 驱动
* **异步支持**：asyncio
* **任务调度**：第一阶段使用应用内任务编排；后续可扩展到 Celery / Arq / Dramatiq
* **测试**：pytest
* **类型检查**：mypy
* **格式化 / Lint**：ruff

## 5.2 选型原因

### FastAPI

用于构建清晰、类型友好的 API 层，适合文件上传、任务查询、结果输出。

### SQLAlchemy ORM

用于实体映射、Repository 实现、事务控制、复杂查询。

### PostgreSQL

用于结构化持久化，适合任务、事件、候选人画像、岗位结构化信息存储。

### Alembic

用于数据库版本管理和演进。

### uv

用于项目依赖与虚拟环境管理，提升开发与 CI 效率。

### Pydantic + dataclass 双模型策略

* 对外 API：Pydantic
* 内部服务 / Agent 中间对象：dataclass

该策略符合以下设计要求：

* 外部接口结构清晰
* 内部对象轻量
* 领域层不被 API 层强耦合

---

## 6. 配置设计

## 6.1 配置原则

所有模型配置、数据库配置、中间件配置、外部服务配置均从环境变量加载。

不在代码中硬编码：

* 模型名
* API Key
* 数据库连接串
* 中间件开关
* OCR/Embedding/LLM Provider
* 日志级别
* 限流阈值
* 文件大小上限

## 6.2 配置模块设计

建议创建统一配置入口：

* `app/config/settings.py`
* 使用 `pydantic-settings` 封装
* 按领域拆成子配置

建议配置分组：

### AppSettings

* app_name
* env
* debug
* log_level
* api_prefix

### DatabaseSettings

* postgres_dsn
* sqlalchemy_echo
* pool_size
* max_overflow

### ModelSettings

* llm_provider
* llm_model_name
* llm_temperature
* embedding_provider
* embedding_model_name
* rerank_model_name

### DocumentSettings

* max_upload_size_mb
* ocr_enabled
* resume_parse_timeout_sec
* temp_dir

### MatchingSettings

* top_k
* vector_recall_k
* keyword_recall_k
* score_weight_skill
* score_weight_experience
* score_weight_project
* score_weight_education
* score_weight_preference

### MiddlewareSettings

* cors_origins
* rate_limit_enabled
* request_id_enabled
* audit_log_enabled

### StorageSettings

* file_root_dir
* artifact_root_dir
* uploads_dir_name
* outputs_dir_name

### SecuritySettings

* auth_enabled
* jwt_secret
* jwt_algorithm
* admin_token

## 6.3 .env 示例

```env
APP_NAME=job-agent
APP_ENV=dev
APP_DEBUG=true
APP_LOG_LEVEL=INFO
API_PREFIX=/api/v1

POSTGRES_DSN=postgresql+psycopg://postgres:postgres@localhost:5432/job_agent
SQLALCHEMY_ECHO=false
DB_POOL_SIZE=10
DB_MAX_OVERFLOW=20

LLM_PROVIDER=openai
LLM_MODEL_NAME=gpt-4.1
LLM_TEMPERATURE=0.1
EMBEDDING_PROVIDER=openai
EMBEDDING_MODEL_NAME=text-embedding-3-large
RERANK_MODEL_NAME=gpt-4.1-mini

MAX_UPLOAD_SIZE_MB=20
OCR_ENABLED=true
RESUME_PARSE_TIMEOUT_SEC=60
FILE_ROOT_DIR=./data
ARTIFACT_ROOT_DIR=./data/tasks

TOP_K=20
VECTOR_RECALL_K=50
KEYWORD_RECALL_K=50
SCORE_WEIGHT_SKILL=0.35
SCORE_WEIGHT_EXPERIENCE=0.25
SCORE_WEIGHT_PROJECT=0.20
SCORE_WEIGHT_EDUCATION=0.10
SCORE_WEIGHT_PREFERENCE=0.10

CORS_ORIGINS=http://localhost:3000,http://localhost:5173
RATE_LIMIT_ENABLED=true
REQUEST_ID_ENABLED=true
AUDIT_LOG_ENABLED=true
```

---

## 7. 分层与模块设计

## 7.1 API 层

职责：

* 接收请求
* 参数校验
* 文件接收
* 返回结构化响应
* 不承载复杂业务逻辑

建议模块：

* `app/api/v1/resumes.py`
* `app/api/v1/match_tasks.py`
* `app/api/v1/optimization_tasks.py`
* `app/api/v1/jobs.py`
* `app/api/v1/health.py`

API 层只依赖：

* Pydantic Request/Response Model
* Application Service / Orchestrator Facade

## 7.2 编排层

### Orchestrator

职责：

* 创建任务
* 推进阶段
* 调度 specialist
* 写入事件日志
* 检查阶段输出是否满足下一步输入条件
* 收敛最终结果

阶段建议：

1. `intake`
2. `parse`
3. `profile`
4. `retrieve`
5. `rank`
6. `explain`
7. `optimize`
8. `review`
9. `deliver`

### 设计要求

* 每个阶段都有明确输入与输出
* 每个阶段都能重试
* 每个阶段都能审计
* 每个阶段都能写事件日志
* 每个阶段可由一个或多个 Specialist 完成

## 7.3 Agent 层

### ResumeParseAgent

职责：

* 文档标准化
* 文本抽取
* 页级分割
* 区块切分
* 基础字段抽取

输入：

* 简历文件路径

输出：

* ResumeBlock 列表
* 基础抽取结果
* 解析风险项

### CandidateProfileAgent

职责：

* 技能标准化
* 经历聚合
* 项目结构化
* 求职方向归纳
* 生成候选人画像

输入：

* ResumeBlock 列表
* 原始抽取字段

输出：

* CandidateProfile
* Skill 列表
* Experience 列表
* Project 列表
* 风险项

### JobRetrievalMatchAgent

职责：

* 执行硬条件过滤
* 执行关键词 + 向量召回
* 执行重排与分项评分
* 输出 Top N 匹配岗位

输入：

* CandidateProfile
* 用户偏好
* 目标公司/岗位限制

输出：

* MatchResult 列表
* GapAnalysis 列表
* Explanation 列表

### ResumeOptimizeAgent

职责：

* 生成通用优化建议
* 针对目标岗位生成定向优化建议
* 生成优化版简历内容

输入：

* 原始简历结构化内容
* Target Job
* Match Gap

输出：

* 优化建议
* 优化版 Markdown / 富文本结构
* 风险说明

### ReviewGuardAgent

职责：

* 检查优化内容是否脱离证据
* 检查推荐解释是否自洽
* 检查高风险字段是否误入主决策链
* 检查结果能否对外宣称完成

输入：

* MatchResult
* OptimizationResult
* Source Evidence

输出：

* ReviewReport
* 风险等级
* 是否允许交付

## 7.4 领域服务层

建议按服务拆分，不让 Agent 直接操作 ORM。

服务示例：

* ResumeParsingService
* CandidateProfileService
* JobRetrievalService
* MatchScoringService
* ResumeOptimizationService
* ReviewGuardService
* ArtifactService
* EventLogService

---

## 8. 数据模型设计

## 8.1 建模原则

1. 原始数据与结构化结果分开存储
2. 事实与推断分开存储
3. 任务与结果分开存储
4. 事件日志独立存储
5. 文件产物和数据库状态双记录

## 8.2 核心表

### candidate

候选人主实体

字段建议：

* id
* user_id
* name
* email
* phone
* target_city
* target_salary_min
* target_salary_max
* created_at
* updated_at

### candidate_resume

简历文件与版本

字段建议：

* id
* candidate_id
* file_name
* file_type
* file_path
* parsed_status
* version
* created_at

### candidate_resume_block

简历区块

字段建议：

* id
* resume_id
* page_no
* block_type
* block_index
* raw_text
* normalized_text
* bbox_json
* confidence
* created_at

### candidate_profile

标准画像

字段建议：

* id
* candidate_id
* resume_id
* profile_json
* confidence_json
* created_at
* updated_at

### candidate_skill

标准化技能

字段建议：

* id
* candidate_id
* skill_name_raw
* skill_name_norm
* skill_category
* evidence_text
* evidence_block_id
* confidence

### candidate_experience

工作经历

字段建议：

* id
* candidate_id
* company_name
* job_title
* industry_tag
* start_date
* end_date
* duration_months
* description
* evidence_block_id

### candidate_project

项目经历

字段建议：

* id
* candidate_id
* project_name
* role_name
* tech_stack_json
* domain_tags_json
* result_text
* evidence_block_id

### company

公司信息

字段建议：

* id
* name
* industry
* company_size
* company_stage
* location_city
* description
* source_type
* source_url
* updated_at

### job_posting

岗位信息

字段建议：

* id
* company_id
* job_title
* job_title_norm
* city
* salary_min
* salary_max
* experience_min_years
* experience_max_years
* education_requirement
* job_description_raw
* job_description_clean
* status
* published_at
* updated_at
* source_type
* source_url

### job_skill_requirement

岗位技能要求

字段建议：

* id
* job_posting_id
* skill_name_raw
* skill_name_norm
* is_required
* weight

### job_tag

岗位标签

字段建议：

* id
* job_posting_id
* tag_type
* tag_value
* weight

### data_source_record

数据来源记录

字段建议：

* id
* source_type
* source_url
* content_type
* trust_score
* freshness_score
* quality_score
* ingested_at

### match_task

匹配任务

字段建议：

* id
* candidate_id
* resume_id
* task_status
* stage
* target_company_id
* target_job_id
* input_json
* created_at
* updated_at

### job_match_result

岗位匹配结果

字段建议：

* id
* task_id
* job_posting_id
* overall_score
* skill_score
* experience_score
* project_score
* education_score
* preference_score
* explanation_json
* gap_json
* rank_no
* created_at

### resume_optimization_task

简历优化任务

字段建议：

* id
* candidate_id
* resume_id
* target_job_id
* mode
* status
* created_at

### resume_optimization_result

简历优化结果

字段建议：

* id
* optimization_task_id
* optimized_resume_markdown
* change_summary_json
* risk_note_json
* created_at

### agent_task

Agent 子任务

字段建议：

* id
* parent_task_id
* task_type
* agent_role
* status
* input_json
* output_json
* started_at
* ended_at

### event_log

事件日志

字段建议：

* id
* task_id
* event_type
* event_payload_json
* created_at

---

## 9. 文件与产物设计

## 9.1 任务工作区

每个任务都分配一个独立目录：

```text
{ARTIFACT_ROOT_DIR}/{task_id}/
  uploads/
  workspace/
  artifacts/
  outputs/
```

### uploads/

* 原始简历
* 用户上传的 JD
* 用户导入的目标公司资料

### workspace/

* 中间处理文件
* OCR 结果
* 预清洗文本

### artifacts/

* block 解析 JSON
* candidate profile JSON
* match result JSON
* review report JSON

### outputs/

* 最终交付给用户的文件
* 优化简历输出
* 报告类结果

## 9.2 文件设计原则

1. 数据库保存结构化状态
2. 文件系统保存中间产物与可审计结果
3. 输出产物可回放
4. 所有关键阶段都应留下 artifact

---

## 10. 检索与匹配设计

## 10.1 检索底座

岗位知识库不应只依赖向量库，建议四层结构：

1. 原始文档存储
2. PostgreSQL 结构化表
3. 关键词 / 条件检索
4. 向量召回索引

## 10.2 标签体系

建议标签分四类：

### 来源标签

* official_company_site
* job_platform
* user_uploaded
* community_content
* manual_input

### 内容标签

* jd
* company_profile
* interview_note
* salary_info
* culture_info
* tech_stack_info

### 时效标签

* fresh
* recent
* stale
* expired

### 质量标签

* structured
* semi_structured
* noisy
* duplicated

## 10.3 匹配流程

### 第一步：硬过滤

* 城市
* 经验年限
* 必须技能
* 学历要求
* 语言要求

### 第二步：召回

* 关键词召回
* 标签召回
* 向量召回

### 第三步：重排

* skill_score
* experience_score
* project_score
* education_score
* preference_score

### 第四步：解释

* 为什么推荐
* 差距在哪里
* 哪些内容缺失

## 10.4 评分原则

1. 不使用单一黑箱总分作为唯一结果
2. 总分由分项分聚合得到
3. 分项分必须可解释
4. 评分参数通过 env 控制基础权重
5. 后续阶段可将权重从 env 迁移到配置表

---

## 11. 简历优化设计

## 11.1 优化模式

### 通用优化

* 结构重组
* 模块排序优化
* 表达优化
* 关键词覆盖提示
* 冗余删除

### 定向优化

* 针对目标岗位强调技能
* 针对目标岗位重排项目经历
* 针对岗位缺口提供补强建议
* 输出针对性强的简历版本

## 11.2 约束规则

系统必须遵守：

1. 不得虚构经历
2. 不得虚构技能
3. 不得虚构项目结果
4. 不得把推测写成已证实事实
5. 所有优化建议都应尽量引用原简历证据

---

## 12. 中间件设计

## 12.1 FastAPI 中间件建议

### RequestIdMiddleware

* 为每个请求注入 request_id
* 用于日志追踪

### LoggingMiddleware

* 记录请求时间、路径、状态码、耗时

### ErrorHandlingMiddleware

* 统一异常封装
* 屏蔽内部堆栈到外部 API

### RateLimitMiddleware

* 用于限制滥用
* 第一阶段可选接入 slowapi 或自定义实现

### CORSMiddleware

* 控制前端跨域访问

### AuditMiddleware

* 记录关键操作：上传、匹配、优化、删除、配置变更

## 12.2 Agent / 应用侧中间件建议

### EventPublishMiddleware

* 在关键阶段自动写 event_log

### StageGuardMiddleware

* 校验阶段输入输出完整性

### TimeoutGuardMiddleware

* 控制大模型、OCR、检索等长耗时步骤

### ReviewGuardMiddleware

* 在交付前统一运行风险检查

### RetryMiddleware

* 用于可恢复错误的有限重试

---

## 13. API 模型与内部模型规范

## 13.1 模型规范

### 外部接口

使用 Pydantic Model：

* UploadResumeRequest
* CreateMatchTaskRequest
* MatchTaskResponse
* JobMatchResultResponse
* ResumeOptimizationResponse

### 内部领域对象

使用 dataclass：

* ResumeBlock
* CandidateProfile
* MatchScoreCard
* GapAnalysis
* OptimizationDraft
* ReviewReport

## 13.2 接口设计原则

1. API 层不直接暴露 ORM 实体
2. API 层不直接复用内部 dataclass
3. Pydantic 用于边界校验
4. dataclass 用于领域流转

---

## 14. 工程规范与代码结构

## 14.1 代码风格约束

建议遵循以下规则：

1. 静态类型检查必须开启
2. 内部对象使用 `@dataclass`
3. 外部接口使用 Pydantic Model
4. 接口协议使用 `Protocol`
5. 除入口外逻辑尽量封装为 class
6. 属性默认私有，通过方法暴露
7. 每个模块必须有对应测试
8. 每个函数入口要有参数合法性检查

## 14.2 建议目录结构

```text
app/
  api/
    v1/
      resumes.py
      match_tasks.py
      optimization_tasks.py
      jobs.py
      health.py
  core/
    config/
      settings.py
    db/
      base.py
      session.py
      models/
      repositories/
    middleware/
      request_id.py
      logging.py
      error_handler.py
      audit.py
    llm/
      client.py
      protocols.py
    vector/
      client.py
  domain/
    models/
      resume.py
      candidate.py
      matching.py
      optimization.py
      review.py
    services/
      resume_parsing_service.py
      candidate_profile_service.py
      job_retrieval_service.py
      match_scoring_service.py
      resume_optimization_service.py
      review_guard_service.py
    protocols/
      llm_protocol.py
      vector_store_protocol.py
      repository_protocol.py
  agents/
    orchestrator/
      orchestrator.py
      stage_machine.py
    specialists/
      resume_parse_agent.py
      candidate_profile_agent.py
      job_retrieval_match_agent.py
      resume_optimize_agent.py
      review_guard_agent.py
  application/
    commands/
    handlers/
    dto/
  infra/
    storage/
    ocr/
    document/
    events/
    telemetry/
  tests/
    unit/
    integration/
    e2e/
alembic/
pyproject.toml
.env
.env.example
```

---

## 15. 数据库迁移与 ORM 规范

## 15.1 Alembic 规范

1. 所有 schema 变更必须通过 Alembic
2. 禁止手工修改线上表结构
3. 每次迁移必须包含 upgrade/downgrade
4. 重要字段变更应配套数据迁移脚本

## 15.2 SQLAlchemy 规范

1. 使用 SQLAlchemy 2.x 风格
2. ORM Model 仅作为持久化模型
3. Repository 返回领域对象或 ORM Model 的边界需明确
4. 复杂查询放在 Repository 层，不放在 API 层
5. 避免在 Agent 层直接操作 Session

---

## 16. 测试策略

## 16.1 测试层次

### 单元测试

* ResumeParsingService
* CandidateProfileService
* MatchScoringService
* ReviewGuardService

### 集成测试

* Repository + PostgreSQL
* API + DB
* Agent 编排流程

### E2E 测试

* 上传简历 → 匹配 → 优化 → 审核 → 输出

## 16.2 必测场景

1. PDF / DOCX 解析成功与失败场景
2. 简历块抽取正确性
3. 候选人画像标准化
4. 岗位过滤与召回逻辑
5. 分项评分稳定性
6. 简历优化不胡编
7. 审核模块能拦截越界内容
8. 任务状态流转正确
9. event_log 正确记录

---

## 17. 观测与运维

## 17.1 日志

建议日志分层：

* API Access Log
* Application Log
* Agent Execution Log
* Audit Log

关键日志字段：

* request_id
* task_id
* agent_role
* stage
* event_type
* duration_ms
* error_code

## 17.2 健康检查

建议提供 `/health` 与 `/ready` 接口。

检查项：

* 数据库连接
* 文件目录可写
* LLM Provider 连通性
* 向量库连通性
* OCR 依赖是否可用

## 17.3 doctor 命令

建议提供一个应用级自检命令，例如：

```bash
uv run python -m app.tools.doctor
```

检查内容：

* env 是否完整
* Alembic 当前版本
* PostgreSQL 连接
* 文件目录
* 模型配置
* OCR 配置

---

## 18. 安全与合规

## 18.1 招聘相关风险约束

以下字段禁止进入主决策链：

* 面相
* 生辰八字
* 性别暗示
* 年龄暗示
* 籍贯暗示
* 民族、宗教等不适合作为推荐因子的内容

## 18.2 输出风险控制

系统必须在输出中区分：

* 来自简历原文的事实
* 系统抽取的结构化事实
* 系统基于事实生成的建议
* 系统无法确定的推断

---

## 19. 第一阶段开发计划

## 19.1 MVP 范围

第一阶段只实现：

1. 上传 PDF / DOCX 简历
2. 解析出 block 结构
3. 生成候选人画像
4. 从岗位库输出 Top 20
5. 给出每个岗位的匹配原因与差距
6. 用户选择一个岗位
7. 输出针对该岗位的简历优化建议与优化版
8. 运行 ReviewGuard 做最终审核

## 19.2 第一阶段必须具备的通用能力

这些属于“与业务弱耦合，但直接支撑闭环”的基础能力，应优先实现：

1. 任务状态机
2. AgentTask / EventLog
3. 统一 schema
4. 任务工作区
5. 证据回溯能力
6. 审核守卫

## 19.3 第一阶段暂缓事项

1. 去中心化协议
2. 大规模多 Agent 网络
3. 自适应在线学习
4. 自动投递流程
5. 全网多源复杂爬取平台
6. 高级长期记忆系统

---

## 20. 推荐实现顺序

### 阶段 A：骨架

* FastAPI 项目初始化
* settings / env
* SQLAlchemy / Alembic
* PostgreSQL 连接
* 基础日志与中间件

### 阶段 B：任务与状态

* match_task
* agent_task
* event_log
* stage machine
* Orchestrator 初版

### 阶段 C：解析与画像

* 文件上传
* ResumeParseAgent
* CandidateProfileAgent
* 结构化结果落库

### 阶段 D：岗位库与匹配

* 岗位数据入库
* 过滤、召回、重排
* MatchResult 输出

### 阶段 E：优化与审核

* ResumeOptimizeAgent
* ReviewGuardAgent
* 输出交付

### 阶段 F：测试与稳定性

* 单测
* 集成测试
* E2E
* doctor 命令

---

## 21. 总结

本系统不应从“做一个很炫的通用 Agent 平台”开始，而应从“构建一个 Agent 编排驱动的求职匹配闭环”开始。

第一阶段的正确目标不是：

* 多 Agent 数量多
* 去中心化程度高
* 规则体系无限复杂

而是：

1. 有明确业务闭环
2. 有明确 Agent 编排闭环
3. 有明确阶段与状态
4. 有结构化数据与事件记录
5. 有证据回溯
6. 有结果审核

只有在这六点成立后，后续扩展多 Agent、长期记忆、更复杂知识库策略，才有稳定基础。

---

## 22. 后续可扩展方向

在第一阶段闭环稳定后，可以逐步扩展：

1. 用户导入目标公司画像
2. 公司知识卡与岗位族谱
3. 更复杂的标签与权重策略
4. 多轮任务记忆
5. 更强的 Resume Rewrite 审核机制
6. 更丰富的 Explainability 报告
7. 独立向量索引服务
8. 后台异步任务队列
9. 跨工作流 agent 协作
10. 最后再评估协议化或去中心化互联

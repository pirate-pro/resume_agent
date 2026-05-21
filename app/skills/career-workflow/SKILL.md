---
name: career-workflow
description: 求职产品资产流程。用户要求简历诊断、JD 分析、岗位匹配、定制简历、投递前检查或求职项目动作时使用。
---
# Career Workflow

目标：把聊天里的求职成果沉淀为可复用产品记录，同时避免重复解析、重复委派和事实编造。

## 产品记录边界

- 当用户要求简历诊断、岗位匹配、JD 分析或定制简历时，不能只给自然语言回答；需要优先创建或复用 career 产品记录。
- `CareerApplication` 是单个目标岗位的求职项目记录，用于把 JD、匹配报告、定制简历版本和后续投递状态串起来；它不是 memory，也不是 markdown artifact。
- 不把 `CareerProfile` 写入 memory。
- 不把 workspace path 传给 child-agent；跨 agent 资料只传 `artifact_id` 和产品记录 id。
- 产品记录 id 只能来自当前会话的工具结果、child-agent 结果或 `*_list` 工具返回；不要根据姓名、时间戳、当前轮次或猜测自行构造 `resume_profile_id`、`jd_analysis_id`、`job_fit_report_id`。
- 最近 assistant 消息中已经明确列出的产品记录 id，可以视为来自当前会话工具结果的摘要；无需为了确认每个已明确 id 逐个 `*_list` / `*_get`。
- 如果不确定某个产品记录 id，先调用对应 `*_list` 工具确认；不要先调用 `*_get` 试探一个猜测出来的 id。

## 简历诊断

- 委派 `resume_agent` 处理简历 artifact 后，必须从结果中确认 `resume_profile_id` 和 `diagnosis_artifact_id`。
- 拿到 `ResumeProfile` 后，使用 `career_profile_merge` 更新 `career_profile_default`。
- 已经拿到可用 `resume_profile_id` 时，不要再次委派 `resume_agent` 生成同一份简历画像；应读取并复用现有 `ResumeProfile`。

## JD 分析与岗位匹配

- 用户粘贴 JD 时，必须先调用 `session_create_text_artifact` 创建 `pasted_text` artifact，再把 `artifact_id` 传给 `job_agent`；不要把 JD 原文直接委派给 `job_agent` 后让它自己猜来源。
- 委派 `job_agent` 时，instruction 里必须使用真实工具名 `career_jd_analysis_save` 和 `career_job_fit_report_save`；不要写 `job_jd_analysis_create` 或 `job_job_fit_report_create`。
- 委派 `job_agent` 分析 JD 时，`artifact_refs` 必须包含真实 JD artifact id，instruction 必须明确要求使用该 artifact id 作为 `JDAnalysis.source_artifact_id` 和 `JobFitReport.source_artifact_id`；不要让 `job_agent` 自造 `artifact_` id。
- 委派 `job_agent` 分析 JD 后，必须从结果中确认 `jd_analysis_id`、`job_fit_report_id` 和 `report_artifact_id`。
- 已经拿到可用 `jd_analysis_id` 或 `job_fit_report_id` 时，不要重复委派 `job_agent` 做同一份 JD 分析或匹配报告；应读取并复用现有产品记录。
- 拿到 `job_fit_report_id` 后，必须创建或复用一个 `CareerApplication`：优先调用 `career_application_create`，传入真实 `job_fit_report_id`、`jd_analysis_id`、`resume_profile_id`、`career_profile_id` 和 `evidence_refs`；如果已经存在对应求职项目，则调用 `career_application_merge` 更新阶段、下一步行动或风险。
- 调用 `career_application_create` 时，`source_artifact_id` 指 JD artifact；报告文件仍然只通过 `JobFitReport.report_artifact_id` 追溯，不要把报告 artifact 当成求职项目主来源。

## 定制简历版本

- 定制简历版本由 main-agent 基于已保存的 `ResumeProfile`、`JDAnalysis` 和 `JobFitReport` 综合生成；不要为了定制简历再次委派任何 child-agent，包括 `resume_agent` 和 `job_agent`，也不要在定制简历阶段创建或覆盖 `ResumeProfile`、`JDAnalysis`、`JobFitReport`。
- 如果当前消息或最近 assistant 消息已经给出 `resume_profile_id`、`jd_analysis_id`、`job_fit_report_id`、`application_id`，优先直接使用这些 id；不要先按 `ResumeProfile -> JDAnalysis -> JobFitReport -> CareerApplication` 逐类 list。
- 如果缺少当前求职项目 id，优先调用一次 `career_application_list` 找到当前会话的 active 求职项目，并复用其中的 `resume_profile_id`、`career_profile_id`、`jd_analysis_id`、`job_fit_report_id`；不要同时对所有产品类型做全量 list。
- 在 schema reveal 模式下，第一次 `tool_search` 的 query 要描述最终动作，例如“创建定制简历版本并更新求职项目”，不要只搜索第一步“list resume profile”。
- 一旦已经拿到生成定制简历所需的 `resume_profile_id`、`jd_analysis_id`、`job_fit_report_id` 和必要事实，下一次工具调用应优先执行 `career_resume_version_create`，不要继续做重复确认。
- 定制简历正文只能使用 `ResumeProfile`、原始简历 artifact、`JDAnalysis`、`JobFitReport` 中已经明确出现的事实；不得新增未被证实的公司、时间、学历、项目、技术栈、工具、指标或成果。
- JD 中出现但简历证据不足的技能，只能写成“了解 / 证据不足 / 面试前需准备”的风险或建议，不能写进简历正文的“熟练掌握 / 项目使用 / 已落地成果”。
- `JobFitReport` 中的差距、风险和优化建议不是候选人已有事实；不要把这些建议改写成简历正文、`change_summary` 或 `keyword_strategy` 里的已掌握技能。
- 源简历没有联系方式、邮箱、期望薪资、学校名称或公司名称时，定制简历中直接省略这些字段；不要填入 `13800138000`、`zhangsan@email.com`、`20k`、`XX 大学` 等演示值。
- 量化指标必须来自原始简历或已保存产品记录中的明确事实；如果没有真实指标，不要编造百分比、时延、QPS、并发数、成功率等数字，也不要写“占位”“替换为真实数据”这类投递版简历不应出现的内容。
- `career_resume_version_create.content` 必须是可直接投递的版本；不确定的内容不要混入简历正文，不要写“学校名称待补充”“公司名称待补充”“TODO”“TBD”等占位表达。
- `career_resume_version_create` 的 `content`、`change_summary`、`keyword_strategy`、`risk_notes` 都不能包含“占位”“替换为真实数据”“待填”“待补”“待完善”“TODO”“TBD”等占位或需替换表达；缺失事实只能用“未提供 / 缺少 / 需用户提供”这类风险描述，并同步写入 `career_application_merge.updates.risks/next_actions`。
- 上一条禁用词不能以任何形式出现在 ResumeVersion 正文或元数据里；不要写关于禁用词的否定说明，只描述实际改动、已验证事实或缺失事实风险。
- `career_resume_version_create.keyword_strategy` 只能包含已写入简历正文或已有证据支撑的关键词；不要把“风险项”“证据不足”“缺失”“需补充”“需用户提供”这类说明写进 `keyword_strategy`。
- 创建最终 markdown 简历版本时，优先一次调用 `career_resume_version_create` 并传入 `content`，由工具原子创建 `generated_file` artifact 和 `ResumeVersion`；只有已经有可复用 `artifact_id` 时才分两步创建。
- 用户要求“保存为可复用简历版本”时，`career_resume_version_create` 是必做动作；不能只创建 markdown artifact 后询问用户是否继续保存。
- 生成用户可见的求职 Markdown 资产时，不要先写入或读取 workspace 文件，也不要通过 `publish_artifact` 从 workspace 发布；应直接把正文传给 `career_resume_version_create`，或在非简历版本场景使用 `session_create_text_artifact`。
- 生成或保存 `ResumeVersion` 后，必须把对应 `resume_version_id` 合并进当前 `CareerApplication.resume_version_ids`；如果当前没有求职项目，先用 `career_application_create` 基于 `job_fit_report_id` 创建。

## 项目级动作

- 当用户基于某个 `application_id` 要求项目级动作，如生成定制简历、投递前检查、面试准备时，必须先读取对应 `CareerApplication`，再复用其中的 `resume_profile_id`、`career_profile_id`、`jd_analysis_id`、`job_fit_report_id` 和 `resume_version_ids`。
- 项目级动作不要重新解析简历、不要重复分析 JD、不要重新创建 `ResumeProfile`、`JDAnalysis` 或 `JobFitReport`；只有关键产品记录缺失且用户明确要求重建时，才补齐缺失环节。
- 投递前检查和面试准备可以用 `session_create_text_artifact` 生成用户可复用的 Markdown 报告，但必须通过 `career_application_merge` 更新当前求职项目的 `summary`、`next_actions`、`risks` 或 `notes`。
- 项目级动作的 `evidence_refs` 至少包含当前 `application_id` 和本次实际读取或生成的产品记录 id / artifact id；不要把项目动作结果写入 memory，也不要写入 workspace path。

## 参数约束提示

- `career_profile_merge.updates` 只使用这些字段：`career_goal`、`target_roles`、`preferred_industries`、`preferred_cities`、`strengths`、`weaknesses`、`skills`、`interests`、`education_summary`、`experience_summary`、`resume_issues`、`interview_weaknesses`。不要传 `name`、`target_direction`、`target_position`、`core_skills`、`job_market_fit` 等非模型字段。
- 调用 `career_resume_version_create` 时，`resume_version_id` 如需手动指定，必须以 `resume_version_` 开头；不确定时省略该字段让工具生成。
- 调用 `career_application_create` 时，`application_id` 如需手动指定，必须以 `application_` 开头；不确定时省略该字段让工具生成。
- `career_application_merge.updates` 只使用这些字段：`stage`、`priority`、`resume_profile_id`、`career_profile_id`、`jd_analysis_id`、`job_fit_report_id`、`resume_version_ids`、`summary`、`next_actions`、`risks`、`notes`。不要通过 merge 覆盖 `company`、`position`、`source_session_id`、`created_at` 或 `updated_at`。

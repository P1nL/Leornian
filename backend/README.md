# 模块化业务后端

API 与 Worker 共用 `leornian` 业务包，通过各自入口和 composition root 装配。已接本地身份、异步目标、原生 Tutor、动态路线/节点正文、概念题包作者/盲解/六审/发布、固定评测、来源摘录、复习和公开快照/SSE。完整交付边界见根 README。

## 当前链路

当前源码 readiness 要求 **0068**。0068 保存部分正文的精确处理范围；路线教材与学习记忆沿现有路线修订和业务记录保存。0066 保存显式制定计划状态、本人受保护的 Tavily 配置及有回执的搜索/提取请求；已诊断修复保留旧操作并标记退出当前尝试。0065 保存规划资料批次、历史阶段回复及来源链接顺序；0064 保存覆盖检查的实际完成时间。5180 新目标默认提交官方材料获取授权及自动主题范围；旧目标及原回执保持原授权。当前实现与数据库部署状态见根 README。

2026-11-08 主库再次备份后已应用 0059，API/Worker 使用新构建并重启，API readiness 200、Worker ping 成功。备份为 `.local/backups/leornian-before-navigation-0059-20261108.dump`。92 项定向后端回归通过；原接收中断的外部调用记录保留。

完整目标覆盖与公开 `MaterialCoverage.synopsis` 共用既有 4000 字符容量，schema、提示词和接受校验一致。正常 search tick 重验原权限、引用和模型绑定后，当前合法的完整未消费回执可恢复同一 Run，由 AgentLoop 原样接受而不新发送；非法结果沿 `Runs.repair` 追加同 Run 格式修复。原回执和合格部分保留，修复只带最终 JSON 及具体诊断，不传递 wire 或私有推理。摘要超限按实际长度判断进展；UNKNOWN 不重发，取消或权限失效不启动修复。该变更 14 个不同定向用例及四文件 Ruff 已通过，无新迁移；实际完整目标/33 refs 已形成 sufficient，规划与当前 active 请求状态见[根 README](../README.md#第四阶段浏览器与仓库模型联验2026-11-07)。

获准来源在原始响应和原文已保存后遇到存储错误，可沿原观察续行，复用同一响应而不重新获取；没有完整响应或已清理的原文不进入此续行。`html-main-text.v2` 优先唯一 main 内的唯一 article，避免页面控件、侧栏和贡献者头像污染正文；多篇 article 保留完整 main，正文中的图形/公式继续等待处理。旧 HTML 提取可经 `html-main.v2` 正常修复链派生新版本，原版本不改写。2026-11-08 已用真实 TypeScript Handbook 原文完成 rev1 partial → rev2 parsed 与词法索引，原整份任务等待 Embedding，浏览器回读原来源版本与等待配置状态；15 项不同定向用例和五文件 Ruff 通过，详细回执见根 README。

材料增量接口（0050）：`POST /v1/material-change-checks` 用幂等键、精确 `binding_id/expected_binding_revision`、`document_id/candidate_revision` 比较当前绑定与后续版本；`GET /v1/material-change-checks/{id}` 读取同一报告并复核当前权限。返回完整块变化、未变映射、实际引用/章节上下文影响和精确范围搬移。正文变化保持 `uncertain/change_review_required`，报告不切换绑定。向量构建只复用同文档、同空间、当前获准的精确输入；检索不重复返回同一版本的相同范围。0050 先在所属 5459 测试库验证，2026-11-07 已按明确授权应用到原主库；该次源码当时要求 0050。

2026-11-08 主 API 8088、Worker、relay 和原 PostgreSQL/Redis 已恢复；`/health/ready` 返回 200，产品网页使用 5180 connected 基准宿主。relay 的环境过期调用已对齐原单数据库构造合同，新增单周期回归与 Ruff 通过，修复后的实际协调进程未再报错。旧学习/调用/执行事实保留，主库尚无用户模型连接，教学前需配置本人连接和职责 Profile。备份和验证见 [根 README](../README.md#主库-0058-与基准前端同步2026-11-08)。

1. `POST /v1/local-sessions` 创建本地开发身份及会话；数据库只保存令牌摘要。`POST /v1/local-sessions/refresh` 仅将当前有效、未撤销且身份启用的 Bearer 会话续期七天，不缩短已有更长期限，也不更换令牌。`DELETE /v1/local-sessions/current` 幂等撤销当前令牌。过期会话不能续期；明确授权的本机维护可沿 Identity owner 为指定原身份另签新会话，不提供按 actor ID 选择身份的公开恢复端点。
2. `POST /v1/goals` 使用 Bearer 令牌和 `Idempotency-Key`；同键同内容返回原 job_id，不同内容返回 409。可选 `material_scope` 使用 `goal-material-scope.v1`，须有 `authorized_official_sources=true`。`language=null` 表示自动发现内置官方目录中匹配讨论主题的候选来源；显式语言及版本仍按精确元信息匹配，语言版本须有语言，框架须有语言，框架版本须有框架。完整 scope 参与原键冲突判断。5180 的新目标默认提交自动范围，省略时保持旧目标合同，不推断联网许可。`GET /v1/goal-requests/{request_key}` 只读本人原任务接收回执，供丢失 HTTP 回应后的核对；未知键或其他身份返回 404，不产生目标、任务或事件。
3. `GoalWorkflow.submit` 在同一事务中写入 learning 请求、platform 任务/Outbox 和 delivery 接收事件，提交后返回 202。
4. 独立 relay 只投递已提交行；Worker 锁定当前任务、检查当前学习者是否有效，经 Learning Facade 保存目标。
5. Inbox、目标、任务终态与公开事件同事务提交。此动作是短事务、无外部 IO，因此不持久化没有实际用途的 running/租约状态。
6. `GET /v1/snapshot` 使用一致性快照返回当前身份最近 100 个目标、任务、最近 12 个事件及游标。
7. `GET /v1/events?after=N` 或 `Last-Event-ID: N` 按身份补读事件，再保持 SSE；无效游标返回 409，需重新取快照。游标按身份串行分配，不用全局自增序号猜提交顺序。

`PATCH /v1/goals/{id}` 以 `{"title":"新名称"}` 重命名本人计划；可同时提交 `motivation`，用于将上传材料时创建的空会话草稿更新为完整学习目标。省略时保留原动机及材料授权。`DELETE /v1/goals/{id}` 将计划从学习列表及最近入口移除，保留历史对话和调用记录。存在进行中或结果未知的教学时，须先完成或明确取消再删除。两种操作均提交本人公开事件；其他身份访问返回 404。

5180 附件按钮直接选择原文件，可先上传再发送首条规划消息。上传沿目标、需求、上传票据、原字节和材料任务的既有链路，文件大小及格式限制不变。路线草案使用已提交的原文件及匹配的官方教材；未冻结范围的检索联合两者的精确文档版本。UNKNOWN 读取原回执，不重新上传或获取原来源；本人模型配置及私有材料外发许可继续按原用途校验。

路线讨论由同一次作者调用返回正文、用户约束与 `rag_intent`。模型将有用信息整理为目标和主题，附原用户消息及原文；只提出附理由的建议，不假设用户基础、时间、范围或偏好。原独立检查通过后才创建资料需求。`none/prepare/supplement/revise` 分别表示复用、首批准备、新增主题和调整范围。补充主题保留完整范围，明确修订才替换范围。普通问候不触发整课程准备，不另加逐轮分类模型调用。

首批和补充批次分别为 `MaterialDemandInput.preparation=initial/incremental`，从相关可用内容中选取一个官方正文和一份已就绪用户教材。解析有效正文、可定位引用、版本、权限及按需图文识别在原阶段完成并复用；信息收集期间不做全路线覆盖审核。批次检索采用 `planning-batch-evidence.v1`，只表示可供当前规划使用的选中证据，不授予整路线覆盖资格。普通完整教学消费者仍使用原 `semantic-goal-evidence.v1`。制定计划时在原路线审核中检查需求覆盖与节点依据，具体缺口才增量补查；未变节点可复用已有合格审核，新增节点及受影响依赖重新检查，全局范围、时间和图依赖仍核对。

路线主线保存在 `PlanDocument.curriculum`，包含技术选择、贯穿项目与约定。`basis=model_knowledge` 允许模型设计课程，教材列表、节点章节和引用可以为空；默认 `selected_materials` 保持原教材及逐节点章节合同。实际采用的教材与引用始终来自获准正文。`Plans.curriculum_snapshot` 返回精确修订的主线，教学记忆继承该主线与已学内容。

路线环境通过 `environment_recipes` 引用基础/固定配方，通过 `environment_dependencies` 声明课程包及精确版本；后者可选，旧路线序列化保持。execution 将语言、包清单和构建方式转成需用户同意的 `EnvironmentRequirement`，`course_environment` 随原确认快照和需求请求保存。六语言分别接 pip/npm/Maven/Go modules/NuGet，JS/TS 的 Vite 环境沿 `web-check.v1` 先构建再检查。`build=http` 使用 `project-http.v1`，可选 SQLite/PostgreSQL/MySQL 私有可写数据库，按场景执行请求并回收资源。所有额外安装继续使用原决定 CAS、幂等回执、准备租约及不可变 release；跨任务常驻、外部联网及未支持的系统能力列为 `environment_gaps`。

0069 将 `http_project` 加入原供题、资格、六审、普通练习、Gate 和后继合同。HTTP 服务按 `PORT=8080` 启动，逐场景独立初始化数据库；原回报携带实际状态码和正文，Assessment 按 `http-response.v1` 对照隐藏预期，公开投影只保留样例。HTTP 执行租约为 600 秒。可信控制器按 API、隔离资源、命令行、网页、SQL 和 HTTP 模块分工，共用原执行队列。

新路线讨论使用 `planning_policy=model-first.v1`：确认制定请求后先形成完整草案，不自动建立整课程材料需求。只有影响路线成立的版本兼容、技术冲突或指定原文缺口触发定向 RAG；`material_gaps` 可与完整 `route` 并存，原任务保留草案，补证后只修正受影响决定。定向检查使用 `planning-question-source-evidence.v1`，不追加全课程教材、课时或练习要求。独立审核允许稳定模型知识支撑路线组织，继续核对需求、技术一致性、实际引文和指定材料；无阻塞缺口后才保存完整未确认路线。旧冻结审核沿原合同处理。

自动完整规划批次已有经过检查且不受已知缺陷影响的可用证据时，`usable_for_planning` 允许作者生成路线候选，覆盖仍记为 `partial` 并携带原缺口。作者和独立审核依据具体路线决定是否补查关键教材、版本或先修依据；明确规划缺口、节点教学及显式冻结范围继续按自身完整条件检查。补查后的路线保留该次已经审核的材料批次。需求信息完整与材料准备状态分别表达。

完整规划的材料目标取当前已经审核的用户目标、纳入范围与偏好顺序，替换讨论阶段累积的主题措辞；已经确定的技术选择随当前需求更新，相同需求的材料身份保持稳定。

自动排除坏片段后，规划补查仍只选简介与相关代表正文，再固定这些精确引用；用户显式指定的范围继续完整检查。既有坏片段与原回执保留。

完整规划的精确缺口在剔除坏片段后可复查剩余正文；该固定引用集合检查结束仍不足、且没有新增文档版本时，转入目录章节或新来源获取。继续排除片段导致引用变化，不会持续创建同版本检查批次。新文档版本继续参加后续检查，原独立结论和可用证据保留。

规划材料检查只携带一份最新历史摘要，并合并保留此前检查的问题与精确缺陷记录。同一目录按当前目标和当前页面筛选章节，保留原始顺序与总章节数；重复目录不重复发送。完整路线作者继续读取原有教材目录。

教学与课文生成携带 `learning_memory`：由 Tutor 历史交付、真实课文、学习者陈述和 Assessment 已提交证据按当前路线及分支组成，并保留原记录引用。实际代码摘录标明提交身份和截断范围；独立评估、练习结果、已讲内容分别表达。记忆按需读取持久事实，不新增逐轮摘要调用；已使用历史材料在交付前再次检查许可。

同一身份、目标、用途、材料范围及原授权下的规范化需求跨回合和重新生成复用。正在执行的检索固定原文档版本集合，不随后台新文档替换；新范围使用后续批次。经审核的新意图会停止较早回合遗留的整目标准备消费者，已就绪资料和外部回执保留。

普通讨论回复完成即结束，RAG 就绪不自动续答。经审核的必要信息完整后，回复下显示「制定计划」；`PlanningInput.start_plan=true` 携带 `expected_requirements_revision`，只接受最新合格需求版本。用户明确表示直接制定或没有新需求也可启动，模型必须引用本条原文，并确认信息完整。只有用户已请求且尚未交付的计划任务等待必需批次，在思考步骤显示「等待RAG解析」，就绪后交付完整未确认草案；确认草案是另一个动作。

资料阻塞时返回具体正文与「修复并继续」。`POST /v1/conversations/{id}/material-repair` 诊断当前必需资料、校验已有回执，复用已完成工作；已知提取失败可切换原站获取，未发送请求可随配置修复重新绑定，已知无效回执不能原样循环。未知调用先核对回执，不重发。用户取消后 RAG 完成不恢复该回复；刷新、SSE 重连只恢复已有状态。历史 `stage_replies` 保留自己的思考快照，后续步骤不会挪到之前的消息。

Tavily Key 填在 **我的模型配置 → 材料处理 → 教材搜索 · Tavily**。`GET/PUT /v1/material-search-configuration` 按当前身份读写，保存使用 `expected_revision`；Key 沿既有 CredentialVault 加密，不写前端存储或共享 `.env`，读取仅返回存在标记、启用状态和版本。勾选启用表示同意发送整理后的检索主题和公开网址及相应费用。

资料获取优先使用已有正文与向量；不足时 Tavily 只在当前已授权官方来源域名中定向搜索，并再次校验精确 URL 前缀。搜索摘要只作候选，不作教学证据；只有选中页面才提取完整正文并进入原 RAG 处理。图像或图表转回原站解析以保留完整性；未启用 Tavily 时沿用原站获取。默认一跳和明确缺口二跳的范围不变。搜索、提取都复用原外部调用账本，先保存回执再应用，UNKNOWN 不重发。

`GET /v1/conversations/{id}/material-progress` 只读本人当前会话最近规划/教学需求，返回 `MaterialPreparationProgress`：来源选择、原文获取、正文解析、按需 OCR、质量检查、切片、Embedding、索引及检索/重排/覆盖检查的实际状态、相关文件和等待原因。它不启动准备或模型调用。5180 在会话右侧圆角窗口展示并按实际状态更新，支持收起及减少动态效果设置。

来源发现按对话增量提交小批次。默认获取入口与一跳章节；二跳仅针对明确的缺失主题选择，不再自动递归到更深页面。链接保留正文标签及原顺序，首批优先相关入门章节。旧的未选深层资料停止自动处理，已有原文、版本和 UNKNOWN 回执保留。`html-main-text.v8` 使用固定版本的 `readability-lxml` 在已保存的 HTML 上本地定位正文，再按节点身份取回原页面中的选中区域，保留代码缩进、表格、标题和待解析图文，不直接采用库清洗后的内容。未定位到收敛正文或发生明确解析错误时，原本地选择器回退一次；不重新抓取或调用模型。正文 HTML 换行统一为 LF，原始文件保持原字节；仓库文件继续读取页面保存的原始 Markdown/代码数据。导航、页脚、隐藏内容、推荐和复制控件不进入正文。自动选中 HTML 的可用正文以 `selected-source-text.v1` 冻结精确范围；文档的 `partial` 状态与 `unresolved_regions` 保留。独立检查收到每个文档版本的未解析区域及上下文，不能将图表说明当作图表内容，当前目标需要这些内容时继续换源。显式整份来源仍要求完整处理。旧提取经版本化修复派生新版本，原始字节未变也不能复用过期解析版本。

规划自动选中及补建的来源使用 `index_mode=lexical`，精确正文进入原独立覆盖检查，不以前置正文 Embedding、查询 Embedding 或 Rerank 阻塞。后续普通混合检索按需补建向量；默认 `hybrid` 的旧需求序列化保持。新来源请求可创建已取消准备作业的后继，不复活原作业，也不绕过 UNKNOWN。

覆盖合同 `scoped-source-evidence.v1` 要求 `findings` 指明问题、精确引用、影响主题和解释，区分局部片段与整份文档。被影响片段不能充当证据；新自动选择只重查未受影响的范围，显式冻结绑定保持。聚合目录同时纳入子检查的可用证据与问题引用，分别标识，保留原问题与 findings，使用独立合格证据补齐覆盖；公开文章末尾的付费宣传不作为正文访问受限的依据。`supported_topics` 记录实际已支持主题，互补 partial 继续复用。

同一规划 Turn 的自动后继共享 `acquisition_state.budget_root`，继承双方必须是在该 Turn 创建后建立的批次，避免新请求继承旧 Turn 的消耗和续配状态。初始 12 个资源、两轮搜索；新合同以新增已审核支持主题判断覆盖进展，可续配四个资源和一轮搜索，仅多读一份正文不算进展。没有新证据最多一次有明确候选的探索续配；最终上限 24 个资源、四轮搜索。失败消耗保留，`usage` 分别记录选中资源、实际获取和缓存复用。充分、耗尽、取消及 UNKNOWN 结束或阻塞当前链，不自动开启新一轮。

覆盖检查与完整摘要汇总按当前模型的输入、输出容量分组，不再固定每组六个片段或两两汇总。模型使用本组短引用键，后端还原为冻结的精确引用并核对全部片段或子检查，保留原范围、摘要、证据与不确定性检查；已有完整引用回执仍可复用。已创建的检查分组不重建。向量/OCR 批次及语义检查提交进展后立即允许原 relay 调度下一步，未取得进展和 UNKNOWN 继续使用原等待、退避与回执恢复机制。

新获取的 HTML 来源若主内容主要由获准章节链接组成，且没有代码、表格或待解析图文，保留原始响应并发现获准章节，不为目录词条单独生成向量或教学覆盖检查。已有文档版本、用户上传资料及含教学内容的正文仍走原完整准备流程。进度接口的 `steps.unit` 区分文档、向量切片及覆盖检查组；`level` 标识当前汇总层，`last_progress_at` 纳入实际批次提交和检查完成时间。5180 沿用原面板样式展示这些计数。

公开 GET 的连接失败、超时、响应中断及未完成读取的租约过期记录为 `waiting_dependency/source_network_unavailable`，自动发现跳过该链接继续选源。历史 `blocked_unknown/source_read_unknown` 仅在原请求为 direct、没有正文回执及材料作业时可跳过，原观察不改写；Tavily 提取或材料作业的 UNKNOWN 继续阻塞。自动发现选中过且尚无正文的网络失败链接不再由后台扫描重复读取。其他定期来源检查的网络失败及 HTTP 408/429/502/503/504 使用 30 秒起、最长一小时的指数退避；到期登记新的公开 GET 观察，原观察保留。模型、搜索、提取、OCR/Embedding/Rerank 的 UNKNOWN 继续核对原回执，不创建替代调用。依赖资料就绪可唤醒原来处于 `blocked_unknown` 的发现任务；重新计算实际依赖后续行。右侧进度分别展示本轮资料和后台资料数量，读取接口不发起调用。前台教学使用 `leornian.foreground` 队列，资料任务使用 `leornian.materials` 与独立 `material-worker`，两者分别运行两个并发任务。旧 `leornian` 队列由资料 Worker 承接，避免旧抓取唤醒挤占新对话，不清空 Redis。

独立检查的 `required_checks` 随实际请求冻结，覆盖基础和当前上下文要求；有效补充检查不设数量上限，其负面结论同样回到作者修复。格式修复不能遗漏或翻转已冻结检查。同一候选、同类协议错误、相同已知检查及输出容量再次出现时，进入 `blocked_protocol`，停止自动调用；新增有效片段、有效检查或实质新候选可继续推进。后台任务提供显式恢复原任务入口，恢复重验当前权限并保留负面结论。

作者协议修复保留实际字段诊断与最新失败回复，放在固定规则和材料之后，同一失败内容只发送一份；私有推理不进入修复。JSON 未闭合与缺少路线/资料缺口分别处理。原 `protocol_repair` 保存规范化错误历史，位置偏移、数组下标及措辞变化不解除重复错误阻断；已解决的错误减少可记录进展。已请求制定时，完整路线和仍需补齐关键依据的 `material_gaps` 分属两条输出路径，缺口由原自动材料流程处理。

文字材料检查省去未解析图片区域的内嵌 `data:` 字节，保留区域位置、标签和未解析状态，并标记 `inline_resource_omitted`。原始文档版本继续保存这些资源，正文引用与来源身份保持；省略图片字节不构成图片已经解析。

模型思考状态与思考文本分开公开：`tutor.thinking.thinking_summary` 是阶段提示，`thinking_text` 是模型返回并过滤后的累计可展示文本。`VisibleThinking` 缓冲完整句子，过滤内部提示、工具协议和代码围栏，遮蔽凭据；独立检查角色不发布思考文本。公开事件持久保存实际文本，快照及历史读取恢复；旧的已完成回复可从本人已接受作者回执只读投影，不重发模型调用。前端复用 LibreChat 的思考折叠组件与 Markdown，将实际文本映射为原生 `think` 内容部分。进度通知失败会记日志并继续接收完整供应商回执，避免将展示通知故障变成外部结果未知。已有 UNKNOWN 保留原调用记录；对话中的重新发送入口由用户明确点击后取消原等待，再提交一个新请求。

`tutor.thinking.thinking_step` 提供结构化步骤：模型请求使用原调用标识，工具操作使用原调用记录标识，逐步更新摘要、详情、状态和耗时。同一步更新不增加步骤数量；`Turn.thinking_steps` 按首次出现顺序恢复各步最新状态，Snapshot 与 history 均按本人身份读取。工具详情仅投影公开标识、数量和操作状态，不复制工具原始参数/结果、准备中的内容或锁定提示；独立检查只公开阶段状态。5180 复用原生 ThinkingButton 与 Markdown，先展开步骤列表，再独立展开单步详情；同一身份和回合的展开状态跨实时/历史视图保留。旧的累计思考文本显示为一条摘要，不推测其内部操作步骤。

正文仍在独立检查通过后交付。5180 前端接收 `tutor.succeeded.reply_text` 或快照中新接受的 `assistant_text` 后，以小批文字逐步呈现，不依赖 SSE 分包速度；播放结束且历史行已加载后切换至原消息行。初次读取的历史直接完整展示，重复事件及快照刷新不重新播放；切换身份会清理原身份的播放队列。此呈现过程不增加模型调用，也不提前公开未通过检查的候选正文。

路线讨论使用原 `POST /v1/conversations/{id}/plan-requests`，设置 `discussion=true`、`expected_revision` 和 goal focus。请求模式冻结在原交付任务中，同键不得切换模式。planner 可先交付澄清文本，或在 `route` 中提交完整 `PlanDocument`；路线沿原来源校验、独立检查与版本保存流程，讨论本身不确认、不打开教学会话、不创建练习。用户另行确认精确修订后，前端才进入第一个节点的学习视图。旧请求默认 `discussion=false`，保持原结构化路线合同。

当前没有事件清理策略。SSE 轮询数据库，每次重新校验会话；公开事件不包含会话令牌或内部仓储对象。202 只代表已接受，不代表目标已保存。

WP08 后端会话使用原 conversation/Turn/Runtime，旧会话只有显式 `open` 后才进入新语义：

- `GET /v2/conversations/{id}/teaching-session` 无会话返回 null；POST 同路径 `/actions` 接闭合 `open/set_mode/pause/resume/return_to_main/set_topic/set_continuation_policy` 和原命令身份/CAS；GET `/actions/{action_id}` 只读已提交回执。新增策略默认 `manual`，原六类命令与历史回执不重新解释。
- `GET /v2/conversations/{id}/teaching-branches?before=&limit=` 只读同 actor/会话的单层分支元数据；snapshot 增加有界 `teaching_sessions/teaching_branches`，消息仍走原历史分页。
- 开启后新教学请求必须携带当前 `teaching_session_revision`；旧受理请求保持原输入/Run/Task 幂等解释。控制本身不调用模型/创建 Turn，普通前台 Run 必须先完成或明确取消；新明确消息/动作/控制可经原取消链优先接管自动 Run，重放不接管。暂停引导不屏蔽明确用户提问。
- 待办主线工件的问题由服务端锚定，同一活动分支复用，不能隐式改主题或选新工件。答疑只冻结 read 工具，仍经原作者/独立检查/原子交付；只读锚点公开消息、已释放内容及本分支历史，不带原准备协议/私有推理或锁定 H1—H3。
- 接受时按真实练习/提交审查 owner 向原 ItemBank 账本写唯一 `artifact_question.v1`；准备、拒绝或失效迟到回执不算实际接触。纯演示不造 owner/Assessment 事实，不自动作答、执行、评分、解锁提示或写掌握。返回仅关闭分支，主题切换退役分支，旧历史/回执保留。
- 会话代际、当前活动分支、冻结后的锚点版本/内容及原材料/计划权限贯穿派发与接受。0046 在所属 5456 安装后冻结；后续 0047/0048 安装并冻结在新 5457。原生前端已接显式控制、当前 revision/focus 和答疑分组/折叠。
- `GET /v1/conversations/{id}/teaching-intents?before=&limit=` 只读同身份/会话意图页；POST `/{intent_id}/cancel` 收 `client_action_id` 并保存不可变取消结果，GET `/{intent_id}/cancel/{client_action_id}` 只读该原回执，不用当前列表代替 UNKNOWN。返回的 `run_status` 来自原 Runtime，未派发意图为 null。
- 只有显式 `after_result.v1` 且 guided 的原已完成 owner 结果/明确 demo completion 才同事务登记意图。原 relay 有界认领，暂停/答疑/考试/用户前台等待；模式/主题/策略使旧代际失效，暂停/恢复/返回保留。原源内容/当前结果/权限复核后只创建一个原 Run，复制源工具版本和模型作用域，原作者/检查/原子接受不变；自动消息不作为用户发言，不携带原私有准备协议或自行再触发。定时/后台生产者尚未实现。

后端切片受影响范围 **95 项分批通过**（会话最终 15、其余原链路 80，不相加交叠批次）；原请求回放用例的夹具基数误算已改为完整前后集合不变断言，没有放宽业务检查。该切片合同生成、旧入口类型/36 项测试、原生严格 TypeScript、Ruff 和 tracked diff 空白检查通过。随后独立 8096/5186 的真实浏览器/SSE 验证六类控制、三轮答疑及历史/草稿恢复；最终六个控制回执、三份答疑接触，原工件 revision 1、无作答/Attempt/正式进度。Native 消息桥接继续原身份/归属检查，再读完原公开 history 分页并投影角色/分支，不返回半段历史。原生 **77 Node + 67 DOM**、严格类型与独立构建通过；作者/检查仍为离线 HTTP，不代替供应商质量、broker、Runner 或 Tauri 验收，未改共享样式或用户 5180。具体范围及后续工作见根 README。

V2 工件组合另有显式能力门禁：原 Runtime 的目录/准备工具、独立检查和候选原子交付复用原教学链；31 个受控 renderer 与受控组件准入均已接，但不代表全部真实互动完成。`learning_practice.v2` 才为新 Run 冻结原单选/Python 准备工具；`learning_responses.v1` 另冻结响应型列题/准备，旧 Run/旧工具不升级。当前 Run 列出的精确候选按组件委派原 Assessment/Execution。`/v2/conversations/{id}/learning-artifacts/{artifact}/sources/{component}` 读取已接受精确引用及真实期限；0034 的材料权限事件在撤权事务提交。动作 `/actions/{action}` 和 Turn `/turn-requests/{key}` 为只读回执，不重新派发。独立完整 LibreChat 宿主与 5180 只读预览分开，原库/服务未升级；实际验证及剩余范围见根 README。

2026-11-06 真实组合续接修复：作者首次 wire 从实际 `RoleSpec.context_manifest` 判断交互合同，不读取尚未反映新上下文的缓存 task。最终交互必须整个响应使用 `LearningReply` JSON，说明放 `text`；混合普通正文/围栏与交互 JSON 在原候选校验中拒绝并修复，不自动抽取挂载，普通无交互文本及旧角色仍兼容。独立检查按接受后的原子发布时点评估引入，不混同异步文档任务或要求学员审批。新建准备还检查每个可编辑 `IsolatedPreview` 自己的 `preview` 动作，编辑和 demo 记录不能更新 iframe；检查不放入历史 DTO 读取或原准备重放。无新迁移/工具能力，0048 保持冻结；真实失败、原完成和未挂载回复不被覆写，具体分层证据见根 README。

提交评审阅读确认使用 `learning_code_review.v2`，替换 v1 能力并冻结 `prepare_learning_code_review_composition_v2`；新旧版本互斥，动作能力仍最多七项。准备产生 `submitted-code-review.v2`，作者/独立检查继续核对完整原提交、行号与原结果。显式 `complete_review` 接原动作身份/CAS 和精确组件，Tutor 同事务保存唯一 `learner_review_report.v1`、原 presentation/内容身份/Attempt/评价/时间、工件终态、事件和 `learning_review_action.v1` 回执。GET 及同命令重放恢复原事实，取消保留已读记录；原 Assessment 成绩和进度保持原记录，阅读确认不生产 `teaching_intent`。详情协商 `code_review_capability=learning_code_review.v2`，v2 读者兼容旧 v1，空 `review_reports` 省略。0049 在新所属 5458 安装后冻结，当前源码 readiness 要求 0049；实现入口为 `bootstrap/review_completion.py` 与 Tutor 的 `reviews.py`。专项及实际浏览器/Runner 结果见根 README 的“第四阶段提交评审阅读确认”。

普通 Python 多 Attempt 使用显式 V2 入口，原 V1 和正式 Gate 不改语义：

- `POST /v2/packs/{id}/execution-submissions`：只收普通训练 slot、代码、精确 `previous_attempt_id` 与显式 `retry`，同幂等键不重复运行；同代码仅 error 后明确重试才建新 Attempt。资格/考核/后继不由此重复。
- `GET /v2/packs/{id}/execution-practice-attempts?slot=&before=&limit=`、`GET /v2/python-practice-attempts/{id}`、`GET /v2/python-practice-requests/{key}`：读本人普通训练历史与已提交请求，不执行、评分或派发模型。
- `POST /v2/python-practice-attempts/{id}/cancel`：仅取消 V2 普通练习；保留 error 与迟到回执，重试另建身份，不复活原任务。
- V2 工件动作另含 `respond_component/run_component/cancel_component_run`，当前业务 scope 从不可变 owner 绑定取得，不能由 payload 指定 pack/slot。`learning_action.v2` 保存精确组件回执；直接原业务 API 的更新可以没有工件动作 ID，不补造。

0035 保存显式练习策略/序列/父 Attempt 和逐次曝光反馈；0036 保存不可变公开所有者绑定及可变组件投影；0037 保存知识响应结果与组件引用；0038 保存请求的普通响应格式及原供给任务的发起 Run/模型配置作用域；0039 在原 presentation 保存完整提交审查绑定。0040 固定 SQL/项目题包环境、原 Assessment 的私有比较策略/多 Attempt、资格及原队列的新输入引用；0041 只增加固定公开样例位置/实际投影，不回填旧行或改成绩；0042 扩展原候选/组件到 program Attempt 的关联。0043 仅新增 Assessment 的不可变普通练习直接答案辅助事实，本直接答案切片时点的源码 readiness 要求 0043；0040—0042 仍冻结在独立 5452 库，0043 只在新建所属 5453 测试库安装，不自动升级旧 5451/5452 或原开发库/服务。最新训练用于当前资格，旧评分与旧 V1 工件结果保持原身份；普通练习通过不写正式进度。

`learning_direct_answers.v1` 是独立客户端能力，仅新 Run 冻结 `prepare_learning_assisted_composition`；每个绑定仍须本 Run 原单选/Python、response 或 program 能力及实际列材回执。原 Runtime 准备/独立检查/exact_handle 交付只携带公开题目与 `practice-direct-answer.v1` 标记，不带参考。用户对精确组件明确提交 `request_direct_answer` 后，原 ItemBank 只返回该普通槽的已审答案/解释（程序用已资格验证的原盲解参考），原 Assessment 记录唯一辅助，原曝光、Tutor revision/event 和幂等回执同事务提交。命令不接 pack/slot、答案、测试、分数或执行输入；不自动作答/运行、不改旧成绩、不写正式进度，活动考试、失效材料、旧准备与运行中的组件均不能借此读答案。回看与 GET 不重复记录；动作回执仅含原身份，不回传参考正文；详情另协商 `direct_answer_capability=learning_direct_answers.v1`，仍重验当前作用域/材料。此直接答案切片不包含 H1—H3，其后续独立实现见下段，不用直接答案冒充提示。

后续 `learning_hints.v1` 单独为新 Run 冻结 `prepare_learning_hint_composition`，每个 owner 仍须原能力与本 Run 列材。三层按概念/策略/下一步区分用途，保存在原 Tutor 的私有 presentation 并进入原内容身份；原独立检查读取实际回执，不能以格式、拆段解释或直接答案冒充渐进提示。公开定义、助手正文、初始详情与待补充任务摘要不透出锁定提示；明确 `request_hint` 只收精确组件、原身份/CAS 和下一层 level，原 Assessment/ItemBank/Tutor 事实同事务提交，不改稿、作答、执行、评分或推进正式进度。详情另协商 `hint_capability=learning_hints.v1`，旧行/Run/工具不升级；直接答案仍单独请求。0044 仅在新所属 5454 测试库安装后冻结，当时源码 readiness 要求 0044，不升级旧 5451/5452/5453 或原服务。

演示续接增加独立 `learning_demo_events.v1` 与仅新 Run 冻结的 `prepare_learning_demo_composition`，沿原完整 V2 校验、独立检查、exact_handle 与原子接受；四类可报告端口是 AlgorithmPlayer/StepPlayer/SequenceDiagram/IsolatedPreview，不新增任意回调。新工具 wire 使用紧凑目录索引避免重复整份 31 组件 Schema，实际参数仍由完整闭合 DTO 验证，六种旧工具声明不变。`start_demo` 明确冻结本端口输入并签发代际/nonce，`acknowledge_demo_event` 核对服务端推导末步/预览及 sequence 1，`complete_demo` 单独确认 sequence 2。原 Tutor 保存学员报告、工件版本/事件及幂等回执，不创建 Attempt、执行、评分或掌握；重开不覆盖旧完成，混合 owner 保留原分数/状态/能力和文件预算。详情需 `demo_capability=learning_demo_events.v1`，默认最近五份完成，`GET .../demos/{component}/completions?before=&limit=&demo_capability=learning_demo_events.v1` 分页读取完整历史；复用原材料 share-lock 当前权限检查，不解除锁来迁就只读事务。0045 只在新所属 5455 库安装后冻结，该演示切片时点源码 readiness 要求 0045，旧库/服务不升级；浏览器二分两代与刷新恢复为局部实测，非真实模型或全部演示场景。具体分层证据见根 README。

本轮演示最终专项 14 项和 Ruff 通过，包含纯演示不可借用 program 文件预算、原 128k 全能力预算/严格参数、分页/当前权限等；批次不与较早影响范围相加。原生 69 Node + 56 DOM、严格类型/合同/独立最终构建分别记录。实际二分两代六动作后取消/刷新，最终 revision 8/cancelled、七动作、两份完成、正式进度 0；记录保留但不允许再写。仅重启所属 8095/5185，不为加载已确认的离线预算配置额外调用模型，不改旧库/服务。

提示续接影响范围 70 项通过，收尾锁定提示不得进入助手正文专项另 1 项通过；宿主 68 Node + 48 DOM、原生严格类型、合同、Ruff 与最终独立构建通过，批次不相加。新 8094/5184 经正常本机身份、真实对话/原 Runtime 的明确离线 HTTP 质量链交付，浏览器先选 B、依次请求 H1—H3、单独请求参考 A 并刷新；仍无作答，随后明确提交 B 仍 false，提示三份、直接答案一份、动作五个、正式进度 0。390 像素无页面横向溢出，视口已恢复；真实数据库/API/浏览器/SSE 不代替供应商质量、全部辅助场景、Runner、broker 或 Tauri。完整客户端独立输出到 `.local/librechat-hints-native-20261106/dist`，原预览/共享样式和旧服务保留。

本能力的九类题源专项先有 12 项通过，追加“已评分后参考不改分/撤权不回正文”后影响范围 61 通过、2 项未启用真实 Docker 的组合用例跳过；各批不相加。新 8093/5183 正常身份/对话与原 Runtime 离线模型链实际交付单选，选择 B 后请求参考 A 不改草稿或提交，刷新仍只有一份辅助；随后明确提交 B 仍为 false，辅助一份、动作两个、正式进度 0。390 像素无页面横向溢出，视口已恢复，宿主 68 Node + 46 DOM、类型/合同/Ruff/独立最终构建通过；真实 API/数据库/浏览器/SSE 与离线供应商回执不等于全部场景或真实教学质量。新 5453 库独立保留，旧库/服务及 5180 均未升级。

完整提交审查须另声明 `learning_code_review.v1`，仅新 Run 冻结 `prepare_learning_code_review_composition`。原公开普通 Python Attempt/评价提供任务、完整只读代码与结果；模型只提逐行精确引文/教学意见，经原独立检查和 exact_handle 原子交付才写原辅助。未交付/取消/未选中的准备不曝光，新 Attempt 不改旧审查，旧评价文档和评分不被覆盖，不新建 scorer/运行时。详情读取另须 `code_review_capability=learning_code_review.v1`，旧读者保留摘要/取消。离线 HTTP/真实数据库、浏览器和实际本机 Runner 证据见根 README；不称为真实模型质量或 SQL/多文件完成。

原 SQL/多文件及六语言 stdio/HTML 检查 Profile 已续接原作者、public-only 盲解、实际资格、六审、发布、Assessment、多 Attempt 与能力协商队列。`modules.execution.contracts` 不接受镜像、命令、宿主路径、业务连接或预期答案；Runner 精确声明 Profile/方言/运行时版本才可认领，未声明仍只领原 Python。新任务租约 300 秒，原任务 90 秒。环境错误让原供给等待；明确允许的精确 release 与资格恢复走原链，不重发未知调用或借换题调用作者。源码、工程与完整产品旅程的实际验证分别见根 README 及 [Runner](../services/runner/README.md)。

### SQL 与多文件普通练习

- `pack-requests` 显式 `kind=sql_query/python_project/project_stdio/web_project` 并固定 `program_environment`；后续修订不得换环境。私有期望只在原 ItemBank/Assessment，发布同时需要 5 份实际资格和六审通过；盲解只看公开题目/样例。新 stdio/Web 种类强制本人当前允许的有效 release，旧 SQL/Python 合同按原可选 release 兼容。
- `GET /v2/packs/{id}/program-practice?remediation=` 打开原公开练习/合格补救；`POST /v2/packs/{id}/program-submissions` 只接 typed answer、普通 slot、精确 `previous_attempt_id` 及显式 `retry`。SQL 提交只有查询，项目必须保留完整固定清单/入口与受保护内容，不接受 caller 的环境/评分/测试。
- `GET /v2/packs/{id}/program-practice-attempts?slot=&before=&limit=`、`GET /v2/program-practice-attempts/{id}`、`GET /v2/program-practice-requests/{key}` 为只读恢复；`POST /v2/program-practice-attempts/{id}/cancel` 不承诺物理立即停止，迟到结果不应用到新 Attempt。`POST /v2/packs/{id}/program-review` 仅续接已资格完成的原审核阶段。
- `sql-result-typed.v1` 比较 cell kind、NULL、列名/列序及公开的 ordered/multiset；Python IO 项目严格比较 JSON 整数，stdio 文本仅统一 CRLF 并移除一条末尾换行，Web 使用严格类型/完整 key 的实际观测。`sample_result` 只投影原公开样例实际值，隐藏数据/期望/实际输出仍私有。独立 `compilation` 记录构建结果，失败时没有运行用例；取消/迟到不应用。普通练习不产生正式进度，正式 program Gate 另经原关系检查、明确开考和整组一次提交。
- `learning_programs.v1` 单独冻结 `list_learning_program_candidates` / `prepare_learning_program_composition`；原始 `sql_workspace/project_workspace` 候选不能直接交付，只能作为实际列材后的组合绑定，独立检查后原子交付。SQL 初始查询、项目完整文件/保护范围固定；混入其他 owner 时必须另有对应能力。详情须 `program_capability=learning_programs.v1`；`run_program_component` 接 typed answer/精确父 Attempt/显式 retry，沿原 Assessment/执行，结果与组件/事件事务一致。原 API 新稿也更新该绑定，不保留第二份业务事实；取消/迟到/只读恢复沿原合同，宿主已接动作/草稿/历史。

### 响应型知识检查

- 原 `pack-requests` 增加显式 `kind=response`，保留原作者、public-only 盲答、六审、完整修订与发布；多选、预测、参考型简答、排序和逐行定位有各自公开格式与私有参考。考核/补救槽不从普通练习开放，原 Gate 拒绝这类题包。
- `GET /v2/packs/{id}/response-practice` 打开两份普通练习并记录原曝光；`POST /v2/packs/{id}/responses` 只接普通 slot、typed 回答和幂等键。原 Assessment 按版本化的固定比较 Profile 一次锁定，并保存参考、反馈曝光与事件；不执行题中代码，也不调用语义评分模型。
- `GET /v2/packs/{id}/response-results` 只读本人原结果，仍检查当前材料/计划；组合 `answer_component` 从原绑定取得 pack/slot，不能由 caller 选择参考/分数/测试。简答 `correct=null`，行号对照不自动评分理由。预测保留有意义的行内空白；空输出必须明确确认。
- 新 source kind 不混入旧候选工具，不直接发布为 V1 工件。带响应型绑定的 V2 详情须带 `?response_capability=learning_responses.v1`；不支持的读者收到明确不可读结果，仍能读公开摘要并提交原取消动作。保存的旧 Run、题包、工具回执和成绩不改语义。

### 对话按需供题

- 新支持动作的教学 Run 才冻结 `request_learning_practice_supply` / `get_learning_practice_supply`；精确 node scope 和各 kind 的动作能力都须匹配。请求只接 command_key、kind、instruction 及 response 的两道普通练习格式，不接作者文档、私有答案或执行/评分指令。普通 `pack-requests` 也可显式固定 `response_formats`，旧 NULL 保留原解释。
- 登记复用原 `Packs` / `SupplyTasks`，不立即启动第二个会话 Run；原 `AutomaticSupply` 在当前前台 Run 让位后认领首个作者，再走既有盲答、六审、修复/修订和发布。取消发起 Run 可阻断排队作者；UNKNOWN 保留，不切模型绕过。BYOK 的模型配置作用域从发起 Run 固定，不借开发共享模型准入。
- 工具状态读取不推进任务。发布后仍须在当前选择 Run 实际列出候选，再准备并独立审核交付；不将 task_id 或 pack_id 当 exact_handle。宿主复用 snapshot/SSE 和 `/v1/packs/{id}/cancel`、`automation-resume`，按原任务归并版本，明确恢复不等于重发未知调用；不增加主动教学推送。

## 运行

推荐从仓库根目录运行 [Compose](../infra/compose.yaml)，将 Celery 保持在 Linux 容器中，不依赖 Windows 原生 Celery 支持。

单独启动 API 或迁移时，先通过本机环境变量提供独立库连接：`LEORNIAN_DATABASE_URL`。默认连接不含密码，不能代替实际配置。迁移不在 API 启动时隐式执行，而由独立 `leornian-migrate` 命令管理。

从本目录运行：

```powershell
uv sync --frozen
uv run leornian-migrate
uv run uvicorn leornian.entrypoints.api:app --host 127.0.0.1 --port 8088
```

`/health/ready` 只检查数据库迁移是否就绪，不保证 Worker/Redis 正常。后台不可用时 API 仍可持久接收目标，界面显示 queued，而不是伪报成功。

## 完整测试

先启动本项目 postgres，创建专用测试库一次：

```powershell
# 从仓库根目录执行，不能指向旧 Aearn。
docker compose --env-file .env -f infra/compose.yaml exec -T postgres createdb -U leornian leornian_test
```

然后在后端目录执行：

```powershell
$line = [IO.File]::ReadAllLines((Join-Path (Split-Path $PWD) '.env')) |
    Where-Object { $_.StartsWith('LEORNIAN_POSTGRES_PASSWORD=') }
$password = $line.Substring($line.IndexOf('=') + 1)
$env:LEORNIAN_TEST_DATABASE_URL = "postgresql://leornian:$password@127.0.0.1:5448/leornian_test"
$env:LEORNIAN_TEST_DOCKER = '1' # 隔离测试及动态执行完整旅程；镜像须已在本机
uv run ruff check src tests
uv run pytest -q
```

测试 fixture 拒绝名称不是 `leornian_test` 的库，不清表；每项测试使用独立学习者。覆盖归属/幂等/原子回滚、会话/来源失效、Runtime UNKNOWN/取消/迟到结果、完整质量链、供给/讲评衔接、概念/执行评分和 Docker。最终测试数见根 README。未设 `LEORNIAN_TEST_DOCKER=1` 时真实 Docker 专项跳过；SQL 专项另需提前准备可信客户端镜像。动态执行原旅程包含 27 个用例，新情境代码后继旅程包含原/新包盲解、错误训练/补救、后继和正式考核共 48 个用例。真实模型与 real broker/进程重启不由进程内测试冒充。

## 目标区域

- `src/leornian/entrypoints`：HTTP/SSE 与后台任务入口。
- `src/leornian/bootstrap`：少数允许组合具体实现的位置。
- `src/leornian/modules`：identity、learning、tutor、knowledge、item_bank、assessment、execution；item_bank 同时拥有固定样例和动态概念题包。
- `src/leornian/agent_runtime`：模型传输、唯一 AgentLoop、运行/调用/工具事实仓储。
- `src/leornian/delivery`：公开投影、快照与事件交付。
- `src/leornian/platform`：持久任务、消息投递等基础设施。
- `src/leornian/shared_kernel`：少量通用基础类型。
- `tests`：架构边界、合同、集成和完整用户旅程测试。
- `migrations`：新库有序迁移，不复制旧库整条历史迁移链。

这些区域随实际切片建立，不预先填充空类或各模块四层占位目录。

跨模块遵守公开合同和数据所有权。短用例直接调用，长任务返回标识；工具参数不能声明当前权限，模型输出不能直接授权业务写入。

完整合同见 [架构基线](../docs/architecture/overview.md)。

## Tutor 合同

- `GET /v1/tutor/availability` 仅表示独立模型配置完整且已启用，不探测供应商，也不承诺网络可用。
- `POST /v1/conversations` 使用 goal_id 为当前学习者取得/创建对话；每个目标一份对话。
- `POST /v1/conversations/{id}/turns` 使用幂等键，返回 accepted/run_id/turn_id。每个对话只允许一个活跃或 UNKNOWN 回合；不同内容复用键返回 409。
- `GET /v1/runs/{id}` 返回公开运行状态与是否可承接；不暴露 provider prompt、原始回执或密钥。
- `POST /v1/runs/{id}/cancel` 停止本地后续动作，不宣称远端停止。`resume` 只承接当前已记录完整回执；没有回执返回 409，不重发旧调用。
- 已知 `invalid_relation_batch` 的 Gate 如仍有完整未应用回执，也可沿同一 `resume` 承接原结果；须未开考、未取消、没有已完成关系裁决，且当前会话/来源/计划/教学/曝光仍有效。它不创建新审核或重新派发旧调用，质量失败和无回执 UNKNOWN 不在该入口刷审。
- 原有 snapshot 增加 conversations/turns/runs，原有按身份有序 SSE 增加 tutor 公开事件。
- `TurnInput.focus` 可绑定目标、精确确认节点/课时或该节点已公开回执；服务端重新核验绑定，不从“最新课时”猜当前节点。
- `GET /v1/delivery-tasks?before=&limit=` 与 `GET /v1/delivery-tasks/{id}` 返回本人交付摘要，不返回候选/raw/private prompt。`POST .../cancel` 设置原任务取消屏障；`POST .../resume` 承接依赖或已记录完整回执，waiting_input 需要 `additional_instruction`。补充不替换原请求。
- `GET /v1/conversations/{id}/history?before=&limit=` 按 keyset 加载更早记录；快照是近期窗口，不代表全部历史已丢失。

Worker 和 relay 只唤醒协调；运行租约与数据库调用事实才决定能否执行。外部网络请求期间不持有业务事务。HTTPX 禁用重试与重定向，raw response 在解析/工具执行前落库；4xx 明确回执记为已知拒绝，5xx/失联保持 unknown。usage 无回执时是未知，而不是零。

新教学、规划、课时与教学工件由 `tutor.delivery_tasks` 持久协调候选、独立检查、诊断修复和重新设计，仍使用原 Runtime。候选未通过不公开；结构校验/独立质量报告接受和业务保存同事务。不设任务总步骤或补正次数上限；相同输入的相同已拒候选不重审刷绿，格式修复保持可恢复裁决。等待信息/依赖/配置与 UNKNOWN 分开，取消和版本替换不自动恢复。日常教学按冻结权限使用上下文/工件工具；规划、课时、工件作者、独立检查和讲评无工具。

0022 的工具合同在 `agent_runtime/tools.py` 静态注册，Schema 和严格 JSON 参数验证共源；`bootstrap/tools.py` 分派业务 Facade。原五个工具保留，0031 后新教学还冻结候选列表工具及版本；旧 Run 不增加能力，原请求声明与当前许可交集仍有效。参数错误返回字段级结构化结果，冲突需重读，未知名称不执行。工具调用幂等与业务命令键分开；工件任务按原会话排队，前台结束后由 relay 启动同一原生 Runtime 的 artifact.v1，再独立检查，不通过则继续修复。

教学工件由 tutor 拥有不可变版本，不吞并路线/题目/评分模块。修订入队和接受时复核 expected_revision；完整已公开版本进入原教学历史/Gate 上下文。读取按精确版本和章节分页；独立只读可分连接并行，同批重复读取复用，不共享连接并发或跨回合缓存权限。模型网络不在工具数据库事务里；任务接收不等于交付，取消前台也取消尚未启动的子任务。公开 tools 端点只含安全执行摘要，无原参数/推理/raw。

`agent_runtime/policies.py` 的新 `stage-policy.v2` 分开正文参考预留与思考模式共享输出；不设应用侧独立推理硬限额。输入上限为通道输入能力与“窗口减正文参考预留减余量”的较小值；装入完整实际请求后，共享 `max_tokens=min(通道最大输出,窗口−完整校准输入估算−余量)`。正文参考预留不再把推理截断在 8,192 等阶段值。非思考输出仍使用阶段预留。必需内容原子保留，协议、工具、必要 reasoning 回放和修复信息全部计入；可选历史按完整回合装入（含工具链），保存选取清单。启发估算不假称 tokenizer；真实 usage 校准后续请求。旧 v1 请求和已有 prepared 的请求/policy 不重算、不改写。

`LEORNIAN_MODEL_STAGE_THINKING` 是可选 JSON 阶段覆盖；阶段必须已注册、值只能为 enabled/disabled，空值沿用全局配置。当前开发通道为教学/规划/课时/独立检查/讲评、生题作者/盲解/六审和 Gate/后继关系启用思考。思考工具采用自动选择，不发送 required/命名强制选择，也不静默关闭思考。原助手 content/reasoning_content/tool_calls 与工具结果完整持久承接；同一工具链冻结原模式及通道预算，下一回合的历史单元含原工具链和已接受作者推理，不混入质量检查推理。非思考旧消息无推理时为 null，供应商明确报告空推理/0 也合法，不伪造。工具必须同时属于当前角色白名单与原冻结请求声明，旧无工具调用不因部署获得权限。独立检查及格式修复均只读正文、不转发私有 reasoning 或整个 wire receipt；对话展示、Snapshot/SSE 只提供过滤后的可展示思考文本，不返回原始协议回执。原 usage 可区分推理与非推理生成量，后者含工具协议，不能一律称为可见正文；缺失明细为未知，不篡改旧 usage。

HTTPX 的分块读超时之外另有整次请求 deadline。默认教学/规划正文参考 16,384 token / 300 秒，课时 12,000 / 600，题目作者/盲解 16,384 / 600，审核/关系 8,192 / 300，讲评 6,000 / 180；这些值不是推理硬限额。当前 Chat API 没有两个可独立设置的推理/正文 token 预算，仍受通道物理输出/窗口约束。有效截断回执留原 raw；没有完整回执的超时仍为 UNKNOWN。独立数据库连接周期续租；失去租约不应用迟到结果。不自动切换模型或供应商。

2026-11-06 按用户要求，本轮演示浏览器验收配置的窗口改为 512,000、通道最大输出改为 131,072，并显式设置 `Settings.model_output_budget_multiplier=4`。所有阶段的正文参考预留按四倍计算，仍与原任务的 `output_multiplier` 相乘并受通道实际输出上限约束；Tutor 首轮预留 65,536，0.5% 安全余量为 2,560，输入上限为 443,904。响应体字节预算沿原公式联动，阶段超时不变。该配置倍率默认仍为 1，不自动扩大其他用户 Profile、旧验收配置或已 prepared 的请求/policy；真实通道容量仍须按供应商能力单独确认。本次仅修改配置与预算解析，没有重启服务、改写数据库或发起供应商调用。

## 固定学习闭环

`JourneyWorkflow` 显式协调 Learning、Assessment 和 Execution：计划确认后才允许提交，代码和执行任务同事务持久化；Runner 使用独立控制凭据领取，任务保留发起会话摘要。领取和应用时检查当前会话、学习者和计划版本。

Runner 的 stdout/exit_code 只作为 execution 事实。assessment 按服务端预期值比较三组完整用例，learning 用 Inbox 去重应用本课进度；重复报告不重复应用。租约超时关闭为 error，不自动重跑；合法领取者的迟到报告独立保留但不推进进度。已执行代码不能因一次 HTTP 失联而自动再执行。

内部 `/internal/executions/*` 的认证与 learner Bearer 不可互换。测试、原始执行报告与 claim_token 不进入 snapshot/SSE。固定演示课 attempt 给状态/安全反馈；动态 Python attempt 可返回本人已提交的原程序，不返回私有盲解程序、隐藏测试或预期输出。

## 来源版本与基础复习

旧摘录入口 `KnowledgeWorkflow` 保存学习者提供的摘录和 HTTPS 链接，修订追加不可变版本并重置准入；该入口自身不请求链接。完整材料另经 `MaterialSourceWorkflow` 登记明确 URL/允许前缀、用途和期限，并使用原 source observation/上传/材料任务受控获取。Tutor 和题包冻结精确引用，派发/工具/落地前重验当前权限，已有供应商回执保留。

固定课时完成和动态节点正式证据创建各自唯一复习卡。0053 后的新回答使用固定 `fsrs==6.3.2` 与默认冷启动参数，保存完整调度器、前后状态、原算法日志和三档自评。旧固定间隔记录保留原含义，不回算历史；到期、展示/回答/取消、暂停/恢复、revision 和幂等均在 Learning 核验。记忆调度与正式能力证据独立。

2026-11-03 首批材料实现的迁移链为 0001–0026；0023 增加精确材料版本/块/权限及 learning 固定绑定，0024 增加用户模型配置、独立密文与版本、职责映射和显式连接测试，0025 增加私有材料需求及持久文本解析任务/阶段，0026 增加受控上传/原文引用、文件提取定位与保留期清理字段，并将文档命令中的重复正文改为内容身份。四份新迁移目前只用于 `leornian_test`，开发服务仍为 0022；该首批源码当时要求 0026，不表示旧运行实例已经升级。0022 增加教学工件、异步命令/不可变版本和冻结工具合同。0020 增加教学焦点、交付任务/不可变质量回执、调用 policy/manifest/finish_reason 和心跳事实；0021 保存 Gate/后继分批关系报告，不重放旧检查。0018 增加默认自动策略，0019 增加持久供给任务和版本关联、放开修订/生题步骤总次数约束，仅既有自动链补建任务。0014–0017 的供给、讲评、动态执行与后继事实继续保留；旧手动记录、旧报告、UNKNOWN 不静默重放或升级授权。已安装迁移不回改。

### 第四阶段材料与用户模型入口

2026-11-04 的后端切片及续接新增 0027—0031，仅在独立临时 `127.0.0.1:5451/leornian_test` 验证，未升级原开发库或 API/Worker/relay。readiness 要求 0031；不要将当前源码新增接口与原 8088 运行实例混为一谈。0030 增加自动消费者唯一身份，0031 增加闭合交互选择及来源。正常材料协议不再使用固定探针，逐页 OCR 追加派生版本，Embedding 分批保存，查询使用专用 Rerank；调用共用原 external_calls，UNKNOWN/取消/迟到和当前用途独立校验。

- `POST /v1/material-searches`：Idempotency-Key、demand_id/expected_demand_revision、query、显式 lexical/hybrid、可选 binding_id/expected_binding_revision，返回 202 任务。`GET /{id}`、`POST /{id}/cancel` 与 `GET /v1/material-selections/{id}` 读取/取消原任务及精确证据；GET 不发模型。混合检索不暗降级、不混向量空间；缺 Embedding 配置仍可显式使用已有词法投影。
- 当前全文为 `tsvector`，向量为本机 PostgreSQL 数组上的精确余弦扫描，融合后用专用重排；没有新增向量服务或 pgvector 部署。`lexical-evidence.v1` 的覆盖仅表示词项支持，语义质量明确未认证。教学/规划/课时请求自动登记精确消费者需求，语言版本未知则为空；规划节点及课时章节新增 material_citations，保存 binding/revision/purpose/ref。新用途另验许可、派生独立绑定；确认旧计划不改读文档 head。题库作者/六审已在 0032 续接，关系检查/讲评等其余角色的自动材料需求仍待接线。
- 同用户/目标的获准索引可被新需求复用，显式绑定保持固定；下一次混合查询发现缺少当前空间时自动分批重建向量，全部匹配后再查询/重排，不复解析/OCR/生题，不改变原材料任务或旧绑定。取消的迟到回执只保存事实，后续获准查询可复用完整回执；UNKNOWN 不重发。保存 Profile 和 GET 均不直接启动重建。
- OCR 按实际缺失页渲染，不整份 PDF 自动外发。渲染依赖锁在本项目 uv 环境，仍在原 60 秒/512 MB、无应用凭据的解析子进程执行；不安装全局 SDK。材料保留到期同时清理检索派生文本/向量和材料调用正文，非秘密调用状态/用量及身份事实保留。
- `POST /v1/conversations/{id}/learning-artifact-candidates` 只从已有已发布普通练习取得概念单选/Python IO 候选；learning_candidate_id 与 exact focus 的显式绑定保留。新 Run 可通过 list_learning_artifact_candidates 从当前精确节点返回的候选中选择，回复的 interaction 闭合为 none/composer/artifact+exact_handle+introduce_only，不开放考核或任意命令。独立检查后原子保存纯正文、Turn.learning_interaction、工件、CAS 与事件；旧工具集合/普通回复语义不升级。`GET .../learning-artifacts` 分页、`GET .../{artifact_id}` 只读，`POST .../{artifact_id}/actions` 使用严格 respond/run/cancel、client_action_id 和 expected_artifact_revision。
- 工件动作与旧 ItemSupply/PythonWorkflow 入口共用一次锁定及真实结果，GET/重连不执行、不评分；pending 讲评不抹去评分。尚未提供修改后多 Attempt、八类全部工件或正式 LibreChat 接线。0022 教学文档保留原合同。新事件为 tutor.learning_artifact_updated，复用同 actor 游标而非第二套事件流。
- 分层结果见根 README“第四阶段材料检索与工件后台”：真实库、离线模型、Python 工件真实 Docker、前端类型/测试分别记录，没有真实千问或原生/浏览器新增验收。受控联网获取、完整质量修复及真实比较仍待推进，三个工作包均不标整包完成。

2026-11-05 续接 0032：新题包同记录保存 `item-materials.v1` 的原规划/作者/审核精确引用，作者及六审用 `item-pack:<pack_id>:<role>` 自动登记需求；新题目和审核可沿原质量链保存 material_citations。作者/审核另验用途、固定到精确节点，不冒用规划授权。旧题包保持 NULL，不给旧 JSON 增加空字段，避免改写候选身份/曝光。readiness 现要求 0032，仍只在独立临时测试库应用，原库/8088 未升级。

题包作者和审核分别读取各自当前获准的固定材料，审核逐题引用 item_review 证据；盲解不接正文、需求、私有 gold/测试或其他审核。接受/发布资格检查实际供应的引用，已知负面结论不因引用格式修复变为批准。两类题目的资格执行/六审/自动修订/发布、练习和 Gate 仍由原 owner 处理；Gate 另验课时材料的新用途与范围，不把模型输出或普通练习当正式进度。

以下为 2026-11-03 基础入口及其原边界；正常材料处理/检索的新进展以上述 2026-11-04、2026-11-05 切片为准：

- `POST /v1/material-texts` 接收有明确使用声明的小型文本/Markdown，返回 parsed 文档版本；`GET /v1/documents/{id}/versions/{revision}` 与 `/blocks?purpose=&after=&limit=` 读取精确版本/块，GET 不触发获取、模型或索引。这个低阶同步入口不代替文件流程、OCR 或完整 RAG。
- `POST /v1/sources/{id}/material-compatibility` 只映射当前有效的旧摘录，保留原 `valid_until` 作为旧合同准入截止，并保留精确版本/撤销事实；不把旧七天窗口推定为来源真实许可，不批量延长。新文档的真实许可/保留与 next_check_at 分离；后者到期不影响合法固定版本。
- `POST /v1/material-bindings` 用幂等键和 expected_binding_revision 追加绑定版本；绑定可定位 goal 或当前确认的精确 plan/node。`GET /v1/material-bindings/{id}` 保留历史，`/blocks?expected_revision=&offset=&limit=` 复核当前 scope、精确引用及用途。review_due_at 不作为硬失效；后台复核任务与真实教学消费者仍待后续接线。
- `POST/GET /v1/material-demands` 及 `GET /{id}` 保存/分页读取本人的精确需求、语言框架版本和 required/optional facets；消费者引用由服务端生成。`POST /v1/material-demands/{id}/texts` 返回 202 文本解析任务，`GET /{id}/jobs` 和 `GET /v1/material-jobs/{id}` 只读状态；`POST /v1/material-jobs/{id}/cancel` 取消本根并围栏迟到结果。现有 relay/Worker 承接确定性解析，完成或取消清除临时输入；保留阶段历史，不增加模型调用。未闭合 Markdown 自动换精确纯文本策略，保留原文并等待检查；正常文本等待索引，不标 ready。
- `POST /v1/material-demands/{id}/uploads` 显式声明本人材料用途、真实期限、格式、字节数和内容身份，返回无宿主路径的引用；`PUT /v1/material-uploads/{id}/content` 以 `application/octet-stream` 发送原始字节；`POST /v1/material-demands/{id}/files` 使用该引用接收 202 解析任务。`GET /v1/material-uploads/{id}` 只读元信息，`GET .../content?purpose=` 经当前权限复核后下载附件，绝不以内联 HTML 执行。此处采用需求下的 `/files`，不另建同义 `material-imports` 入口。
- UTF-8 文本/Markdown 保留原字符，HTML 提取标题/正文/代码/表格且不联网，PDF 使用锁定的 pypdf 6.21.4 逐页提取。HTML/PDF span 标为 `extracted_text`，PDF 有真实 source_page、无假边界框。空/低质量页保存部分结果并等待专用 OCR 配置/正常调用实现，不假标 ready。限制为原文件 20 MB、提取文字 2 MB、10,000 块、200 页和有界解压；解析独立进程 60 秒/512 MB，不继承应用凭据。Windows 限制已执行；Linux 限制未实际验收。
- `LEORNIAN_MATERIAL_STORAGE_DIR` 指向本应用独立原文目录；原生默认当前 OS 用户数据目录，Compose 映射专用 `material-originals` 卷，不进入 Runner。备份需同时保护该目录及数据库；新卷尚未部署。未使用上传保留一天后清理，取消未消费原文会定向删除；已保存版本按实际 retain_until 清理原文、派生文本和章节路径，但保留元信息、摘要、绑定/阶段/失败历史。next_check_at/review_due_at 不触发清理。网页已接上传、任务恢复/历史/取消和受控附件下载并做隔离浏览器自动化；普通材料模型调用及索引链仍待接入，新后台尚未部署。
- `GET /v1/model-configuration` 聚合当前身份的安全配置；`GET/POST /v1/model-connections`、`PATCH/DELETE /v1/model-connections/{id}` 管连接/轮换/撤销；`GET/POST /v1/model-profiles`、`PATCH /v1/model-profiles/{id}` 管非秘密配置和角色映射。更新/删除检查 expected_revision，不返回密钥。验证错误移除输入回显。
- 产品默认 `LEORNIAN_MODEL_CONFIGURATION_MODE=user`。缺失 Profile、禁用或未同意对应材料外发时，教学交付等待配置，不回落到环境共享 key。只在开发者明确设置 `development` 时使用旧环境通道；旧 Run 的 legacy_development 范围保留，不追认为其他用户授权。
- 原生 Windows 使用 DPAPI。Linux 使用独立主密钥文件（`LEORNIAN_CREDENTIAL_MASTER_FILE`），必须属于本机进程用户且无组/其他用户访问位。`python -m leornian.platform.credentials --initialize` 首次生成，绝不覆盖已有 key；Compose 配方用独立 `model-keys` 卷初始化，再只读挂载给本机后台。数据库备份不含根 key；不要删除/重建该卷，丢失主密钥不能恢复已有密文。该配方未部署，不等于桌面安装旅程完成。
- `POST /v1/model-connections/{id}/tests` 以 allow_billable=true、精确连接 revision、profile_id 和幂等键接收显式固定样例测试，返回 202。聊天要求单个完整、无工具调用的 assistant 回复，正文为精确 `{"ok": true}` 的合法 JSON，`ok` 必须为布尔 true，数值 1 不通过；向量/排序用两条非教材文本检查完整索引及声明维度/返回范围；OCR 用自带 PNG 检查固定文字，使用官方支持的多模态兼容接口但不发送思考/工具参数。专用职责不套聊天生成 policy。`GET /v1/model-connection-tests` / `/{id}` 只读恢复状态。真实用量未知时保持 null，共享原 external_calls 回执/unknown 事实，失联不重发。一次真实 DeepSeek 聊天探针收到 HTTP 200 后，非法 JSON 被正确拒绝，原失败及用量见[根 README](../README.md#第四阶段浏览器与仓库模型联验2026-11-07)；本次 6 项定向离线回归通过。千问实际通道及材料质量仍待配置后验收，既有费用/地域许可保持。
- 新请求冻结 profile/connection/mapping/credential revision，事务外调用；派发前重新核验当前授权。新步骤可在明确承接后绑定新配置，已有 prepared/request/receipt 不覆盖，已 dispatching/unknown 的旧调用不会被换 key 重发。

### 模型设置与显式用途分配（2026-11-08）

模型配置采用“提供方连接 → 模型 Profile → 学习用途”三级结构。5180 设置分为“外观、模型配置、用途分配”，模型配置复用 CCS 前端组件，按“教学与路线规划 / 材料处理”分类，两类均支持预设和自定义。预设只需填写 API Key 并确认授权，也可先调整模型选择；已有连接直接提供模型编辑和合成样例测试。用途分配独立设置，保存、启用或修订模型均不自动发起测试。

- `GET /v1/model-configuration` 返回 `provider-presets.v1/v2/v3` 和非秘密预设目录，包含 Key 管理链接及模型容量。`POST /v1/model-presets/{deepseek|qwen}` 接收秘密 Key、明确 `allow_private_material=true`、当前映射修订号及幂等键；可选 `group=teaching|material` 限制模型与用途类别，`models` 须为该类别的非空、无重复子集，省略时配置该类别全部预设。未传 `group` 的旧请求保持原行为。整个操作原子提交，失败完整回滚，原键重放不轮换 Key、不重复建 Profile。v1 重新应用已有连接的 ID/revision 请求保持兼容。
- 教学类别支持 DeepSeek `deepseek-flash` 与北京千问 `qwen-plus`，明确启用后应用 13 项聊天职责；材料类别支持千问 `qwen3.5-ocr/text-embedding-v4/qwen3-rerank`，向量 1024 维，仅分配所选材料职责。未传类别的旧千问请求仍只补齐空缺教学用途。其他区域及自定义模型从对应类别的“自定义”进入；详细容量见 [S05.4](../docs/phase-4/spec.md#s054-deepseek-与千问快捷配置)。
- `POST /v1/model-providers/custom` 接收类别、启用的 `connection`、`profile` 参数、明确材料许可、映射修订号及幂等键，同事务保存连接、凭据引用、模型和对应类别映射。教学只接收 chat，材料只接收 OCR/Embedding/Rerank；任一冲突完整回滚，同键重放不重复创建或轮换凭据，不创建 Run。
- 已有连接的 Key 更新直接使用带 revision 的 `PATCH /v1/model-connections/{id}`，不重新应用预设、不改变模型或映射。类别初始化复用 `POST /v1/model-connections/{id}/use` 的 owner 操作，带连接 revision、选定 Profile 的 ID/revision 和映射修订号；复核本人、连接归属、启用/凭据、材料许可与操作类型后，同事务分配组内用途。该公开接口继续兼容旧客户端；当前界面的后续用途调整统一进入独立“用途分配”。

- 新客户端使用 `POST /v1/model-profiles?assign_roles=false` 或 `PATCH /v1/model-profiles/{id}?assign_roles=false`，仅保存模型及允许用途，不改当前用途映射。省略此参数时保留旧客户端的创建行为；幂等键不能跨两种模式混用。旧入口修订模型不抢回其他 Profile 已接管的用途。
- `PUT /v1/model-role-mappings/{role}` 接收 `{profile_id, expected_profile_revision, expected_mapping_revision}`。未配置映射使用 revision 0；服务端验证本人模型、允许用途、启用状态和凭据，再以两份修订号执行 CAS，陈旧版本返回 409。私有材料外发许可保持独立，不因分配用途自动打开。停用或失去用途资格的旧映射保留修订号，业务调用等待可用配置。
- `GET /v1/model-configuration` 的 `capabilities` 包含 `explicit-role-assignment.v1` 时支持上述独立分配。新界面遇到无此标记的旧服务会阻止模型保存和用途切换，提示先更新后台，不回落到旧自动映射行为。
- 显式测试仍使用 `/v1/model-connections/{id}/tests` 和原测试读取接口，要求启用本人连接/Profile、`allow_billable=true`、连接修订号及幂等键。新测试可使用尚未分配用途、尚未允许私有材料的 Profile，仅发送固定合成输入；冻结并复核原 session、Profile、连接和凭据版本。结果未知不重发，配置变化后的完整迟到回执入账但不应用。已保存的旧角色绑定测试保持原解释。
- 当前协议为 `chat_completions` 和 `dashscope`；聊天、OCR、Embedding、Rerank 使用各自 operation，Rerank 要求 DashScope。模型容量和输出预留使用实际通道值。已有连接可修订名称、启停和轮换密钥，更换协议、地址或区域需创建新连接；密钥不回显、不进入浏览器草稿或学习代码。

模型配置解耦、类别预设和自定义原子配置均复用 0024 的现有表，无新增模型迁移。本轮 76 项定向后端模型用例、23 项模型面板 DOM 用例及 14 项 connected 宿主/设置用例通过，严格 TypeScript 与 Ruff 通过。保存行为测试禁止访问供应商 HTTP，不使用真实 Key 或付费请求。部署及用户验收状态见[根 README](../README.md#模型设置精简与分类2026-11-08)，CCS 来源及构建许可见 [CCS-UPSTREAM.md](../apps/librechat/CCS-UPSTREAM.md)。

### 材料更新准备、通知与明确决定（2026-11-07）

0052 接入持久的更新准备、提案、站内通知及用户决定。独立复核完整接受 `semantic_change` 后，同事务唯一登记 preparation，原 Worker/relay 承接；新的 compare 命令复用历史已完成实质复核时也可登记同一唯一准备，不重发复核调用。GET 和原 compare 命令键回放保持原事实；等价或不确定结论不登记更新准备。准备仍以用户当前 binding revision 为基线，复核原 session、计划范围和材料用途。

- 自动准备复用原材料需求和正常 job：将明确候选版本送入原处理链，job 达到 ready 后，发起仅限该文档/版本的正常词法 search。新需求保留原必需 facets；selection 需覆盖每个候选精确范围及实际需要的 facets，变更旧范围也需被原绑定完整覆盖。缺配置、覆盖缺口、容量不足或 UNKNOWN 分别保留在原子任务与 preparation 状态中，不另起替代外调。
- `GET /v1/material-change-checks/{check_id}/preparation` 只读准备状态及 demand/job/search/offer 关联。已有合格 selection 时，也可用 `POST /v1/material-change-checks/{check_id}/offers`、幂等键及 `{expected_binding_revision, candidate_selection_id}` 登记提案；仍经过相同精确范围、就绪与权限检查。`GET /v1/material-update-offers/{offer_id}` 读取提案、变化摘要、候选引用、影响和可选决定。
- 提案按本人当前绑定 revision 和候选正文身份去重，每份提案只登记一条站内通知。`GET /v1/notifications?before=&limit=` 分页读取；`POST /v1/notifications/{id}/read` 仅记录已读。通知载荷包含提案入口、版本、影响计划/课时数量及迁移代价；通知已读不改变材料绑定。
- `POST /v1/material-update-offers/{offer_id}/decisions` 使用幂等键和 `{decision, expected_offer_revision, expected_binding_revision}`，决定为 `accept_update / decide_later / keep_current_for_track`。稍后或本轮保留旧版只写决定/通知状态；接受时重新检查精确候选、当前权限和实际依赖，在同一事务追加 successor binding revision、决定及事件。并发陈旧版本返回 409，相同命令恢复原结果。
- `GET /v1/material-update-offers/{offer_id}/decisions/{request_key}` 只读本人原决定回执，供丢失 HTTP 回应后核对；返回决定身份、原/后继 binding revision 和需重新准备的依赖，不重发接受命令，也不重新读取材料正文。原决定在后续材料权限变化后仍可按原键恢复。
- 影响分析按文档版本、块和范围相交，列出实际引用该材料的计划版本及课时。接受后，新消费可沿明确接受的 successor 链读取新精确引用；既有计划、课时、Attempt、成绩和证据保持原引用。决定的 `requires_reprepare` 返回受影响计划/课时身份，后续内容重备及路线变更仍经原生成/确认链，不因接受材料更新自动改写历史或确认路线。
- 真实保留截止经原材料清理入口取消相关 preparation、需求、job 与 search，清除派生 facets、查询及外部操作正文；提案/通知/决定的非正文身份、已发生调用与应用状态继续保留。撤权或基线变化阻止继续准备和接受，原 UNKNOWN 不重发。

首次明确 `accept_update` 还同事务唯一登记 0056 的重准备：规划和课时继续走原交付任务，保存同一请求/Run；新路线草案需用户明确确认后，才允许同 stable node 的后继课时。`GET /v1/material-update-decisions/{id}/repreparations` 只读各原任务和等待原因，GET/原接受键回放不补造任务，UNKNOWN 不发第二请求。历史路线、课时、Attempt 和证据保留。

0001—0058 已在所属 5459 测试库安装并冻结；2026-11-08 主库已备份并同步至 0058，常驻 API/Worker/relay 使用当前源码镜像。

### 程序 Gate、后继与恢复

- `POST /v2/packs/{id}/program-gate-requests` 复用原两题 Gate，GET 同路径 `/{key}` 读取原请求；新程序 Gate/后继仍需同环境、版本、来源和实际曝光检查。`POST /v2/gates/{id}/program-submissions` 整组一次提交，GET 同路径 `/{key}` 仅恢复真实原提交。
- `POST /v2/program-attempts/{id}/transfer-requests`、`POST /v2/transfers/{id}/program-submissions` 进入原精确后继和 Assessment；缺题使用 `POST /v2/program-attempts/{id}/supply-demands`，不直接造候选或通过证据。
- 概念/Python/program 共用只读 `GET /v1/transfer-requests/{key}`、`/v1/supply-requests/{key}`、`/v1/supply-demands/{id}`。开题/提交/取消丢失回应分别读 `/v1/transfers/{id}/opening`、`/submissions/{key}`、`/cancellation`；只有实际记录匹配才返回，其他为 404，不重发动作。
- 环境工具仅列当前范围或登记正常需求；安装同意、认领/隔离准备/验证/release、原作业运行与评分分开。Controller 持续复核原执行权限和 release，物理停止及定向清理由原执行所有者确认。

## 动态路线与课时合同

- `POST /v1/conversations/{id}/plan-requests`：text、expected_revision、幂等键；首版为 0。成功仅接受 run，规划结果通过结构化校验后才追加计划版本。
- `GET /v1/plans/{id}`、`GET /v1/plans/{id}/revisions?before=&limit=`：安全内容和可继续加载的版本页。`POST /confirm` 明确确认当前 exact latest，不根据模型文本自动激活。新草案不覆盖 active。
- `POST /v1/plans/{id}/lesson-requests`：expected_plan_revision、node_key、instruction 和幂等键。只允许当前确认版本及绑定来源仍 current 的节点。读取 `GET /v1/lessons/{id}` 不触发生成。
- 一对话的教学/规划/课时共用活跃回合互斥。`planner.v1`、`lesson.v1` 使用原有 AgentLoop/调用事实/取消/UNKNOWN/迟到承接，不创建第二套运行机制。
- 结构化角色无工具；按阶段预留输出，JSON object 仅提供格式模式。Learning 严格校验有序依赖/来源/版本，再走独立检查；已知失败可留痕修复，不创建不合格草案或正文。无整份八节点/五节上限；分片组装后仍需完整校验。物理请求超出窗口不能伪装成完整审查。
- 节点正文中的示例代码仅文本，来源引用是精确版本关系，不证明模型解释已独立核实；不写 assessment、Gate、mastery 或 completed。

## 动态概念题包合同

迁移 0018 后，新 `PackRequest` / `SupplyRequest` 默认 `automatic=true`。原需求提交后，`AutomaticSupply` 通过现有 relay 持续协调：有已知审核反馈则追加唯一修订，合格则调用原 `Packs.publish` 自动发布；无需客户端修订、补正或发布点击。只安排原 Agent Runtime 和 Execution/Runner 的工作，不创建第二个生成循环。

后台让位后自动承接 Python 六审。已知作者/盲解/审核输出可恢复；审核和关系报告可恢复的裁决必须保留，不靠格式补正改票。反复质量失败升级为重新设计决策，版本和补正不封顶。精确 Gate/transfer 报告以及已验证的未开题绑定失效事实驱动唯一后继，不复用不变文档。每步重查身份/计划/来源/起点；依赖失效转 waiting，取消转任务级 cancelled。公开 PackSummary 增加 supply_task_id / automation_status / automation_action / automation_reason，不返回会话摘要。

`POST /v1/packs/{任意历史版本}/cancel` 先提交全任务取消屏障，再清理所有后继的未完成 Run；不撤销已发布事实。`POST /automation-resume` 绑定当前本人授权、重验依赖后继续原等待任务，已取消任务不能恢复。普通任务合格发布即完成；缺题任务继续通过原 TransferWorkflow 准备关系检查，ready 才完成供给，但不自动开题、作答或记进度。完整迟到回执可在重验后自动承接，不重发旧 UNKNOWN。

0018 不自动接管旧候选；`automatic=false` 和以下手动端点保留兼容，旧真实质量阻断不重跑。下列“明确发布/修订”操作对新自动链由后台执行，不是要求学习者逐步确认。

- `POST /v1/plans/{id}/pack-requests`：expected_plan_revision/node_key/instruction/可选 predecessor_id；幂等键返回 pack_id/run_id。当前确认版本、精确来源和会话在各阶段派发/应用前重验。跨 actor 的同键互不影响，同 actor 重放不会增加角色调用。
- `item_bank.packs` 保存候选文档、精确来源和版本前驱；`stages` 每版每角色唯一。作者写文档后不可变。每次模型结果先存 Runtime raw receipt，再校验业务合同；模型不能提交公开 passed flag 授权发布。
- 作者生成 2/2/1 五题，服务器校验题位、选项、重复题面/答案选项集、精确来源。盲解是独立无工具上下文，仅 public question，无私有答案/解释、作者 transcript 或评审票；服务器确定性比对五题。
- 作者和六审输入本人确认计划、已保存正文、完成教学与实际题目/锁定反馈，提前处理教学到考核泄露；盲解不接收这些额外上下文。单选作者须排除语义等价的多个正确项并验证合法反例，不能用代码风格选答案；程序题明确结果与边界，并逐项核算绑定用例。
- 六角色各有独立上下文，逐题裁决及关系理由；任一未过都保留变化要求，仍收齐六审。缺一份/盲解错/来源失效不能 ready。当前只做完整新版重审，不冒称已实现增量复审或客观语义认证。
- `GET /v1/packs/{id}` 与 snapshot 只含摘要、覆盖状态及当前阶段 ID，不带候选内容或私有报告。`POST /publish` 明确发布到本地本人范围；不做生产/公共库发布。
- `GET /practice` 只返回两道练习并存首次曝光；`POST /answers` 接受 practice 或已明确分配/打开的 remediation 槽、选项和幂等键，由 assessment 比对并锁定。解释仅作答后公开；不发考核、不写概念完成。
- 需要修订时追加新候选，绑定唯一父版，不设固定修订版数上限；无内容变化不能当修订，同一父版不能分叉。旧报告/调用/UNKNOWN 不重写，新版盲解和六审独立执行。
- `POST /review-format-correction` 保留只处理已知审核理由超长的手动合同，但不按补正次数封顶。自动任务还可修复作者、盲解与关系输出的其他已知结构失败；可恢复的题位/关系 verdict 必须等于原 raw。不截断原始理由、不把无效旧 raw 当合法报告，也不重发 UNKNOWN。新调用失联仍为 UNKNOWN。

所有阶段使用原 AgentLoop/ModelGateway/调用仓储，无第二个生成/恢复引擎。最终发布和练习仍复核 current。同模型的独立上下文不等于不同模型的认识论独立性，也不是客观课程质量保证。

## 补救、曝光与概念 Gate

- `GET /v1/remediations/{id}/question` 仅本人已分配、当前来源/计划和合格已发布补救可读，追加真实曝光；`POST /answers` 锁定补救回执。补救难度不高于触发练习、不同题位；错误分配与错题回执同事务。再次错误写 transfer_required、不给原题重试/当前 Gate，没有自动伪造后继。
- `item_bank` 独占 append-only exposure_facts 与单调 exposure_heads：question 和 feedback 分开，重复阅读不增新事实。迁移按实际旧行回填，跨题包和已结束 Gate 的考核曝光保留，不按新 key/新生成请求重置。
- `POST /v1/packs/{id}/gate-requests` 携带 expected_plan_revision/幂等键，返回 GateSummary。当前本人同时最多一个未终结 Gate；前置为两道练习提交、必要补救或其新情境后继通过、同节点课时和精确版本先修进度。绑定来源、active revision、课时 ID、concept-gate.v1、完整有界曝光及保存的课时/教学上下文。
- 新 `gate_relation.v1` run 复用原 Runtime/Outbox/UNKNOWN。每实际 pair 必须有一份 distinct_decision 结论；缺项、重复、答案泄露或 uncertain 不开考。新大输入保存原文分片、逐批覆盖和调用绑定，再单独检查跨批组合风险；摘要不替换原文，不再按固定历史/课时/曝光/关系条数拒绝。Gate 可因明确负面提前阻断，未检查对显式记 uncertain 而非伪报已审；后继须继续比较其他候选。
- 批次包含额外全局真实 pair 时，完整保留其意见，按负面优先合并；额外通过不替代该 pair 的剩余原文批次/跨批检查。缺少本批必需 pair 或含全局之外的 pair 仍拒绝。部署修正可承接原完整回执，不另开 Gate 重审；取消后的失败 Run 不显示可承接。
- 相同 pack、exposure revision 和完整 context 的独立性失败不会因换 key 重审；返回 409 assessment_not_independent，不创建新 Gate/模型 run。同原 key 仍返回既存结果。上下文变化不会删除原失败报告。
- 原 `/v1/plans/{id}/pack-requests` 可带 predecessor_id + gate_feedback_id，只有当前本人、精确原题包的已知独立性失败才可修订已发布版本。服务端保存原报告/上下文/实际曝光，作者获得这些事实，盲解和六审仍是独立新上下文；旧题包不改写。唯一后继和不设固定修订版数上限继续生效，不能由客户端伪造报告或 passed flag。
- `GET /v1/concept-gates/{id}` 返回服务端 allowed_actions、blocked_reason；ready/preparing 无题目。`POST /start` 明确开考、记录两题曝光后给 public questions。期间 Tutor/新训练命令阻断，不能用它们取得本系统新帮助；不宣称可检测站外帮助。
- `POST /submissions` 必须同时给 assessment_1/2（各一次）与幂等键。评分只在 assessment；两个正确才传公开 ConceptCompletion 给 learning。结果、反馈曝光、证据、精确版本节点进度和公开事件同事务；重复返回同一结果，其他内容或新键不能重写答案。
- `POST /cancel` 同时停止本地关系 run 与 Gate；UNKNOWN 不重发，迟到 raw 仍保存。开考后的取消/失败仍保留曝光，不能再考同一包。当前源/课时/计划/教学或曝光发生变化，后续应用拒绝，历史读和已保存证据保留。
- `learning.concept_evidence` 只存本节点概念证据，`node_progress` 幂等投影；不自动换节点或替代执行能力。动态 Python Gate 另外写 execution_evidence，见下文。

## 新情境精确后继

- `POST /v1/remediations/{id}/transfer-requests` 带 expected_plan_revision/幂等键；仅 failed remediation，本人当前来源/计划。无合格已发布候选时 409 no_transfer_candidate，不创建模型 run 或占位分配。存在已打开/有效后继时不另抽题。
- item_bank 选择至多两份另一题包、同节点/版本/来源、未见未占用、D(n)/D(n-1) 的 practice；assessment 独占候选占用与后继事实。`TransferWorkflow` 是具名协调器，跨模块不读写私有表。
- `transfer_relation.v1` 无工具，每份候选必须与全部实际曝光逐对比较，完整覆盖才由服务端固定顺序选择首个全 distinct_decision 候选。检查过的候选不会通过新 key 反复重审。来源、active revision 和 exposure revision 在派发/应用/打开/评分前重新检查。
- `GET /v1/transfers/{id}` 返回摘要/allowed_actions，明确 `POST /open` 前无题；预留候选不可从普通 practice/answers 旁路。`POST /submissions` 只接 selected_key + 幂等键，不接客户端分数/候选 ID。评分、反馈曝光、结果和事件原子提交，不创建学习证据。`POST /cancel` 同时停止本地 run；迟到 raw 独立保留。
- passed transfer 仅满足原补救阻断，失败回执不改写。`concept-transfer.v2` 加入完整有界课时/教学历史比较与失效检查；旧 v1 活动检查不被静默授权继续。缺题与讲评按下面合同接续；普通练习的独立直接答案与 H1—H3 按序提示已接，完整辅助资格和自动教学推送仍未完成。
- `POST /v1/python-attempts/{id}/transfer-requests` 只接受本人已锁定、失败的 `training/remediation_1`；校验同类代码候选，策略为 `python-io-transfer.v1`，复用原关系角色。`TransferSummary` 的 kind 和两个互斥起点 FK 区分概念/代码，不能互相代替。
- 代码后继沿原 `/v1/transfers/{id}` 和 `/open`，`POST /execution-submissions` 只接受 code/幂等键，服务端固定候选槽。程序与队列/后继 submitted 同事务；`python_attempt` 返回本人程序及安全评分，不含隐藏用例。错误、取消、过期后原题锁定，普通训练接口不能旁路。
- 合法 Runner 回执在当前会话/计划/来源/实际曝光/教学上下文和租约仍有效时评分；评分、终态、反馈曝光、讲评入口和事件同事务。失效仍保留真实回执但不解除原补救阻断；后继通过本身不创建 learning 证据。

## 供给与讲评

- `POST /v1/remediations/{id}/supply-requests`：expected_plan_revision/instruction/幂等键。仅真实失败补救且没有合格未占用发布候选；返回 SupplyDemand，创建需求和原 author run 原子提交。一个 remediation 一条供给链。
- Python 起点使用 `POST /v1/python-attempts/{id}/supply-requests`，供给同样绑定唯一失败代码补救和 kind；同链修订保持 python_io，重新执行五份盲解、六审和明确发布后才可选择，不降级为概念题。
- `POST /v1/supply-demands/{id}/revisions`：expected_pack_revision/instruction/可选 transfer_feedback_id。服务端读取已知关系失败，不接客户端报告。仍同 demand、唯一父版、不设固定修订版数上限；需要完整重审和明确 publish。
- assessment 终态与 `tutor.evaluations` 原子衔接。`POST /v1/evaluations/{id}/run` 显式启动唯一 evaluation.v1，无工具、不抢占活跃用户回合；只拿已公开回执及本人代码。模型必须回显原正确与否，不能改分或写进度。
- 讲评进入真实教学历史，会使已有 transfer/Gate 的旧关系检查失效。供给需求、讲评和作答状态从一致性 snapshot 恢复，不靠客户端消息序列推导。

## 动态 Python 执行合同

- pack-requests 的 kind 可为 python_io（默认 choice）。仍五槽/精确来源/不设固定修订版数上限；公开 PythonQuestion 只有题面、starter 和一个样例，三个绑定用例及预期值留在服务端。
- public-only 盲解输出五份程序，复用 execution.jobs；五份全部回执后再六审。错误输出不能发布，超时/撤销不重跑。前台回合优先时 `POST /v1/packs/{id}/continue-review` 承接唯一后续阶段，不重做盲解。
- `GET /execution-practice` 与 `POST /execution-remediation` 明确开题并写曝光；`POST /execution-submissions` 只接 slot/code/幂等键，不能声明 passed。补救需 D(n)/D(n-1)，每题一次锁定。
- `POST /execution-gate-requests` 复用同一 Gate 准入和关系 run，策略 python-io-gate.v1。仍用 `/v1/concept-gates/{id}` 读取/开始/取消，兼容现有资源路径；`POST .../execution-submissions` 同时提交两份程序。
- Gate submitted 期间封锁教学/训练，单题中间成绩不公开。Runner 仅拿程序与输入，assessment 按绑定预期值比较；两题全过后原子写入终态、反馈、独立 execution_evidence 及事件。概念/执行证据不互相替代。
- `POST /v1/packs/{id}/cancel` 停止本地后续生成/资格检查/审核；不声称在途模型/容器已经停止。执行过期、取消和失效后的合法回执保留，不重派、不记通过。当前仅 Python 整数数组 → 整数，本地 Docker 不等于公开恶意代码生产沙箱。

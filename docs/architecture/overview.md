# Leornian：无 Sidecar 的架构基线

日期：2026-10-30。状态：架构方向已确认，首个学习目标通信切片已实现；本文仍包含后续设计，不能将全篇当作已实现或已验收系统。实际完成状态以根 README 为准。

2026-10-31 更新：原生 Tutor、动态路线版本/确认与节点正文、固定 Python 评测/Runner、版本化摘录和基础复习已接线。真实供应商尚未配置/验收。教学角色只用只读上下文工具；规划/课时角色不开放工具，仅输出由 Learning 验证的结构化内容。评分/进度仍由 assessment/learning 独占裁决，不提供 token 流或长工具等待，固定样例不是动态题包或正式 Gate。

## 0. 已确认边界与本轮范围

- 独立新仓库、独立新数据库。暂不迁移旧学习记录、运行状态和旧表。
- 旧仓库、旧库、历史回执和失败记录原样保留；新链通过不代表旧验收通过。
- 新系统直接去掉 Sidecar，不保留 Codex CLI/App Server、子进程监管、Codex 专用 worker、runtime_kind 双分支、兼容适配器或备用入口。
- 选择供应商的 Model Gateway 不是选择 Agent Runtime：只有一个 Leornian 原生运行时。
- 当前仓库已有可启动实现和独立本地数据库；具体交付状态以根 README 为准，旧项目不改动。
- 下面的接口名、表名、状态和目录是建议的合同形状，尚非冻结实现规格。

## 1. 技术与部署基线

采用模块化单体业务代码 + 独立后台进程 + 隔离执行服务，不先拆七个微服务。

| 部署单元 | 建议技术 | 职责 |
|---|---|---|
| Desktop | React / TypeScript / Tauri | 对话、课时、编辑器、练习和公开工件展示；不判定业务通过 |
| API | Python / FastAPI | 身份和所有权、HTTP 命令/查询、公开投影、SSE；不在请求内跑长模型循环 |
| Worker | Python / Celery | 调用业务用例，执行原生 Runtime、来源处理、供题、评分等后台任务 |
| Scheduler / Outbox relay | Worker 管理任务 / 定时唤醒 | 投递已提交事件、发现可继续的作业；不创造业务授权 |
| Runner | 独立可信控制进程 + Docker | 领取执行任务，启动受限容器，回传结果 |
| PostgreSQL | 一个新数据库，按模块分 schema | 业务事实、运行状态、租约、幂等键、事件和公开读模型的真值 |
| Redis | Celery broker / 非权威缓存 | 唤醒与缓存；丢失消息可由数据库协调扫描补发，不能丢失业务真值 |
| 文件/对象存储 | 初期本地存储，清晰存储接口 | 材料正文、代码文件、附件；访问仍由所属模块授权 |

暂不引入 Kafka、通用工作流平台、全量事件溯源或按业务模块拆独立数据库。首切片 Python、JavaScript 和 Rust 依赖已用各自锁文件固定；后续新增入口再收敛，不把旧版本照搬成新项目要求。

API、Worker 共享业务包但有各自 composition root。Runner 不复用 API 的业务权限；不可信容器与控制进程必须区分。

## 2. 业务模块及数据归属

| 模块 | 独占写入的业务数据 | 公开能力示例 | 不负责 |
|---|---|---|---|
| identity | learners、preferences、access grants、deletion requests | get_actor、check_scope、change_preferences | 教学决策、题目审核 |
| tutor | conversations、turns、teaching sessions、teaching intents | submit_turn、resume_teaching、request_hint | 直接写学习进度、发布题目 |
| learning | tracks、plan revisions、lessons、progress、mastery、review schedule | draft/confirm_plan、get_learning_context、apply_assessment_result | 自己启动容器、驱动模型 HTTP |
| knowledge | sources、source versions、materials、citations、admission/freshness records | retrieve、read_material、check_current_source | 发布题目、裁定学习者得分 |
| item_bank | question versions、generation jobs、review findings、packs、publication records | request_pack、get_public_item、publish_qualified_item | 写学习者掌握度、保存作答 |
| assessment | attempts、submissions、rubrics、evaluations、gate results | start_attempt、submit_answer、evaluate、get_gate_result | 修改课程计划、管理 Docker |
| execution | execution requests、execution leases、public/private result records | enqueue、claim、report_result、cancel | 认定掌握度、把 exit code 当 Gate 通过 |

工件不是包揽所有领域的总模块。Lesson、Exercise、Evaluation 等内容由对应模块拥有；delivery 层只把它们映射为版本化公开工件、快照和 SSE。

runtime 是技术执行内核，不是第八个业务总管。它拥有 runs、steps、external_calls、tool_invocations、leases；不拥有计划、题目或掌握度。

## 3. 依赖规则与内部结构

每个业务模块只需四个清晰区域，不为了分层而为每个对象再建一组空接口：

- contracts：命令、查询、事件、返回 DTO；可被其他模块依赖。
- application：用例、事务边界、工作流；实现公开 Facade。
- domain：业务状态、规则、纯计算；不依赖 FastAPI、Celery、供应商 SDK。
- infrastructure：仓储、SQL、外部接口适配；在启动装配处注入。

依赖方向为 transport/worker → application → domain。infrastructure 实现 application 所需端口，不能反向决定业务。

跨模块只能调用公开 Facade/Protocol，不能 import 对方私有类，不能直接读写对方仓储。bootstrap 是少数允许组合具体实现的位置。shared_kernel 只保留 ID、错误分类、时间与事件信封，不收纳所有领域模型。

跨模块读使用明确 Query/DTO。列表与聚合页面可以有订阅事件建立的读模型，但读模型的最终一致性必须对界面明确。它不能代替当前授权、当前发布资格或 Gate 裁决。

同一新库内，真正需要原子性的少数跨模块用例由命名的应用协调器组合公开接口，共享基础设施注入的事务范围；不通过外部 DTO 传裸连接，不让每个模块任意提交，不先引入分布式事务。

## 4. Tutor 与 Agent Runtime

Tutor 负责教学策略、教学上下文需求和本轮可用工具。Runtime 是所有 Agent 角色共用的机制，但不承接所有业务流程。

运行请求建议包含：run_id、actor_id、scope_id、role、input_ref、context_refs、allowed_tool_names、policy_version、deadline。

Runtime 内部职责：

1. ContextBuilder：向所属模块读取必要事实，构建受预算约束的上下文；摘要不成为业务真值。
2. AgentLoop：调用模型、校验结构化决策、继续、等待或结束；只运行一套协议。
3. ModelGateway：供应商协议、流式输出、usage 与错误归一化；不绑定业务状态机。
4. ToolRouter：按角色白名单和参数 schema 选定业务 Facade。工具内部再检查 actor/scope/current；模型参数不能声明授权。
5. RunRepository：保存运行/步骤/外部调用事实，处理当前租约、取消与结果承接。
6. EventProjector：从已记录的结果生成允许公开的消息与工件事件，不向前端透出隐藏答案和私有评审。

建议的教学工具：learning.get_context、learning.draft_plan、knowledge.retrieve、item_bank.request_pack、assessment.start_attempt、assessment.get_feedback、execution.submit。

不把 item_bank.publish 直接暴露为 Tutor 任意工具；发布由题库原用例检查质量、来源与版本条件。

题库应用层拥有 author → validation → review → publication 的确定流程。author/reviewer 可调用 Runtime 的不同角色；Tutor 不吞掉这条流程。知识更新同理由 knowledge 用例拥有。

## 5. 模块通信合同

### 5.1 同步查询与短命令

同进程函数调用 + 类型化 DTO，无内部 HTTP。示例：

- LearningFacade.get_context(actor, track_id) → LearningContext
- LearningFacade.confirm_plan(actor, plan_id, expected_revision, command_id) → ConfirmedPlan
- AssessmentFacade.submit_answer(actor, attempt_id, answer, command_id) → EvaluationAccepted

同步返回不包含 repository、Connection、ORM 实体、旧 lease 或进程内 capability。业务拒绝使用封闭错误码，例如 not_found、forbidden、stale_version、precondition_failed，而不是让跨模块 caller 捕获内部异常字符串。

### 5.2 长任务命令

返回 accepted/job_id，不同步等待整段模型或沙箱链：

- RequestPack → {status: accepted, job_id, progress_ref}
- GenerateLesson → {status: accepted, job_id}
- EvaluateSubmission → {status: accepted, job_id}

命令有 command_id / 幂等键。重投只能让消费者检查同一命令的既有状态，不能默认生成第二次外部调用。

### 5.3 已提交事件

事件信封建议字段：event_id、event_type、schema_version、aggregate_id、aggregate_version、occurred_at、correlation_id、causation_id、actor_scope、payload。

示例：PlanConfirmed、QuestionPublished、AssessmentCompleted、LessonPublished、SourceVersionRevoked。

业务记录与 Outbox 同事务。relay 只发布已提交行，收到 broker 确认后标记已投递；这个窗口允许重复。消费者把 Inbox 去重标记与自身业务更新放在同一事务，按 aggregate_version 拒绝或协调过时事件。

事件只携带必要 DATA/引用，不广播答案、原始 prompt、私有报告、授权 token。订阅者必须自己做访问和当前状态检查。

有跨模块后续动作时用明确的应用流程协调器；不靠一串无文档的订阅回调实现整个产品。

## 6. 一次 Tutor 请求如何走完

1. 客户端 POST /v1/conversations/{conversation_id}/turns，提供请求幂等键。
2. API 校验归属。Tutor 用例在一个事务中写 turn、创建 run/初始工作记录、写 Outbox。提交后返回 202 与 run_id。
3. relay 将 job_id 投递到 broker。Worker 取到消息后，再从数据库检查状态、当前租约和是否已处理；消息本身不是执行资格。
4. Worker 通过注册的 Tutor 用例构建教学 RoleSpec 与上下文，调用唯一原生 Runtime。
5. Runtime 保存本次 external_call 的准备记录；发送前将 dispatching 持久化，再经 ModelGateway 请求供应商。
6. 收到响应后先记录结果，再解析与路由工具。跨重启承接只读取已记录结果，重新取得当前业务权限；不重发同一次已知模型结果。
7. 短工具同步执行所属模块用例。长工具返回 job_id；运行进入 waiting_dependency 并释放 worker，依赖完成事件再次唤醒。
8. 学习/题库/评测等模块提交自己的结果与 Outbox；Runtime 只推进对话，不越权宣布课程或评测完成。
9. 当前公开事件按 actor 分配提交有序游标，统一通过 GET /v1/events 和快照交付；重连可用 Last-Event-ID，游标失效则回快照。没有另外实现 conversation 事件流。
10. 模型不再请求工具且当前教学回合后置条件成立，run 才成功结束；缺输入进入 waiting_input；未确认外部结果进入 blocked_unknown。

普通学习页面查询、计划确认、作答提交等不需要模型的 API，直接进入对应业务 Facade，不绕 AgentLoop。

## 7. 两层状态机，而不是一个巨大 status

### Run：这轮工作处于什么阶段

queued → running → succeeded / failed / cancelled

running → waiting_input → queued

running → waiting_dependency → queued

running → blocked_unknown

只有有事实支持的协调处理或明确业务处置，才能从 blocked_unknown 离开。不能靠时间到、进程不存在或重新入队自动解锁。

cancel_requested 单独保存；取消请求并不证明供应商停止。迟到结果可以记录为事实，但不能在取消后擅自执行新工具。

### ExternalCall：某次外部请求发生了什么

prepared → dispatching → result_recorded

dispatching → failed_known / unknown

prepared → not_sent / cancelled_before_dispatch

关键：dispatching 在真正发送之前提交，所以在此后崩溃即使可能尚未发出，也不能猜测未发出。只有可靠证据才能区分。供应商支持幂等时也要确认实际协议再采用，不能自己生成一个 key 就声称 exactly-once。

租约过期只允许新的 worker 协调工作，不自动许可重新发送 dispatching/unknown 调用。模型业务决策失败、供应商执行失败、权限拒绝和用户取消分别记录。

业务进度、资源/费用事实、当前授权分别属于自己的记录；UNKNOWN 不伪装成 0，权限失效不删除历史结果。

## 8. 数据库与迁移

新数据库按 identity / tutor / learning / knowledge / item_bank / assessment / execution / runtime / delivery 等 schema 划分。platform 可保存通用 outbox/inbox 基础设施；业务事件内容仍属于发布者。

每份数据只有一个写入所有者。真正完整的事务约束尽量位于一个模块内；需要最终一致性的跨域结果使用已提交事件。共享一个物理库不等于共享所有表的访问权限。

新库使用清楚的新基线与一条有序迁移链，不把旧数百编号的历史迁移搬进来。SQL 保留唯一性、外键、版本检查、防重复消费和必要安全约束；完整 Agent 流程不再同时复制到多组 Python 与 SQL 中。

用户学习状态和业务事实在 PostgreSQL；知识正文与附件可放文件/对象存储，数据库只保存版本、元信息与受控引用；向量/全文索引是可重建检索投影，不是唯一事实库。

## 9. Runner 边界

execution 模块登记待执行请求。独立 Runner 通过内部认证的 claim/report API 领取与报告；只有可信控制进程能接触容器运行接口。不可信学习代码默认无网络、无宿主凭据、无业务数据库权限，并受时长、内存、CPU、进程数和输出上限控制。

运行输出回到 execution，评测用例按 rubric/测试集裁决，学习模块消费 AssessmentCompleted 并验证用户、课程版本、能力绑定和当前条件后更新进度。exit_code=0、run succeeded、模型说完成均不是 Gate 通过。

首版不支持任意宿主终端和整个用户代码仓库编辑；那是额外的产品能力，不是替换 Sidecar 的必需步骤。

## 10. 目标目录结构（基础目录已建立，功能区域随实现创建）

```text
repo/
  apps/desktop/
  backend/
    src/leornian/
      entrypoints/api/
      entrypoints/worker/
      bootstrap/
      modules/
        identity/
        tutor/
        learning/
        knowledge/
        item_bank/
        assessment/
        execution/
      agent_runtime/
      delivery/
      platform/
      shared_kernel/
    tests/
      architecture/
      contracts/
      integration/
      journeys/
    migrations/
  services/runner/
  packages/api-contracts/
  infra/
  docs/
    architecture/
    product/
    decisions/
```

packages/api-contracts 是从服务端 schema 生成的前端类型与公开事件协议，不手工再维护一套相同模型。每个业务模块按 contracts/application/domain/infrastructure 组织；不要求每个模块都有空的四层目录。

## 11. 实施顺序与退出条件

阶段 A 的具体交付为“异步保存学习目标”：identity/learning、具名 GoalWorkflow 事务协调、platform jobs/outbox/inbox、delivery 快照/SSE，以及对应客户端。后续已增加 Tutor、Runtime、固定课时和 Runner。普通保存目标本身本可同步完成，首片特意采用确定性后台用例验证通信边界，不意味着所有短命令都必须过队列。

本切片的 job 只有 queued/succeeded/failed：保存目标、Inbox、终态和公开事件在同一短事务中提交，进程中途失败整体回滚；运行中没有外部调用。relay 对 queued 目标任务进行定时再唤醒，用以弥补 Redis 丢失消息。该策略不得自动用于后续 Agent Run；外部调用仍遵守第 7 节的独立事实与 UNKNOWN 合同。

HTTP 合同：`POST /v1/local-sessions`、`POST /v1/goals`、`GET /v1/jobs/{job_id}`、`GET /v1/snapshot`、`GET /v1/events`。学习者由 Bearer 会话解析，不接受请求体指定 actor；Worker 再次检查当前身份。事件游标按身份串行分配；快照与 cursor 来自同一个只读重复读事务。快照包含最近 100 个目标/任务、12 个事件；SSE 接受 after 或 Last-Event-ID，未来游标返回 409。

A. 建立可启动骨架、数据所有权和依赖检查，并跑通一条真实 HTTP → 持久作业 → 无外部 IO 的确定性业务操作 → SSE 链路。这个结果只是通信基础，不宣称 AI 产品可用。

B. Tutor/learning/assessment 跑通一条完整学习旅程，接入真实模型与隔离执行；逐项区分离线合同测试和真实验收。

C. 接知识来源、动态供题、六角色审核、完整题包及关系要求；不以早期单题切片冒充最终功能完成。是否调整原业务要求另作产品决定。

D. 补齐复习、主动教学、各类工件与更多语言执行；建立完整能力对照表，旧数据迁移仍不在当前批准范围。

当前 B 的确定性部分已用真实 Docker 正/负作答验证，模型部分仍只有离线传输 + 真实库测试。C 已建立学习者提供摘录的版本、有效期、确认使用、撤销及 Runtime 绑定；没有来源 GET、语义认证、动态供题或六审发布。D 已实现本课的固定间隔复习，不是 FSRS、主动教学或独立掌握度。

具体新增合同：`POST /v1/tracks`、`/{id}/confirm`、`/{id}/submissions`、`GET /v1/tracks/{id}/lesson`、`GET /v1/attempts/{id}`；Runner 使用独立认证的 `/internal/executions/claim` 与 `/{id}/report`。执行任务绑定发起会话，当前授权失效只阻止业务应用，不抹除实际回执；租约过期不重新执行。

来源通过 `/v1/goals/{id}/sources`、`/v1/sources/{id}/revisions|admit|revoke` 管理。每个回合绑定至多 3 份精确来源版本；每次 dispatch、工具和公开回复落地前重查当前版本/有效期，网络期间不持有数据库事务。来源失效不删除已记录外部结果。用户确认使用不是独立真实性审核；引用数据由版本化 Material DTO 提供，模型引用准确性尚未做真实验收。

复习使用 `/v1/reviews/{id}/responses|status`，只修改 learning 自有的日程与自评记录。首次本课完成时同事务去重创建，按 1/3/7 天安排；到期由服务端查询，不为时钟变化制造伪业务事件。

动态路线使用同一对话的 `POST /v1/conversations/{id}/plan-requests`，携带 expected_revision 与幂等键。`planner.v1` 和 `lesson.v1` 都复用唯一 Runtime，但无工具权限；一次有效内容结果即结束，不另建恢复/重试链。Gateway 对这两个角色使用 JSON object 模式（不是供应商 schema adherence 保证），Learning 严格校验后才落领域内容，失败保留原 receipt、不自动重发。

`learning.plans` 只保存 latest/active 指针，`plan_revisions` 和 confirmations 保留追加历史。新草案基于精确前驱，明确确认只允许当前 latest；来源重新查 current 后才改 active，草案产生本身不会激活或产生完成进度。读取 `/v1/plans/{id}` 和 `/revisions`，确认 `/confirm`；公开事件 `learning.dynamic_plan_drafted|confirmed` 与内容同事务。

节点正文通过 `POST /v1/plans/{id}/lesson-requests` 指定当前 confirmed revision/node 和讲解要求。它与普通教学/规划共享对话活跃回合互斥。请求绑定精确 node source refs，dispatch/应用前复核来源和 active revision；正文、来源快照和生成 run 持久关联，公开 `/v1/lessons/{id}` 不暴露 raw provider 数据。旧正文作为历史，不迁移到新版本，也不替代当前执行许可。正文不包含正式评分、完成状态或评测题包，示例代码不会自动运行。

验收至少覆盖：模块边界不可越过；重复消息无重复业务副作用；已记录外部结果可承接；发送后崩溃不自动重发；取消与迟到结果正确分离；当前来源失效正确阻止新动作；端到端用户结果真实落库并展示。

## 12. 明确不做

- 不保留 Sidecar 兼容层或多运行时切换。
- 不让 Tutor 成为所有后台任务的负责人。
- 不让每个模块独立部署后再用 HTTP 互相同步调用。
- 不因使用消息队列就声称模型 exactly-once。
- 不把所有通信变成事件，不把所有数据搬进 shared。
- 不以删除校验、忽略 UNKNOWN、复制旧历史数据来换取“链路通过”。

## 13. 参考依据

本文包含新设计和已标注的实施切片，并非所有目标能力均已实现。客户端技术选型参考旧 Aearn 桌面依赖，模块覆盖参考旧产品用户流程。设计时检查了 Celery Tasks 和 AWS Transactional Outbox 官方说明，当前通信切片实现了幂等与提交后投递；更广能力仍按对应退出条件验收。

官方资料：`https://docs.celeryq.dev/en/stable/userguide/tasks.html`；`https://docs.aws.amazon.com/prescriptive-guidance/latest/cloud-design-patterns/transactional-outbox.html`。

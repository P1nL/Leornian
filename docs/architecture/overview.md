# Leornian：无 Sidecar 的架构基线

日期：2026-10-30。状态：架构方向已确认，首个学习目标通信切片已实现；本文仍包含后续设计，不能将全篇当作已实现或已验收系统。实际完成状态以根 README 为准。

2026-11-01 更新：原生 Tutor、动态路线/正文、概念与 Python 执行题质量链、补救/后继/自动供给、正式 Gate、版本化摘录和基础复习已接线；真实模型已有分层验收，质量阻断保留。新增持久教学交付、精确上下文绑定、分阶段模型 policy、长请求心跳和大份关系上下文分批检查，详见本页末尾与根 README。评分/进度仍由 assessment/learning 独占裁决，固定样例不替代动态 Gate。

2026-11-02 设计补充：[第四阶段 PRD](../phase-4/prd.md)、[spec](../phase-4/spec.md)、[IMP](../phase-4/imp.md) 将完整教材 RAG、长周期/增量续检与用户决定更新、对话内交互工件、复习/主动教学及多语言验收纳入同一阶段。三份文件为待实施设计；0022 的工件仍是教学文档，不是目标 Learning Artifact。

2026-11-03 部署边界澄清：唯一产品模式是用户本机执行，不提供或预留远程 Runner。应用、本地后台、业务数据、隔离执行引擎和课程环境都在用户电脑；外部模型 API 仍按用户配置及用途许可调用。以下 API/Worker/“服务端”表示本机业务权威，不表示运营远程服务器。

## 0. 已确认边界与本轮范围

- 独立新仓库、独立新数据库。暂不迁移旧学习记录、运行状态和旧表。
- 旧仓库、旧库、历史回执和失败记录原样保留；新链通过不代表旧验收通过。
- 新系统直接去掉 Sidecar，不保留 Codex CLI/App Server、子进程监管、Codex 专用 worker、runtime_kind 双分支、兼容适配器或备用入口。
- 选择供应商的 Model Gateway 不是选择 Agent Runtime：只有一个 Leornian 原生运行时。
- 当前仓库已有可启动实现和独立本地数据库；具体交付状态以根 README 为准，旧项目不改动。
- 下面的接口名、表名、状态和目录是建议的合同形状，尚非冻结实现规格。

## 1. 技术与部署基线

采用模块化单体业务代码 + 独立后台进程 + 隔离执行服务，不先拆七个微服务。

下面各单元均部署在用户本机。独立进程/容器用于职责和权限隔离，不增加远程执行模式；正式桌面发行由应用管理本地后台，当前 Compose/终端命令仅为开发验收入口。

| 部署单元 | 建议技术 | 职责 |
|---|---|---|
| Desktop | React / TypeScript / Tauri | 对话、课时、编辑器、练习和公开工件展示；不判定业务通过 |
| API | Python / FastAPI | 身份和所有权、HTTP 命令/查询、公开投影、SSE；不在请求内跑长模型循环 |
| Worker | Python / Celery | 调用业务用例，执行原生 Runtime、来源处理、供题、评分等后台任务 |
| Scheduler / Outbox relay | Worker 管理任务 / 定时唤醒 | 投递已提交事件、发现可继续的作业；不创造业务授权 |
| Runner | 独立可信控制进程 + Docker | 领取执行任务，启动受限容器，回传结果 |
| PostgreSQL | 一个新数据库，按模块分 schema | 业务事实、运行状态、租约、幂等键、事件和公开读模型的真值 |
| Redis | Celery broker / 非权威缓存 | 唤醒与缓存；丢失消息可由数据库协调扫描补发，不能丢失业务真值 |
| 本机文件存储 | 清晰存储接口与受控目录 | 材料正文、代码文件、附件；访问仍由所属模块授权，不依赖托管对象存储 |

暂不引入 Kafka、通用工作流平台、全量事件溯源或按业务模块拆独立数据库。首切片 Python、JavaScript 和 Rust 依赖已用各自锁文件固定；后续新增入口再收敛，不把旧版本照搬成新项目要求。

API、Worker 共享业务包但有各自 composition root。Runner 不复用 API 的业务权限；不可信容器与控制进程必须区分。

### 1.1 应用、执行引擎与课程环境

| 层次 | 随产品提供的内容 | 获取/准备方式 |
|---|---|---|
| Leornian 应用及本地后台 | 界面、业务规则、学习记录、语言支持协议及可信环境配方 | 安装应用；后台组件由应用管理，不要求学习者手工启动 |
| 本机隔离执行引擎 | 受控启动、资源与网络约束、取消和清理入口 | 首次检测兼容性，缺少时明确引导；系统安装权限独立确认 |
| 课程环境包 | 精确运行时/编译器、锁定依赖、框架及测试服务配置 | 按路线需求一键准备，复用合格环境，不一次捆绑所有工具链 |

路线提出依赖需求不等于用户已授权安装。execution 拥有环境需求、授权、准备及资格；learning 引用需求/环境版本，Tutor 只可建议或展示，不能替用户同意。授权后自动下载、隔离构建、检查与发布；超范围依赖/权限再确认，同范围重建不重复弹窗。未同意时保留学习目标及可读材料，不开放未具备资格的实操。

环境安装不修改全局 Python/Node/JDK 等 SDK，不因探测到宿主工具链就将其作为评分环境。教材/项目模板、实际环境与 scorer 的资格分开，安装成功不等于课程交付。

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

第四阶段教学工具以 [spec](../phase-4/spec.md) 的 S14 为准：当前绑定/材料/合法候选读取和幂等学习活动需求可按角色开放；执行、开考、作答、评分不由 Tutor 工具代替用户或业务所有者。旧 Run 保持冻结权限，不能因新部署获得新增能力。

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

用户学习状态和业务事实在本机 PostgreSQL；知识正文与附件存本机受控文件目录，数据库保存版本、元信息与受控引用；向量/全文索引是可重建检索投影，不是唯一事实库，不引入远程存储依赖。

## 9. Runner 边界

execution 模块登记待执行请求。独立 Runner 通过内部认证的 claim/report API 领取与报告；只有可信控制进程能接触容器运行接口。不可信学习代码默认无网络、无宿主凭据、无业务数据库权限，并受时长、内存、CPU、进程数和输出上限控制。

所有执行均在用户本机；内部控制接口限定本机，不能配置成远程执行产品入口。依赖下载/环境构建先检查路线安装授权，运行不因此获得互联网权限；框架测试服务仅在任务私有范围内通信。取消后确认停止并定向清理本任务临时资源，不清理用户其他环境或学习记录。

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

D. 按第四阶段设计补齐教材 RAG、稳定版本/更新通知、对话内交互工件、复习/主动教学与更多语言执行；建立完整能力对照表，旧数据迁移仍不在当前批准范围。

当前 B/C 已接固定执行、概念/动态 Python Gate、两类补救/新情境后继、缺题供给和回执讲评。动态执行由真实库与实际 Docker 验证，概念题包有真实模型质量循环样例；原真实 Gate 质量阻断继续保留。讲评显式启动，不是后台主动教学；来源抓取/客观语义认证、完整跨题型关系、直接答案/提示规则与更多语言仍未完成。D 是固定间隔复习，不是 FSRS。

具体新增合同：`POST /v1/tracks`、`/{id}/confirm`、`/{id}/submissions`、`GET /v1/tracks/{id}/lesson`、`GET /v1/attempts/{id}`；Runner 使用独立认证的 `/internal/executions/claim` 与 `/{id}/report`。执行任务绑定发起会话，当前授权失效只阻止业务应用，不抹除实际回执；租约过期不重新执行。

来源通过 `/v1/goals/{id}/sources`、`/v1/sources/{id}/revisions|admit|revoke` 管理。目标范围读取本目标当前准入来源，精确节点读取其绑定来源，不按最近三份截断。每次 dispatch 和公开交付前重查当前版本/有效期，网络期间不持有数据库事务。来源失效不删除已记录外部结果。用户确认使用不是独立真实性审核；Material DTO 和质量报告也不提供客观真实性认证。

复习使用 `/v1/reviews/{id}/responses|status`，只修改 learning 自有的日程与自评记录。首次本课完成时同事务去重创建，按 1/3/7 天安排；到期由服务端查询，不为时钟变化制造伪业务事件。

动态路线使用同一对话的 `POST /v1/conversations/{id}/plan-requests`，携带 expected_revision 与幂等键。`planner.v1` 和 `lesson.v1` 复用唯一 Runtime，无工具权限；新请求由持久交付任务协调候选、完整结构校验、独立质量检查和已知失败修复。Gateway 的 JSON object 模式不保证业务 schema，Learning 仍独占计划/正文保存；原 receipt 保留，UNKNOWN 不重发。

`learning.plans` 只保存 latest/active 指针，`plan_revisions` 和 confirmations 保留追加历史。新草案基于精确前驱，明确确认只允许当前 latest；来源重新查 current 后才改 active，草案产生本身不会激活或产生完成进度。读取 `/v1/plans/{id}` 和 `/revisions`，确认 `/confirm`；公开事件 `learning.dynamic_plan_drafted|confirmed` 与内容同事务。

节点正文通过 `POST /v1/plans/{id}/lesson-requests` 指定当前 confirmed revision/node 和讲解要求。它与普通教学/规划共享对话活跃回合互斥。请求绑定精确 node source refs，dispatch/应用前复核来源和 active revision；正文、来源快照和生成 run 持久关联，公开 `/v1/lessons/{id}` 不暴露 raw provider 数据。旧正文作为历史，不迁移到新版本，也不替代当前执行许可。正文不包含正式评分、完成状态或评测题包，示例代码不会自动运行。

动态概念题包使用具名 `ItemSupply` 协调 learning 当前节点、knowledge 当前来源、item_bank 候选/阶段、assessment 作答和同一个 Runtime。`POST /v1/plans/{id}/pack-requests` 返回 pack_id/作者 run_id；每个角色独立 run/持久回执，前阶段应用与后阶段唤醒同事务，无额外内存队列或第二个模型循环。每版 2 practice/2 assessment/1 remediation，作者与六审还读取已保存课时、完成教学历史及实际公开题目/反馈，提前对照教学泄露；盲解仍只读公开题面、不继承这些上下文或作者历史。六审不读盲解答案/他人票。

item_bank 拥有五题文档、来源快照、父版本、八角色结果、本地发布与 question/feedback 曝光。严格校验后才接受作者文档；盲解匹配、六角色逐题/关系结论全过才 ready。用户明确 `/publish`；普通 `/practice` 只给两道练习，补救和考核走独立受控入口。私有答案、关系报告和六审全文不进 snapshot/SSE/Tutor，公开反馈只有对应作答锁定后可见。

修订追加唯一后继，不设固定版数上限；文档发生实际变化后新版独立盲解/完整六审，不改父票。已知输出失败可以继续补正，在原 run 新 step 留原 raw；可恢复的审核逐题与关系 verdict 必须保持，不因格式错误重审刷绿。原始失败不截断、不改写，未知调用不重发。过期/撤销/active plan 改变使任务等待当前依赖，不抹除既有回执。

该实现保留“来源/评分/关系/曝光各自有事实”的方向，但不冒称同模型角色等于客观认证，也不把精确去重和模型关系报告冒称完整跨题库独立性。迁移 0010 为独立新库增加上述表与允许角色，旧 0001–0009 不改写。用户授权复用旧密钥仅进入忽略本地配置，不继承旧运行许可/预算/UNKNOWN，不修改旧数据库。

迁移 0011 增加 assessment.remediations/concept_gates、item_bank.exposure_facts/heads、learning.concept_evidence/node_progress。旧曝光和错题按既存事实回填，不清零。assessment 绑定错题与同目标、不更难的已发布补救，补救和原题均一次提交；错误反馈同事务，补救不生成独立概念证据，再次失败明确需要新情境 transfer，不编造未审核后继。

具名 `ConceptGate` 只协调公开 Facade：learning 当前节点/精确课时/先修进度、item_bank 当前发布内容/全部有界已见题目反馈、assessment Gate 状态和 Runtime 关系角色。请求冻结来源/计划/课时/策略及保存课时和已完成教学上下文；`gate_relation.v1` 是无工具原生角色，必须覆盖完整 actual pair set（两个考核各对训练/已见内容/课程对话，再相互比较）。缺对、冲突、uncertain、泄露或当前性变化不开考。单调 exposure revision 和冻结教学上下文检查在派发/应用/开考/评分前执行，不缓存 current 授权。

`/v1/concept-gates/{id}` 只读投影服务端 allowed_actions；明确 `/start` 才事务记录两题曝光并公开。考核中拒绝本系统 Tutor 新请求和新训练，外部帮助不能被本地系统检测。`/submissions` 一次给两题，不接受调用者分数/independence；assessment 确定性判定两题正确才提供 ConceptCompletion DATA。learning 追加本节点 concept_choice 证据及精确版本进度；同一事务还写终态、实际 feedback 曝光和事件，失败全部回滚。失败不删除旧证据，不自动下一节点。

取消既停止 Gate 后续应用，也取消本地关系 run；原调用若 dispatching 则 UNKNOWN，迟到 receipt 仍保存。开考后取消/失败不恢复未见资格，换新幂等键不能原题重考；ready 阶段曝光/教学改变时旧报告保留但失去当前适用性。该切片不是公开生产测评、执行能力认证、全局 mastery 或站外反作弊。

迁移 0012 仅为 item_bank.packs 追加 gate_feedback_id/revision_feedback，不回改已安装迁移。assessment 拥有既存独立性失败事实；具名 ItemSupply 取得同本人、同原题包的 GateRevisionFeedback，再交 item_bank 追加唯一修订后继。新作者读原失败关系、原教学上下文和实际曝光，盲解/六审不读旧报告，最终仍需明确发布。旧发布、作答、Gate 和 Runtime raw 全部保留；不设固定修订版数上限。相同题包/曝光版本/完整上下文已有失败报告时，ConceptGate 拒绝换 key 重审，不新建 run；只有材料/上下文变化才重新检查。传递的是已提交质量数据，不是客户端分数或临时执行许可。

迁移 0013 增加 assessment.transfer_checks/transfer_candidates。TransferWorkflow 从 item_bank 取得至多两个完整审核发布、同节点/精确版本/来源、未见未占用且 D(n)/D(n-1) 的候选；原生关系角色不获未曝光 gold，assessment 核完整 pair set 后固定顺序选首个全过候选。预留不允许普通练习旁路，缺题无半份分配，不换 key 刷审。明确开题、一次评分/曝光/终态同事务；通过仅满足补救前置，不改旧失败、不写 learning 证据。

0014 的 SupplyWorkflow 把真实缺题事实交给 item_bank.supply_demands，一个失败补救关联一条持久供给链，绑定难度、曝光和教学上下文。它调用现有 Pack 角色/质量/发布机制，而非第二个生成引擎。发布后再走精确后继；已知 transfer 质量失败经 assessment Facade 返回数据，才能驱动已发布父版的唯一修订，仍不设固定修订版数上限。题包需求、已发布内容与已分配后继是三件不同事实。

tutor.evaluations 以不可变、已公开作答回执为唯一来源，与成绩同事务建立，显式创建唯一 evaluation.v1 run/turn。Tutor 只讲评，不改 assessment 或 learning；活跃用户回合优先。0016 的 concept-transfer.v2 把保存课时/完成教学历史也纳入逐对检查与当前性绑定，避免新讲评后继续使用旧关系许可；v1 历史不重写、不自动升格。其模型执行仍使用原 transfer_relation.v1 协议/Runtime。

0015 增补 kind=python_io 的五槽题包。作者绑定三组整数数组→整数用例；盲解上下文只含公开题面，五份程序通过原 execution.jobs / Docker Runner 实际执行，再由 assessment 比较预期值。item_bank 仅接收对应资格回执，不用模型自报 passed 决定发布；随后仍独立六审。用户前台回合存在时不抢占，可显式承接唯一审核阶段。

PythonWorkflow 复用原 Runner 租约/回执和原 ConceptGate 准入/曝光机制，没有第二套队列、评分许可或恢复循环。正式 Gate 两程序一次锁定，submitted 阶段不公开中间分数；两题全过且当前版本/授权仍有效后，终态、反馈曝光、learning.execution_evidence 与事件原子提交。该证据是 python-io-gate.v1，不更新概念 node_progress 或旧固定样例完成；取消/过期/迟到不记通过、不自动重跑。Runner 不拿预期输出、不写业务库，快照只返回本人提交代码，不返回资格盲解程序或隐藏测试。

0017 在原 transfer_checks/supply_demands 上增加 kind 和与概念起点互斥的 python_remediation_id FK；代码回执通过 python_result_id / python_attempts.transfer_id 双向绑定，不以无约束 source_id 获得执行许可。起点只能是失败的已锁定代码补救，候选只来自同类、完整资格与六审发布的未见程序题。python-io-transfer.v1 复用 transfer_relation.v1 和完整曝光/教学上下文；改版、撤销、已见或 UNKNOWN 不自动重审。

TransferWorkflow 明确开代码后继、一次提交；PythonWorkflow 在原 Execution 队列下分派 transfer purpose。回执处理按当前身份、后继、执行、作答顺序协调；过期路径保持后继 → execution 的相同锁顺序，每份执行独立事务。三组绑定用例全过才同事务记录评分、后继终态、实际反馈曝光、Tutor 讲评入口和事件；授权失效仍存 Runner 事实，不生成通过。原补救失败不改写、普通训练不能旁路重考；passed 仅满足原包 Gate 训练前置，仍须重新审查新增曝光并通过两题正式执行考核。缺题和有报告的修订复用原持久供给任务，不创建第二套生成或 Runner。

验收至少覆盖：模块边界不可越过；重复消息无重复业务副作用；已记录外部结果可承接；发送后崩溃不自动重发；取消与迟到结果正确分离；当前来源失效正确阻止新动作；端到端用户结果真实落库并展示。

### 自动生题承接

0018 为 item_bank.packs 增加 automatic、受保护会话摘要、停止原因和有界承接扫描。新需求默认自动；AutomaticSupply 是具名业务协调器，不是通用工作流平台：复用原身份/计划/来源、Packs 请求与发布、格式补正、Runtime wakeups 和 Runner。relay 根据持久事实承接已让位的六审、已知完整格式补正、唯一新版本或合格发布；并发受既有 actor 命令锁及唯一前驱约束。已知 Gate/transfer 失败报告由 assessment Facade 提供，不能由客户端或模型签发发布许可。

0019 将推进状态移至 item_bank.supply_tasks，版本保留自己的内容/报告。任务持有 root/head、当前会话摘要、running/waiting/completed/cancelled、恢复原因、下次协调时间、关联后继检查与修复策略。固定三版、一次补正和生题 run 三步限制移除；同问题再次出现时升级为重新设计决策，不以次数耗尽终结目标。仍使用原 relay/Runtime/Runner，非通用工作流引擎。

任务级取消先独立提交取消屏障，随后清理 Run，避免 task→run 与 Runtime run→task 的锁顺序反转。Runtime 派发/应用及 Runner 资格检查复核任务状态；已发出的生成工作只记录迟到事实。已明确打开的后继属于 assessment，不因停止生成而撤销本人已有作答许可。正常供给合格发布即完成，缺题供给继续自动准备精确后继关系检查；合格 ready 才完成供给，不自动打开/作答/记进度。完整迟到模型回执经原恢复合同重验后可承接，不重发原请求。授权/来源等待可恢复，已取消任务不能恢复；旧手动失败不自动接管。

### 教学合格交付与分阶段模型底座

0020 由 tutor 拥有 `delivery_tasks` 与不可变 `delivery_checks`，Runtime 只保存调用 policy/上下文清单/finish_reason 和续租事实。TeachingContext 向业务 Facade 查询目标、精确确认节点/课时及已公开评测回执；不同节点的“最新课时”不能替代当前绑定，未确认草案不是教学进度，审题流水不是教学历史。TeachingDelivery 是 teaching/planning/lesson 三种闭合业务的协调器，不是第二个 Runtime 或通用 workflow 平台。

候选 → 严格结构校验 → 独立四项质量检查 → 原子保存/公开。负面检查回作者诊断修复，重复问题升级重新设计；相同原输入的同一失败候选不重复审核。可恢复裁决在格式补正中冻结；needs_input、依赖/配置等待、blocked_unknown、取消与 superseded 分开持久化。不按任务总步骤/修订次数封顶；恢复仍重验当前权限，未知无回执不重发。

新请求使用 `stage-policy.v2`：阶段正文参考预留与推理/正文共享输出分开，不设应用侧独立推理硬限额。输入上限保留正文参考与估算余量；装入协议、完整必需事实、工具/必要推理回放和修复信息后，思考模式共享输出取通道最大输出与剩余窗口的较小值。当前 API 的 max_tokens 不是单独正文配额，不能宣称无限推理或两个预算可分别硬控。历史按完整回合（含工具链）选择并留清单；真实 usage 校准启发估算，不假称精确 tokenizer。v1 历史与已有 prepared 请求不重算。总 deadline 与独立连接心跳保留，失去租约只记录响应事实；调度量子、单次物理容量与完成条件仍是不同事实。

思考参数按阶段覆盖并随 policy 冻结。日常 Tutor 按 Run 冻结的集合使用上下文或教学工件工具，同一精确绑定，无 Runner/评分/进度权限；其他生成/质量角色仍无工具。思考模式使用工具自动选择，不发 required/命名强制选择；完整持久回传原 assistant content/reasoning_content/tool_calls/id/参数字符串与配对工具结果，同一工具链保留原模式及通道 policy。后续历史来自已接受教学作者的原工具链与最终推理，不取独立检查推理；旧非思考消息的无推理事实为 null。质量检查与公开投影移除推理原文。已记录工具回执可在恢复时消费一次，UNKNOWN 不重发、取消后迟到回执不运行工具。正文/推理用量依据原 usage 区分，缺失为未知。作者与独立六审仍裁决内容，思考不是发布许可或质量通过。

0021 为新 Gate/transfer 保存 `relation_parts`。大份教学历史和实际曝光不再被固定条数上限拒绝：逐对比较与原文分片完整留痕，最终另查跨批组合风险；摘要补充而不替代原文。Gate 可在明确负面时提前阻断，未审部分显式 uncertain；Transfer 继续覆盖其他候选。原报告、曝光与 UNKNOWN 不回改。物理容量不足或组合风险未解决时，不能伪报完整审查或通过。

批次报告可附带原全局范围内的其他 pair，意见完整留存、负面优先合并，但不能用额外通过代替尚未处理的原文批次；缺对、重复和全局无关 pair 仍拒绝。已有 `invalid_relation_batch` 阻断只在原完整未应用回执存在、绑定仍当前且未开考/未取消时，允许同 Gate/Run 恢复消费；不重发、不改原 raw，也不把独立性失败转成重新投票。

2026-11-01 的第三阶段收尾已完成两份新开发身份的真实自动供题 → 公开练习 → 全量关系检查 → 明确开考 → 概念/程序 Gate → 能力分离证据与公开投影。完整调用、用例、修订、耗时与验收限制见根 README；这不是人类掌握度或整套产品/原生窗口验收。

交付/对话历史和计划版本有 keyset 分页；snapshot 是近期公开窗口，不是历史存储上限。正式计划仍需学习者确认，课时保存不等于学习完成，教学或质量角色都不能写评分/掌握度。

### 当前教学文档工件与工具执行（0022）

0022 的静态工具注册表统一名字、参数合同、版本、副作用类型与可并行条件；网关不再内置单工具分支，bootstrap 路由到业务 Facade。新教学装配上下文读取、工件列表/分页读取、生成请求、修订请求；旧 Run 的默认合同仅保留历史上下文工具，不因部署增加权限。每次执行同时校验原请求、当前角色及当前会话/业务条件。已知参数/业务错误作为结构化工具结果承接，不改原回执；未知名称不执行。

当前 0022 文档工件由 tutor 拥有文档及追加版本，不是通用 artifacts 数据总库，也不是第四阶段对话内交互工件。工具接收短事务持久命令，业务键去重与调用记录去重分开；前台结束后 relay 为命令创建 artifact.v1 Run，复用原交付检查/修复链，不在工具事务调用模型。候选未通过不公开；接受与工件版本、公开教学正文、事件原子提交。入队/接受均检查 base revision；旧版可读，新 head 不被过期修订覆盖。全部已公开版本进入现有 Gate 教学上下文，阅读/生成不写掌握度。

独立工件只读在各自只读快照连接并行，同批相同读取复用；共同快照要求、当前上下文刷新和写命令保持串行。分页明确后续游标，不静默丢弃全文；工具 Schema/结果和思考协议全部计入实际请求预算。公开工件面板及工具摘要只展示安全数据，代码为转义文本。动态执行仍走原 execution/Runner，未向 Tutor 开放任意执行或宿主文件工具。

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

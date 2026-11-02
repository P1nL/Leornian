# 模块化业务后端

API 与 Worker 共用 `leornian` 业务包，通过各自入口和 composition root 装配。已接本地身份、异步目标、原生 Tutor、动态路线/节点正文、概念题包作者/盲解/六审/发布、固定评测、来源摘录、复习和公开快照/SSE。完整交付边界见根 README。

## 当前链路

1. `POST /v1/local-sessions` 创建本地开发身份及会话；数据库只保存令牌摘要。
2. `POST /v1/goals` 使用 Bearer 令牌和 `Idempotency-Key`；同键同内容返回原 job_id，不同内容返回 409。
3. `GoalWorkflow.submit` 在同一事务中写入 learning 请求、platform 任务/Outbox 和 delivery 接收事件，提交后返回 202。
4. 独立 relay 只投递已提交行；Worker 锁定当前任务、检查当前学习者是否有效，经 Learning Facade 保存目标。
5. Inbox、目标、任务终态与公开事件同事务提交。此动作是短事务、无外部 IO，因此不持久化没有实际用途的 running/租约状态。
6. `GET /v1/snapshot` 使用一致性快照返回当前身份最近 100 个目标、任务、最近 12 个事件及游标。
7. `GET /v1/events?after=N` 或 `Last-Event-ID: N` 按身份补读事件，再保持 SSE；无效游标返回 409，需重新取快照。游标按身份串行分配，不用全局自增序号猜提交顺序。

当前没有事件清理策略。SSE 轮询数据库，每次重新校验会话；公开事件不包含会话令牌或内部仓储对象。202 只代表已接受，不代表目标已保存。

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

测试 fixture 拒绝名称不是 `leornian_test` 的库，不清表；每项测试使用独立学习者。覆盖归属/幂等/原子回滚、会话/来源失效、Runtime UNKNOWN/取消/迟到结果、完整质量链、供给/讲评衔接、概念/执行评分和 Docker。最终测试数见根 README。未设 `LEORNIAN_TEST_DOCKER=1` 时 6 项真实 Docker 测试跳过；动态执行原旅程包含 27 个用例，新情境代码后继旅程包含原/新包盲解、错误训练/补救、后继和正式考核共 48 个用例。真实模型与 real broker/进程重启不由进程内测试冒充。

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

0022 的工具合同在 `agent_runtime/tools.py` 静态注册，Schema 和严格 JSON 参数验证共源；`bootstrap/tools.py` 分派业务 Facade。新教学冻结五个工具及合同版本，旧 Run 保留旧集合；原请求声明与当前许可交集仍有效。参数错误返回字段级结构化结果，冲突需重读，未知名称不执行。工具调用幂等与业务命令键分开；工件任务按原会话排队，前台结束后由 relay 启动同一原生 Runtime 的 artifact.v1，再独立检查，不通过则继续修复。

教学工件由 tutor 拥有不可变版本，不吞并路线/题目/评分模块。修订入队和接受时复核 expected_revision；完整已公开版本进入原教学历史/Gate 上下文。读取按精确版本和章节分页；独立只读可分连接并行，同批重复读取复用，不共享连接并发或跨回合缓存权限。模型网络不在工具数据库事务里；任务接收不等于交付，取消前台也取消尚未启动的子任务。公开 tools 端点只含安全执行摘要，无原参数/推理/raw。

`agent_runtime/policies.py` 的新 `stage-policy.v2` 分开正文参考预留与思考模式共享输出；不设应用侧独立推理硬限额。输入上限为通道输入能力与“窗口减正文参考预留减余量”的较小值；装入完整实际请求后，共享 `max_tokens=min(通道最大输出,窗口−完整校准输入估算−余量)`。正文参考预留不再把推理截断在 8,192 等阶段值。非思考输出仍使用阶段预留。必需内容原子保留，协议、工具、必要 reasoning 回放和修复信息全部计入；可选历史按完整回合装入（含工具链），保存选取清单。启发估算不假称 tokenizer；真实 usage 校准后续请求。旧 v1 请求和已有 prepared 的请求/policy 不重算、不改写。

`LEORNIAN_MODEL_STAGE_THINKING` 是可选 JSON 阶段覆盖；阶段必须已注册、值只能为 enabled/disabled，空值沿用全局配置。当前开发通道为教学/规划/课时/独立检查/讲评、生题作者/盲解/六审和 Gate/后继关系启用思考。思考工具采用自动选择，不发送 required/命名强制选择，也不静默关闭思考。原助手 content/reasoning_content/tool_calls 与工具结果完整持久承接；同一工具链冻结原模式及通道预算，下一回合的历史单元含原工具链和已接受作者推理，不混入质量检查推理。非思考旧消息无推理时为 null，供应商明确报告空推理/0 也合法，不伪造。工具必须同时属于当前角色白名单与原冻结请求声明，旧无工具调用不因部署获得权限。独立检查及格式修复均只读正文、不转发私有 reasoning 或整个 wire receipt；对话展示、Snapshot/SSE 无原始推理。原 usage 可区分推理与非推理生成量，后者含工具协议，不能一律称为可见正文；缺失明细为未知，不篡改旧 usage。

HTTPX 的分块读超时之外另有整次请求 deadline。默认教学/规划正文参考 16,384 token / 300 秒，课时 12,000 / 600，题目作者/盲解 16,384 / 600，审核/关系 8,192 / 300，讲评 6,000 / 180；这些值不是推理硬限额。当前 Chat API 没有两个可独立设置的推理/正文 token 预算，仍受通道物理输出/窗口约束。有效截断回执留原 raw；没有完整回执的超时仍为 UNKNOWN。独立数据库连接周期续租；失去租约不应用迟到结果。不自动切换模型或供应商。

## 固定学习闭环

`JourneyWorkflow` 显式协调 Learning、Assessment 和 Execution：计划确认后才允许提交，代码和执行任务同事务持久化；Runner 使用独立控制凭据领取，任务保留发起会话摘要。领取和应用时检查当前会话、学习者和计划版本。

Runner 的 stdout/exit_code 只作为 execution 事实。assessment 按服务端预期值比较三组完整用例，learning 用 Inbox 去重应用本课进度；重复报告不重复应用。租约超时关闭为 error，不自动重跑；合法领取者的迟到报告独立保留但不推进进度。已执行代码不能因一次 HTTP 失联而自动再执行。

内部 `/internal/executions/*` 的认证与 learner Bearer 不可互换。测试、原始执行报告与 claim_token 不进入 snapshot/SSE。固定演示课 attempt 给状态/安全反馈；动态 Python attempt 可返回本人已提交的原程序，不返回私有盲解程序、隐藏测试或预期输出。

## 来源版本与基础复习

知识模块只保存学习者提供的摘录和 HTTPS 链接；不请求链接、不将人工确认描述为独立认证。`KnowledgeWorkflow` 协调当前身份和目标归属，修订追加不可变版本并重置准入。Tutor 在第一次上下文绑定精确版本，dispatch/工具/回复落地前重新检查有效性；变更、撤销或过期会阻止新动作，已有供应商回执不删。

首次本课完成在同事务创建唯一复习卡。到期由服务器当前时间计算，自评只写 learning 自有记录和下次日期，固定 1/3/7 天；暂停/恢复、revision、幂等键和归属全部在服务端核验。该能力不是 FSRS、正式评测或掌握度。

迁移链为 0001–0022；0022 增加教学工件、异步命令/不可变版本和冻结工具合同。0020 增加教学焦点、交付任务/不可变质量回执、调用 policy/manifest/finish_reason 和心跳事实；0021 保存 Gate/后继分批关系报告，不重放旧检查。0018 增加默认自动策略，0019 增加持久供给任务和版本关联、放开修订/生题步骤总次数约束，仅既有自动链补建任务。0014–0017 的供给、讲评、动态执行与后继事实继续保留；旧手动记录、旧报告、UNKNOWN 不静默重放或升级授权。已安装迁移不回改。

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
- passed transfer 仅满足原补救阻断，失败回执不改写。`concept-transfer.v2` 加入完整有界课时/教学历史比较与失效检查；旧 v1 活动检查不被静默授权继续。缺题与讲评按下面合同接续，直接答案/Hint 与自动教学推送仍未做。
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

# 模块化业务后端

API 与 Worker 共用 `leornian` 业务包，通过各自入口和 composition root 装配。已接本地身份、异步目标、原生 Tutor、动态路线/节点正文、固定评测、来源摘录、复习和公开快照/SSE。完整交付边界见根 README。

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
$env:LEORNIAN_TEST_DOCKER = '1' # 启用三项真实 Docker 隔离测试；镜像须已在本机
uv run ruff check src tests
uv run pytest -q
```

测试 fixture 拒绝名称不是 `leornian_test` 的库，不清表；每项测试使用独立学习者。当前 102 项测试覆盖输入与归属、同键冲突、并发重复提交/消费、事务失败回滚、会话撤销、broker 失败恢复、Runtime UNKNOWN/取消/迟到结果、动态路线和节点正文、评分、来源失效、复习及 Docker 隔离。未设 `LEORNIAN_TEST_DOCKER=1` 时 3 项真实 Docker 测试跳过。真实模型和 real broker/进程重启不由进程内测试冒充。

## 目标区域

- `src/leornian/entrypoints`：HTTP/SSE 与后台任务入口。
- `src/leornian/bootstrap`：少数允许组合具体实现的位置。
- `src/leornian/modules`：identity、learning、tutor、knowledge、item_bank、assessment、execution；其中 item_bank 当前仅人工入门样例。
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
- 原有 snapshot 增加 conversations/turns/runs，原有按身份有序 SSE 增加 tutor 公开事件。

Worker 和 relay 只唤醒协调；运行租约与数据库调用事实才决定能否执行。外部网络请求期间不持有业务事务。HTTPX 禁用重试与重定向，raw response 在解析/工具执行前落库；4xx 明确回执记为已知拒绝，5xx/失联保持 unknown。usage 无回执时是未知，而不是零。

教学角色实现只读 `learning_get_context`、最近六轮已完成历史、64KB 请求字节界限、单次 1200 输出 token 请求限额、三模型步骤和两次工具上限；规划/课时角色无工具，单请求输出 2400 token。字节界限不是精确 token 计算。模型供应商需支持该协议和参数。工具读取目标、已确认课时、最多三份当前准入摘录和最近三次作答反馈；生成正文只有在当前 active revision 且来源完全属于本轮绑定时才进入上下文。工具权限在业务 Facade 内重新检查。

## 固定学习闭环

`JourneyWorkflow` 显式协调 Learning、Assessment 和 Execution：计划确认后才允许提交，代码和执行任务同事务持久化；Runner 使用独立控制凭据领取，任务保留发起会话摘要。领取和应用时检查当前会话、学习者和计划版本。

Runner 的 stdout/exit_code 只作为 execution 事实。assessment 按服务端预期值比较三组完整用例，learning 用 Inbox 去重应用本课进度；重复报告不重复应用。租约超时关闭为 error，不自动重跑；合法领取者的迟到报告独立保留但不推进进度。已执行代码不能因一次 HTTP 失联而自动再执行。

内部 `/internal/executions/*` 的认证与 learner Bearer 不可互换。私有测试输入、回执、claim_token 和原始代码不进入 snapshot/SSE；公开 lesson 只给题面和 starter，attempt 只给状态与安全反馈。

## 来源版本与基础复习

知识模块只保存学习者提供的摘录和 HTTPS 链接；不请求链接、不将人工确认描述为独立认证。`KnowledgeWorkflow` 协调当前身份和目标归属，修订追加不可变版本并重置准入。Tutor 在第一次上下文绑定精确版本，dispatch/工具/回复落地前重新检查有效性；变更、撤销或过期会阻止新动作，已有供应商回执不删。

首次本课完成在同事务创建唯一复习卡。到期由服务器当前时间计算，自评只写 learning 自有记录和下次日期，固定 1/3/7 天；暂停/恢复、revision、幂等键和归属全部在服务端核验。该能力不是 FSRS、正式评测或掌握度。

迁移链目前为 0001–0009。已安装迁移不回改；0007 增补会话执行绑定，0008 增加动态计划，0009 增加来源绑定的节点正文。旧 queued 执行缺原会话时不能由新字段获得执行许可。

## 动态路线与课时合同

- `POST /v1/conversations/{id}/plan-requests`：text、expected_revision、幂等键；首版为 0。成功仅接受 run，规划结果通过结构化校验后才追加计划版本。
- `GET /v1/plans/{id}`、`GET /v1/plans/{id}/revisions`：安全内容与最近 20 份版本。`POST /confirm` 明确确认当前 exact latest，不根据模型文本自动激活。新草案不覆盖 active。
- `POST /v1/plans/{id}/lesson-requests`：expected_plan_revision、node_key、instruction 和幂等键。只允许当前确认版本及绑定来源仍 current 的节点。读取 `GET /v1/lessons/{id}` 不触发生成。
- 一对话的教学/规划/课时共用活跃回合互斥。`planner.v1`、`lesson.v1` 使用原有 AgentLoop/调用事实/取消/UNKNOWN/迟到承接，不创建第二套运行机制。
- 结构化角色无工具、请求 2400 输出 token；JSON object 仅提供格式模式，不保证业务 schema。Pydantic 严格校验、节点依赖/来源和当前版本由 Learning 裁决；不合法保留 receipt，不自动请求模型修复。
- 节点正文中的示例代码仅文本，来源引用是精确版本关系，不证明模型解释已独立核实；不写 assessment、Gate、mastery 或 completed。

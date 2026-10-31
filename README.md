# Leornian

面向编程学习的 AI 教学系统：模块化业务后端、原生 Agent Runtime 与隔离代码执行服务。

## 当前状态

2026-10-31：通信、原生 Tutor、动态路线版本/确认、来源绑定的节点课时、固定 Python 评测闭环和基础复习已接线。动态生成目前完成的是实现与离线传输集成，真实供应商尚未配置。

| 范围 | 当前交付 | 验收边界 |
|---|---|---|
| 通信基础 | HTTP、持久任务、Outbox、Celery、快照/SSE | 已有真实容器和重启验收 |
| Tutor / Runtime | 受限工具、多轮上下文、取消、UNKNOWN、迟到回执承接 | 自有模拟传输 + 真实 PostgreSQL；未调用真实供应商 |
| 学习闭环 | 计划确认、单课正文、代码提交、隔离执行、服务端评分和进度 | 固定 Python 样例；真实 Docker 正/负作答验证 |
| 知识来源 | 学习者提供摘录、不可变版本、明确准入/撤销、有效期、Tutor 版本绑定 | 数据库/HTTP TestClient 集成；不抓取或独立认证网页 |
| 复习 | 本课完成后安排、到期回想、自评、暂停/恢复 | 固定 1/3/7 天间隔；非 FSRS、非掌握度评测 |
| 动态路线 | 原生规划角色、结构化节点/依赖/引用、追加版本、明确确认 | 自有模拟传输 + 真实库；旧确认版本不会被新草案覆盖 |
| 节点课时 | 按已确认路线和精确来源生成正文、示例代码、回想问题 | 自有模拟传输 + 真实库；不执行示例、不创建评测/进度 |

已提供 FastAPI API、Celery Worker、Outbox relay、独立开发数据库与 Redis、React 客户端和最小 Tauri 壳；Python、JavaScript 和 Rust 依赖分别由 uv.lock、pnpm-lock.yaml、Cargo.lock 锁定。

这不是完整教学系统。动态路线和课时已有接线，但真实模型质量尚未验收；动态供题、独立盲解、六角色审核、完整题包、正式 Gate/掌握度、主动教学与更多语言执行尚未实现。固定人工课时不是这些能力的替代。没有复制旧数据、旧凭据或 Sidecar。当前没有配置 Leornian 独立供应商，真实模型端到端验收未执行。Tauri 目前通过编译检查，未进行原生窗口或安装包验收。

## 本地启动

前置条件：Docker Desktop（Linux 容器）、Python 3.12、uv、Node.js 24、pnpm 10；仅运行网页不需要 Rust。

在仓库根目录用 PowerShell 7 执行：

```powershell
# 首次启动：只在 .env 不存在时生成独立的本地数据库密码。
if (-not (Test-Path -LiteralPath .env)) {
    $password = [Convert]::ToHexString([Security.Cryptography.RandomNumberGenerator]::GetBytes(24))
    [IO.File]::WriteAllText((Join-Path $PWD .env), "LEORNIAN_POSTGRES_PASSWORD=$password`n")
}
uv sync --directory backend --frozen
pnpm install --frozen-lockfile
docker compose --env-file .env -f infra/compose.yaml build api
docker compose --env-file .env -f infra/compose.yaml up -d --no-build api worker relay
pnpm dev
```

打开 [本地学习空间](http://127.0.0.1:5178/)。数据库与 Redis 分别绑定本机 5448、6388 端口，API 绑定 8088；不使用旧 Aearn 的 5432/6379。Compose 使用独立网络和数据卷。网络默认子网为 `10.83.44.0/24`，若冲突可在 `.env` 设置 `LEORNIAN_SUBNET`。

代码提交还需要在另一终端启动 [独立 Runner](services/runner/README.md)，先为本项目生成 `LEORNIAN_RUNNER_TOKEN` 并重新启动 API。没有 Runner 时作答会真实保持 queued，不会使用宿主 Python 执行或生成成功结果。

停止后台服务用 `docker compose --env-file .env -f infra/compose.yaml stop`；保留数据卷，不运行删除卷的命令。

本地身份是匿名开发会话，不是正式注册登录。会话令牌有效期七天、由浏览器本地保存；清除浏览器数据会丢失这个身份的入口，但不会删除数据库中的目标。不要把当前开发服务暴露到公网。

## 已确认的方向

- 使用独立新数据库，暂不迁移旧 Aearn 的学习记录、运行状态和旧表结构。
- 旧仓库、旧库与历史记录保留；新项目不会修改它们。
- 直接移除 Sidecar，不引入 Codex 适配器、双运行时切换或备用入口。
- Tutor 管教学策略，唯一原生 Agent Runtime 管模型与工具循环，业务模块管自己的规则和数据。
- 模块间使用公开接口、持久任务和已提交事件；API 与 Worker 共用业务代码。
- 不可信代码由独立 Runner 隔离执行。

## 阅读入口

1. [产品范围](docs/product/scope.md)
2. [完整架构基线](docs/architecture/overview.md)
3. [关键决策记录](docs/decisions/0001-project-baseline.md)
4. [开发约束](AGENTS.md)

完整文档索引见 [docs/README.md](docs/README.md)。

## 仓库结构

```text
apps/desktop/           React 学习空间与最小 Tauri 壳
backend/                API、Worker 与模块化业务代码
  src/leornian/         业务模块、原生 Runtime、delivery、基础设施与具名协调器
  tests/                合同、模块边界、真实数据库集成测试
  migrations/           独立新库的迁移链
services/runner/        可信宿主控制进程；学习代码只进入受限 Docker 容器
packages/api-contracts/ OpenAPI 与生成的 TypeScript 类型
infra/                  本地 Compose 配置
docs/                   产品、架构与决策
```

功能区域随实际切片建立，不预建其他模块的空业务类或通用编排平台。

## 首个实现切片

已打通：HTTP 请求 → 持久任务/Outbox → Redis → Celery → 确定性保存目标 → 已提交公开事件/SSE。API 和 Worker 使用同一个具名事务协调器装配模块；业务模块只写自己拥有的数据。

目标内容、任务、事件和幂等事实都在 PostgreSQL。Redis 唤醒消息即使丢失，relay 也会重新唤醒未完成的目标保存任务；消费去重和业务结果在同一事务中提交。这种自动重投仅适用于当前无外部 IO 的目标保存动作，不代表未来模型调用可以自动重发。

## 验证

```powershell
pnpm contracts
pnpm check
pnpm test
pnpm build
uv run --directory backend ruff check src tests
uv run --directory backend pytest -q
cargo check --locked --manifest-path apps/desktop/src-tauri/Cargo.toml
```

默认 pytest 在未指定测试库时跳过数据库集成测试。完整真实数据库测试的准备及命令见 [后端说明](backend/README.md)。

本轮实测：设置独立测试库和 `LEORNIAN_TEST_DOCKER=1` 后，102 项后端测试通过，包含真实 PostgreSQL 集成及 3 项真实 Docker 隔离检查；前端 5 项测试（SSE 解码及路线/正文安全静态渲染）、类型检查和构建通过。静态渲染不等于浏览器交互验收。测试客户端有一条上游 Starlette/httpx 弃用警告。

真实 HTTP → Celery → 计划确认 → Runner → 评测 → 进度验收中，`print(0)` 只通过 1/3 用例、不推进进度；正确程序通过 3/3 后本课完成。后续来源与复习通过真实库 + HTTP TestClient 验证；另一次补充来源 live HTTP 命令被工具策略拒绝、未执行，不能当作验收通过。最终发起会话撤销检查由数据库集成测试覆盖。

前一切片已验证 Last-Event-ID 补读和 API/PostgreSQL/Worker 重启恢复，Tauri `cargo check` 及浏览器目标提交/刷新恢复也已通过。本轮未改 Rust；未重新验收原生窗口。内置浏览器截图接口此前失败，本轮未取得新增页面的桌面/手机视觉验收，也没有换浏览器绕过限制。

## 最小 Tutor 与原生 Runtime

在已保存目标下提交问题，Tutor 负责教学角色、必要历史和学习上下文，AgentLoop 负责模型/工具循环。唯一工具 `learning_get_context` 是只读工具，不接受 actor_id 或 goal_id；实际读取目标、已确认课时、最近评测反馈和当前准入来源，由当前会话与对话归属决定。没有终端、代码执行、题目发布或评分工具。

真实模型需要在本项目 `.env` 独立设置 `LEORNIAN_MODEL_BASE_URL`、`LEORNIAN_MODEL_NAME`、`LEORNIAN_MODEL_API_KEY`，并明确设置 `LEORNIAN_MODEL_ENABLED=true`；详见 `.env.example`。供应商须支持 Chat Completions、教学工具调用以及路线/课时所需 JSON object 模式，不意味着所有 OpenAI 模型或任意供应商兼容。没有默认模型、测试回复回退或旧 Aearn 凭据继承。启用意味着将所选目标、路线/节点、课时、评测反馈、准入摘录和必要历史发送到该供应商。

运行状态与 external_calls 分开。发送前提交 dispatching；失联、超时和 5xx 不自动重发。迟到结果可以记录，但 UNKNOWN 只能在已有完整回执时明确承接；取消不证明上游已停止，也不会抹去回执/usage。每轮最多 3 个模型步骤、2 个只读工具调用，首版返回完整回复事件，不提供逐 token 展示。

来源进入回合时绑定精确版本。发送新请求、工具执行和回复落地前重新检查当前有效性；来源变更、撤销或过期时停止后续动作。已经返回的模型回执仍保存，不因准入失效抹去调用事实。模拟传输只存在于测试，不作为运行模式。

## 动态路线与节点课时

在 Tutor 中选择“生成或修订学习路线”，填写基础、时间投入与要求。规划角色复用同一个 AgentLoop/ModelGateway/external_calls，不开放工具，返回结构化 JSON；Learning 校验 1–8 个有序节点、唯一 key、先修依赖、时长和精确来源引用。JSON mode 不保证业务正确性，服务端仍严格校验，不合格结果保留回执但不创建草案，也不自动修复重发。

每次成功生成追加一份不可变版本。新草案不覆盖当前确认版本；只有“确认使用版本 N”才变更 active pointer，旧版本保留。引用来源确认时再次检查当前性。无材料时路线必须明确写出未验证假设，不把常识规划冒充来源支持；没有来源的节点不能生成正式保存的课时正文。

确认后选择一个有当前来源的节点，填写讲解要求，生成带引用的正文、只读示例代码和回想问题。正文绑定精确计划版本/节点/来源。重复幂等请求沿用原 run；改版后旧正文保留为历史，不更新到新节点。来源或当前确认路线在派发/应用前失效时停止新动作，迟到回执仍保存。点击阅读、展开引用或刷新不会调用模型。

后续教学只读上下文会附上当前确认路线中最近一份正文，且仅在它的全部来源都属于本轮当前绑定材料时提供；来源失效后不把旧正文当作当前教学依据。

这里的“课时正文已生成”不等于课程审核、练习生成、代码执行、Gate 或学习完成。动态路线尚未接正式评测题包；下面的固定 Python 样例仍是独立演示链路，不能用它给任意动态节点记进度。

## 固定课时、评测与复习

当前仅有 `python-even-sum.v1`：从标准输入读取 JSON 整数数组、输出偶数和。计划确认后才能读课时和提交，作答带幂等键。Runner 只拿代码和输入；预期输出留在 assessment。三组完整用例全部符合才能完成本课，exit_code=0 本身不代表通过，也不产生正式 Gate/掌握度。

Runner 控制进程使用独立凭据；任务绑定发起会话，领取和应用结果时重新核验。容器无网络、无挂载、只读根目录、非 root，并限制时间、CPU、内存、进程数和输出。租约过期会把作答关闭为 error，不自动重跑；合法领取者的迟到回执保留，但不更新进度。这是本地开发隔离边界，不是可公开接收任意恶意代码的生产沙箱。

本课第一次完成后创建一张复习卡，第二天到期。自评只调整下次日期，记录保留并可暂停/恢复；它不改动题目评分或生成独立掌握度。页面用服务端快照刷新到期状态，不在客户端自行判定课程完成。

## 后续推进

下一条主线是动态题目供给：已确认路线/当前来源 → 原生角色生题 → 确定性校验 → 独立盲解 → 六角色审核 → 修订/重新审核 → 完整题包和受控发布。保留每目标 2 练习/2 考核/1 补救、关系与曝光边界等原产品要求，不能从正文生成或固定样例推导它们已完成。之后补正式 Gate、主动教学和多语言执行。真实模型接入需本项目独立配置；不会从旧 Aearn 读取密钥或继承执行许可。

本地仓库尚未关联远程，也没有初始提交。

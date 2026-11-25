# 隔离 Runner

`controller.py` 是可信本地控制进程：通过内部认证的 claim/report API 领取任务，启动受限 Docker 容器并回传。课程支持多语言文本输入项目、网页检查、SQL 查询和任务内 HTTP 服务。镜像、构建命令和挂载由应用维护，学习者提交公开合同允许的源文件、入口和输入。

可信控制进程与不可信学习代码分开：学习代码不能取得宿主凭据或业务库权限。执行受网络、文件系统、CPU、内存、进程数、时长和输出限制。

Runner 不裁定 Gate 或掌握度。结果先由 execution 记录，再由 assessment 裁定，最后由 learning 检查条件并应用进度。

自由教学示例可以打开交互终端。控制器声明 `example_terminal` 后才领取这种任务：沿用路线的隔离环境，保持程序的输入管道打开，实时回传输出，并把学员每次回车提交的一行交给同一进程。点击停止会结束程序并清理容器；程序运行上限为 180 秒。已发布题目继续按原用例批量执行。

## 实现分工

`controller.py` 保留启动、单实例锁、环境准备协调和任务分派。`runner_runtime/api_client.py` 处理本机认证请求、授权回查与回报确认；`sandbox.py` 负责资源限制、取消、工作区、容器和卷清理；`stdio.py`、`web.py`、`sql.py`、`service.py` 分别负责命令行、网页、查询和 HTTP 执行。它们在同一进程运行，共用原队列和回执。环境准备继续由 execution 的 `EnvironmentInstaller` 与课程包准备器负责。

## 教学中的执行环境

基础语言工具链由应用负责管理，Tutor 不应要求学习者安装宿主 Python、Node、JDK、配置 PATH 或打开系统终端。旧路线中的“环境搭建与第一个程序”在教学时介绍应用内沙盒与一个最小程序；路线版本保持原记录。第三方依赖和框架仍通过应用内明确授权，由可信控制器准备到专用隔离环境。

教学上下文默认携带 `execution_environments`，与 `get_execution_environments` 使用同一份本人、路线及版本过滤。模型据此读取引擎、需求和 `usable_environments`；配方存在、镜像已缓存、Docker 就绪或历史运行成功都不自动代表当前课程 release 可用。缺少准备时走原应用内需求和决定流程，示例代码只在原执行所有者返回回执后才可称为已运行。

## 三层状态与按需环境

应用分别显示本机应用后台、Docker 隔离引擎和本人课程环境状态。发行包自带专用 Python、Node、API/教学 Worker/资料 Worker/Relay 镜像与控制器；`bootstrap.local_services` 只管理本应用固定 Compose 项目和进程，后台就绪包含两个 Worker。教学队列为 `leornian.foreground`，资料队列为 `leornian.materials,leornian`，与开发入口路由一致。引擎缺失时打开 Docker 官方安装说明，引擎已安装但未运行时提供明确启动动作；系统组件的权限与重启由用户在安装器中决定。

完整路线汇总受控环境清单，确认时由应用自动登记并准备基础工具链；TypeScript 类型包、SQL 驱动及浏览器依赖随各自工具链管理。额外课程框架在路线确认按钮气泡中统一询问，用户可明确选择同时安装或仅确认路线；专用隔离位置由应用管理，技术详情默认折叠。需求绑定本人、此电脑及可选的已确认路线版本；额外安装决定同时检查需求与决定 revision。获准后控制器领取准备任务，依次下载、隔离构建、实际烟测，最后发布冻结实际版本和镜像 ID 的环境 release。新 `project_stdio` / `web_project` 题包在请求、阶段执行、Runner 派发和回报应用时都要求本人当前精确 release；旧 Python / SQL 的公开合同保留原可选字段与执行语义。

受控配方覆盖 Python 标准库 / Flask、JavaScript、TypeScript、Java、Go、C#、HTML/CSS、SQLite、PostgreSQL 和 MySQL。Rust / C++ 处于评估。依赖只进入应用专用镜像与卷，不修改全局 SDK。基础自动准备记录 `managed_base` 依据，不伪造用户同意；同一路线仅版本变化且依赖范围相同，可引用原同意恢复，不重复询问。扩大依赖锁、来源或权限后重新确认；撤销或暂停的环境不会自动恢复。已知下载失败在原授权和引擎就绪条件下恢复准备；租约结果未知保留 `blocked_unknown`，由用户明确选择原范围重建。

路线的 `environment_dependencies` 声明语言、用途、包名与精确版本，以及 `stdio`、JS/TS 的 `vite` 或服务项目的 `http` 构建方式。应用从声明生成额外环境需求，在原路线按钮中一次请求同意；Runner 分别通过 pip、npm、Maven、Go modules 或 NuGet 准备专用镜像并核对实际版本。包管理器、公开来源、构建命令与配置由应用维护，模型和学习者不能提交安装命令、镜像或私有源凭据。Python 准备使用 wheel，npm 不运行包安装脚本；需要源码构建的原生或系统依赖仍须具备明确的受支持准备方式。

Vite 环境可包含 Vue、VueUse、Naive UI 等路线选择的包，使用原 `web-check.v1` 接收 JS/TS 源文件。Runner 先构建，再由隔离 Chromium 检查产物；构建失败保留独立编译诊断且不执行浏览器用例。检查资源通过浏览器本地映射提供，无公共端口或运行时互联网。

## HTTP 项目与可写测试数据库

课程声明使用 `build="http"`，可选 `database="sqlite"|"postgresql"|"mysql"`；标准库服务允许 `dependencies=[]`。准备后的 `project-http.v1` release 固定语言运行时、依赖和所需测试镜像。服务代码使用既有语言入口，监听 `127.0.0.1:8080`，端口也通过 `PORT` 提供。

每个 `HttpScenario` 包含最多六个按顺序执行的本地 HTTP 请求，可为声明的类型化表结构提供初始数据。一次程序最多三个场景；每个场景新建服务和数据库，场景内保留写入，场景间重新初始化。可信请求客户端只共享该服务的回环网络，不映射宿主端口；服务和数据库不访问互联网。SQLite 提供 `LEORNIAN_DATABASE_PATH`，PostgreSQL/MySQL 提供 `DATABASE_URL` 及 `DB_HOST/DB_PORT/DB_NAME/DB_USER/DB_PASSWORD`，通过共享的任务回环网络连接。SQLite 使用 64 MiB 的临时内存卷，服务数据库数据也有独立容量限制。数据库只用于本任务。

执行分为编译、启动服务、等待就绪、请求观察和资源回收。编译失败独立回报；正常、失败、取消与授权变化均进入同一清理路径。HTTP 任务租约为 600 秒，原其他程序与 Python 租约保持。应用日志和请求输出均有大小限制。

`http_project` 题包沿原作者、公开盲解、实际资格、六审和发布流程处理。Runner 只接请求、数据和代码，回报 `http-scenario-result.v1` 的实际状态码与正文；`http-response.v1` 由 Assessment 比较状态码和响应序列，JSON 正文按解析后的结构比较，其他正文精确比较。普通界面只显示公开场景的实际响应。跨任务常驻托管、外部联网服务和专用原生构建仍需另行支持。

HTTP 工作台要求读者声明 `learning_programs.v2`；旧 `learning_programs.v1` 继续读取原 SQL/项目。环境的 `learner_network=none` 表示不接入外部网络，HTTP 通信限制在本任务回环域内。容器删除命令超时后核对实际状态，只有确认容器已不存在才继续领取；不能确认停止时保留原清理错误并停止控制器。

上述路线气泡与自动基座策略已在 2026-11-13 通过 103 项后端测试（含独立 PostgreSQL 集成）、33 项 DOM、5 项 Node、合同/类型/Ruff 与 connected 构建，并加载至主后台及随包资源。两套控制器、8088/8122 API 与 5180/5202 前端均已运行；视觉验证按要求停止。既有 11 个已发布环境记录保持，当前部署情况见根 README。

需求、决定、重建都有 actor + key 的持久原回执。提交结果未知时，客户端只查询对应 GET 回执，不生成新 key 重发；读取旧决定不会重新激活已撤销授权。撤销或当前业务资格失效后停止继续使用，原准备、执行和迟到报告保留。协议与权限要求见 [spec](../../docs/phase-4/spec.md) S13。

2026-11-07 的隔离工程验证记录了以下实际版本。最终用户成品仍由本人允许后的准备任务重新验证并发布 release，执行只消费该 release 的精确镜像：

| 配方 | 实际工具链 |
| --- | --- |
| Python 标准库 / Flask | Python 3.12.14；Flask 3.1.2 及固定依赖锁 |
| JavaScript / TypeScript | Node 22.16.0；TypeScript 5.9.3 |
| Java | JDK 25.0.5.0 |
| Go | Go 1.26.10 |
| C# | .NET SDK 10.0.403；运行时 10.0.14 |
| SQLite / PostgreSQL / MySQL | 3.46.1 / 15.19 / 8.0.46 |
| HTML/CSS | Chromium headless shell 156.0.8078.4；Playwright 1.64.1 |

HTML/CSS 使用只含 Chromium headless shell 的可信窄配方，来源为官方 Python 镜像、PyPI、Playwright CDN 与 Debian 软件源。配方只准备当前声明的浏览器；公开依赖下载不自动开通付费服务。

2026-11-13 已在主实例按用户明确授权完成上述 11 个环境的正常准备与 release 发布，版本与表中一致；Java 的完整观测版本为 25.0.5.0.2，release 规范版本为 25.0.5.0。每个环境都由原控制器实际隔离烟测，Flask、浏览器和 SQL 客户端依赖锁已核对，TypeScript 另核对 `@types/node` 22.19.0 / `undici-types` 6.21.0。九个基础环境为本人此设备作用域，SQLite 与 Flask 绑定原 Python 确认路线 revision 3；原教学节点可用环境为 11。安装记录与具体版本见[语言基座与依赖安装](../../README.md#语言基座与依赖安装2026-11-13)。

## 开发控制器启动

完成下方首次凭据配置及 `uv sync --directory backend --frozen` 后，日常直接在仓库根目录执行 `pwsh -File .\start.ps1`，即可依次启动后台、隐藏的控制器和 5180 基准网页。控制器日志在 `.runtime/development-runner/`。已有控制器占用单实例锁时，脚本核对项目 Python 和绝对控制器入口，匹配则自动复用并继续启动网页。`Ctrl+C` 只通过原停止信号等待本次新启动的控制器清理，复用的控制器和后台保留运行；若超过 20 秒仍未退出，先保留后台并检查日志。无法核对旧手动进程或只调网页时使用 `-SkipRunner`。

从仓库根目录用 PowerShell 7 执行。首次为本项目追加独立凭据，不读取旧 Aearn 设置：

```powershell
$path = Join-Path $PWD '.env'
$lines = [IO.File]::ReadAllLines($path)
if (-not ($lines | Where-Object { $_.StartsWith('LEORNIAN_RUNNER_TOKEN=') })) {
    $token = [Convert]::ToHexString([Security.Cryptography.RandomNumberGenerator]::GetBytes(32))
    [IO.File]::AppendAllText($path, "`nLEORNIAN_RUNNER_TOKEN=$token`n")
}
# API 必须重新加载凭据。先按根 README 构建镜像，再启动服务。
docker compose --env-file .env -f infra/compose.yaml up -d --no-build api worker relay
$line = [IO.File]::ReadAllLines($path) | Where-Object { $_.StartsWith('LEORNIAN_RUNNER_TOKEN=') }
$env:LEORNIAN_RUNNER_TOKEN = $line.Substring($line.IndexOf('=') + 1)
& .\backend\.venv\Scripts\python.exe (Join-Path $PWD 'services/runner/controller.py')
```

此进程持续运行，关闭终端、Ctrl+C 或应用停止信号会结束领取并清理当前隔离任务。旧 Python 路径默认使用已存在的 `python:3.12-slim`；控制器可先启动并观测引擎，再按已允许需求准备新课程环境。学习者执行固定 `--pull=never`。可信操作者可设置 `LEORNIAN_RUNNER_IMAGE` 和 loopback `LEORNIAN_RUNNER_API`，学习者 DTO 不接受这些参数。

控制器只允许本机 Docker 命名管道或 Unix 套接字，拒绝 SSH / TCP 端点。读取有效 `DOCKER_CONTEXT` 或 `DOCKER_HOST` 后，将该端点固定在本进程环境中；后续执行和定向清理保持同一引擎，不修改用户全局 context 或代理。Docker 需要使用 Linux 容器模式。

原生资源用 `apps/desktop/package-native.py` 打包。脚本复制白名单 Python 3.12、现有 Node、`native-server.mjs`、控制器与配方，导出应用镜像，生成专用 Compose 和 Tauri 资源配置。先将 `$backendImage` 设为本次最终后端构建 tag，再从仓库根目录执行：

```powershell
$root = $PWD.Path
& .\backend\.venv\Scripts\python.exe .\apps\desktop\package-native.py `
    --frontend .local/librechat-phase4-native-20261107/dist `
    --backend-image $backendImage --output .local/native-package
if ($LASTEXITCODE -ne 0) { throw 'Native resources did not finish packaging.' }
$configuration = Join-Path $root '.local/native-package/tauri.portable.json'
Push-Location apps/desktop
try {
    pnpm exec tauri build --no-bundle --config $configuration
    if ($LASTEXITCODE -ne 0) { throw 'The native executable did not finish building.' }
} finally { Pop-Location }
Copy-Item -LiteralPath apps/desktop/src-tauri/target/release/leornian-desktop.exe `
    -Destination .local/native-package/Leornian.exe
$env:LEORNIAN_LOCAL_STATE_DIRECTORY = Join-Path $root '.local/native-acceptance-state'
Start-Process -FilePath .local/native-package/Leornian.exe
```

EXE 与 `runtime` 目录一起分发，运行时不要求仓库、uv 或全局 Python / Node。首次启动为专用 `leornian-local` Compose 项目创建随机凭据和独立卷；默认验收端口为 API 8122、前端 5202、数据库 5462、Redis 6392，打包参数可逐项修改，四端口必须不同。被其他应用占用时拒绝接管。上述验收状态目录可独立保留；普通启动默认使用当前用户的应用数据目录。包中的镜像负责应用后台，课程依赖按本人的允许决定准备。

停止本机服务时先向原控制器发停止信号并等待其清理，再停止本应用 API / 教学 Worker / 资料 Worker / Relay / PostgreSQL / Redis，最后停止随包 Node。停止动作保留应用数据卷、原回执和课程缓存；恢复启动继续读取原状态。

开发时可用 `pwsh -File .\start.ps1 -WebPort 5194` 在另一端口打开同一后台和本机 Runner，默认网页端口仍为 5180。

## 隔离与故障

- 旧 Python 用例为 6 秒、128MB、0.5 CPU、32 进程；新文本输入项目单次运行 8 秒、512MB，编译独立限 90 秒、768MB、1 CPU。HTML/CSS 浏览器检查限 35 秒、768MB。所有用例 stdout/stderr 各最多 4096 字节。
- `--network=none`、只读根目录、无宿主目录挂载、UID/GID 65534、移除全部 capabilities、no-new-privileges。
- 控制凭据只留父进程，不传入学习代码容器。控制器不连接业务数据库，预期答案留服务端 assessment；下述 SQL 工程 Profile 仅使用本用例的临时练习库。
- 回报可重试最多三次，但不会重新执行同一代码；过期任务由 relay 关闭，不自动再领取。
- 每次启动及执行期间轮询原 execution 的 claim、租约、会话和当前业务资格；有环境 release 的任务同时核对当前环境授权。取消、来源失效或撤销后停止实际容器，保留原报告；后台决定报告能否应用到当前业务状态。轮询不延长容器硬超时。
- 每次只清理本进程生成随机名称的容器，不 prune 或影响其他项目。不能确认停止时控制器退出，不继续领取新作业。
- `tests/test_runner.py`、`test_program_runner.py` 和 `test_multilanguage_runner.py` 分别覆盖原路径、新旧项目、三 SQL 方言、编译与运行分离、实际浏览器检查及执行资格失效后的停止。Runner 不持有预期输出，语义评分留服务端。

## 公开 Profile 与结果

`execute_sql`、`execute_project`、`execute_stdio` 和 `execute_web` 消费 execution 的封闭公开 DTO，不接收任意镜像、命令、数据库 URL、宿主路径或预期答案。原队列、报告所有者与 Assessment 继续消费实际结果；客户端只查看业务合同允许的公开样例。claim 广告本机已有的精确环境，未具备对应能力的控制器不会领取新 Profile。

- `project-stdio.v1`：六语言共同使用 1—32 个相对路径文件、合计最多 256KB UTF-8、明确入口和 1—3 个原始字符串 stdin。Python / JavaScript 直接运行，TypeScript / Java / Go / C# 先独立编译。构建只用可信参数与固定工程文件，拒绝学习者 `package.json`、`go.mod`、MSBuild / Dockerfile 等配置；源文件只读、编译产物进入本作业独立卷。Go 由控制器提供固定 `module learner.local/project` 与 `go 1.26`，编译入口所在目录，跨包导入使用此前缀，仅访问标准库和本题声明文件；代理、校验服务与工作区关闭。`RunnerReport.compilation` 记录编译结果；失败编译可以返回空 `cases`，成功编译或缺少编译记录时仍须有实际用例。Assessment 统一 CRLF 为 LF，并仅移除末尾一条换行后比较文本，保留其余空格。
- `web-check.v1`：固定 Chromium 在无互联网的隔离环境中检查声明 HTML/CSS 文件的 DOM 存在、文本、计算样式和点击后的文本。只返回唯一 key 对应的字符串、严格布尔或 null 观测，预期答案不进入 Runner。Assessment 逐项比较 `web-check-result.v1`，HTML/CSS 环境就绪与题包课程资格分别校验。

- `sql-query.v1`：SQLite 在受限 Python 容器内建内存库；PostgreSQL / MySQL 每组数据各启一个网络关闭、无宿主端口的临时数据库容器，数据目录仅在受限 tmpfs。可信客户端通过本作业命名卷中的 Unix socket 连接，使用只有 SELECT 权限的 learner 与只读事务，不取得业务/模型凭据。SQLite 同时使用 query_only、authorizer 及扩展禁用。
- Schema 只收有界的表、四种列类型、单列主键及外键；数据逐类型、行宽、NULL、主键和引用检查，实际建表/约束，不接模型任意初始化 SQL。每组最多 100 行，最多三组。执行一次查询，最多返回 100 行/12 列，保留列名、顺序、重复行和 NULL；数值转换为不丢 Decimal 精度的规范文本。`sql-table.v1` 在首次业务准入前增加实际 `types` 矩阵（integer/number/text/boolean/null），不以文本冒充数值或把 NULL 字符串当空值；不同方言的 bool/数值实际 kind 可以不同。协议不排序、去重或判分，比较策略固定在原 Assessment；当前不支持 DDL/DML 练习。
- SQL 客户端 128MB、0.5 CPU、64 进程，单查询外层 7 秒，PG/MySQL 另设 5 秒查询限制；输出仍不超过 4096 字节。PG/MySQL 服务分别限 256/512MB，临时数据目录最多 256MB，初始化等待最多 35 秒；原队列为新 Profile 固定 300 秒租约覆盖准备，旧 Python 仍为 90 秒。超过租约只记迟到事实，不自动再执行。
- `python-project-io.v1`：真实 2—20 个相对路径文本文件、合计最多 100KB UTF-8，声明唯一 `.py` 入口，拒绝点路径别名/穿越。可信暂存器将文件写入本作业命名卷，学习者容器只能只读挂载，无宿主目录。每组使用新容器和最多 16MB 的 `/tmp`，保留原 6 秒/128MB/0.5 CPU 与整数数组协议。允许标准库跨文件导入和读取声明数据，不安装框架或第三方依赖；原 ItemBank/Assessment 另验证提交的完整清单、入口与只读文件未改。运行前在无学习者挂载的可信容器核对 Python 版本并固定本地镜像 ID，学习者自行 exit 70 不冒充版本检查失败。
- 容器/卷使用控制器生成的随机名称，卷带所有权标签；定向清理，不能确认停止或清理即抛出 `CleanupError`，不继续领取。没有 Docker prune、业务库访问或全局 SDK 改动。

开发者显式准备可信客户端镜像（不是最终用户的安装旅程）：

```powershell
docker build --pull=false -t leornian-sql-client:dev -f services/runner/Dockerfile.sql-client services/runner
$env:LEORNIAN_TEST_DOCKER = '1'
uv run --frozen --directory backend pytest -q tests/test_program_contracts.py tests/test_program_runner.py tests/test_runner.py
```

客户端锁定 psycopg binary 3.3.8 / PyMySQL 1.1.2；受控准备器在隔离 PostgreSQL / MySQL 服务中实际执行合成 SELECT 后才报告 ready。旧手工 Profile 可设置 `LEORNIAN_RUNNER_SQL_CLIENT_IMAGE`、`LEORNIAN_RUNNER_POSTGRES_IMAGE`、`LEORNIAN_RUNNER_MYSQL_IMAGE`；新课程精确消费 release 中的客户端与服务端镜像身份，SQL 查询前再次核对实际版本。可选旧 Profile 探测失败保留已可服务的能力；清理状态不明则停止控制器。

# 第四阶段 Spec：合同、数据归属与运行规则

设计日期：2026-11-03。文档版本：1.2。状态：技术合同基线；第四阶段实施中，进度已核对至 2026-11-12，见 [IMP 第 6 节](imp.md#6-状态维护)和[仓库说明](../../README.md#第四阶段进度核对2026-11-12)。

以下日期条目保留对应切片的实现与部署事实；当前范围及未完成项由上述进度维护，合同目标不因局部验收通过而缩减。

实施进度（2026-11-03）：WP01 的低阶精确文本/块/生命周期绑定/私有需求与 WP02 的用户模型配置/原 Runtime 路由/四类固定协议探针/持久文件解析已有首批实现。仅新增 0023—0026 并在测试库验证，两个包均未满足全部退出条件。下文仍是完整目标合同；实现范围与分层结果见根 README 和 IMP 状态表，不将目标端点一并视为已存在。

实施进度（2026-11-04）：0027—0029 在本轮临时专用测试库增加正常材料模型操作、索引/持久检索选择、Tutor 精确绑定消费，以及概念单选/现有 Python IO 两类交互工件后台。原库/服务未升级，工件样式入口未接正式业务。以下标注当前切片与剩余目标的差异，WP02/03/05 均仍实施中，真实千问、全部消费者/工件和正式界面验收未完成。

同日续接新增 0030—0031：教学/规划/课时的自动消费者需求、规划与课时精确材料引用、下一次混合查询驱动的分批向量重建及新 Run 的闭合工件选择。仍只在独立临时测试库验证，readiness 要求 0031，不更改既有开发部署或前端预览。

2026-11-05 续接新增 0032：题包冻结各用途材料引用，接入作者/六审自动需求及两类题目的精确新引用；源码 readiness 要求 0032。仍仅更新独立临时测试库，不升级原开发服务。分层证据以根 README 最新续接记录为准。

需求和产品验收见 [PRD](prd.md)，代码改动顺序及验证见 [imp](imp.md)。本文件细化 [架构基线](../architecture/overview.md)，不另立 Runtime、数据库权威或产品范围。下面的新名称为本阶段合同目标，落地时必须同步服务端、生成类型、调用者及本文，不能只改一端。

## S01. 不变量与本阶段范围

1. 独立 Leornian 数据库；旧项目只参考，不复制其数据、UNKNOWN、授权或现场锁。0022 以前已有迁移和回执不改写。
2. 唯一原生 Runtime；业务流程仍由所属模块的用例推进，不能将材料、生题和教学统一塞进一个通用 Agent 工作流。
3. 身份、当前作用域、发布资格、辅助/曝光、评分及进度由服务端权威判断。模型、前端、缓存和通知不授予权限。
4. 教材自动准备/发布不等于自动切换学习路线；用户不更新时继续当前合法版本。
5. 单次物理容量、超时、资源约束与调度批次不是任务总尝试次数上限。已知质量问题持续修复，不用相同失败输入刷结果。
6. 派发前保存 `dispatching`；结果不明保留 UNKNOWN，过期租约、重复消息或取消不授权重发。迟到结果可保存，不代表允许应用。
7. 阅读、演示、提示后成功、运行退出码、工件完成与独立掌握分别建模。不得削弱既有 Gate/关系审查/实际曝光规则。
8. 本阶段只声明经分层验收的能力，不以测试夹具、文档或注册项代替真实调用、真实执行和界面证据。
9. 唯一产品模式为用户本机执行；Desktop、本地 API/Worker/数据、隔离引擎及 Runner 同机运行，不提供或预留远程执行分支。本文“服务端”指本机业务权威，进程分离不是跨设备部署。
10. 支持规则与可信配方内置，实际课程环境按需准备；路线安装授权、引擎系统权限与运行/开考是不同决定。用户授权不能被模型、路线确认或 GET 代替。
11. 用户自配的外部模型 API 及获准资料获取仍可联网，本地执行不等于完全离线；只按用途发送必要上下文，不默认外发完整项目或使用远程执行服务。

## S02. 归属、复用点与命名

| 所有者 | 新增/扩展职责 | 继续复用 |
|---|---|---|
| `knowledge` | 材料需求、接入/续检、文档/块/语料版本、索引、覆盖、证据选择、变更与更新提案 | 来源、明确用途/权限检查、不可变版本 |
| `learning` | 当前材料绑定、更新决定/迁移、分维度能力投影、复习与算法版本 | 计划确认、课时、概念/执行证据 |
| `tutor` | 教学会话、交互工件外壳、候选选择、答疑分支、教学意图 | conversation/turn、交付检查、精确教学绑定 |
| `item_bank` | 各工件可用的已审内容、能力匹配、补救/新情境供给 | 作者、盲解/执行、六审、持续修订与合格发布 |
| `assessment` | 动作对应的作答、辅助记录、独立性和评分 | Attempt、Gate、曝光/关系审查、讲评回执 |
| `execution` | 本机环境需求/安装授权、环境准备及资格、多语言 Profile、编译/运行/查询/检查 | 原任务、租约、可信 Controller 与本机隔离 Runner |
| `delivery` | 对话条目投影、通知中心投影和已读/稍后展示状态 | 同一 actor 事件游标、快照、SSE、历史分页 |
| `agent_runtime` / `platform` | 用户模型 Profile/凭据解析、新模型操作的协议/回执、工具合同、后台唤醒 | 单一 Runtime、Outbox/Inbox、幂等、心跳与取消 |

`tutor` 只写工件交互外壳；正文、题目、结果与进度仍由原所有者写入。`delivery` 不成为所有内容的总仓库。

0022 的 `tutor.artifacts`、`artifact_versions`、`artifact_requests` 是教学文档模型。本阶段将其明确归类为历史教学资料；保留原数据和工具合同，不直接修改成可执行工件，不把已验证文档调用计作交互工件验收。

当前复用位置：`backend/src/leornian/{agent_runtime,bootstrap,modules,delivery,platform}`、`services/runner/controller.py`、`apps/desktop/src/{TutorPanel,ArtifactPanel,SourcesPanel}.tsx`。目录随真实用例建立，不预建空层或占位适配器。

### S02.1 前端来源与适配边界

2026-11-03 用户补充决定：后续前端以 LibreChat 前端源码为基础，先独立固定来源及基础适配，再逐步迁移，不能直接覆盖或退役 `apps/desktop`。

- 本次来源固定为官方仓库 `https://github.com/LibreChat-AI/LibreChat.git` 的提交 `f4154b649efa37e1345ccc517a4d8d1ed2178c82`（提交日期 2026-10-31）；本机独立、被忽略的只读来源在 `.local/upstream/LibreChat-f4154b6`。包元数据为 `v0.8.9-rc1`，不是稳定版或“最新版本”结论；后续引入实际使用部分时保留来源、原始许可及版权通知。
- 当前已核对来源及部分依赖/组件，并将最小 ChatPane/视图选择结构适配到独立 `/chat.html`，由现有 App/Tutor 提供业务槽位；后续按用户明确安装要求，完整 client 及三个前端配套包已在独立 checkout 按 lock 安装并构建。`apps/librechat/preview.mjs` 在本机 5180 托管原版完整构建，提供明示的只读 UI 启动夹具，不连接业务后台、模型或保存凭据；模型列表为空、全部业务写入拒绝、未知 API 明确不支持、同源 CSP 且不注册 Service Worker。这不等于完整客户端与 Leornian 身份/消息/任务/导航的业务迁移。`@librechat/chat` 声明 `private: true`，不是可直接安装的独立公开组件方案；其组件/状态还依赖 `@librechat/client`、`librechat-data-provider` 等。上游 client 使用 React 18，chat/client 配套包的 peer 范围包含 React 19；逐项验证适配，不为整仓构建盲目降级 Leornian React 19 或引入其完整工作区。
- 可复用聊天布局、导航、消息展示与输入体验；身份、HTTP、任务、公开回复、快照/SSE、历史分页、取消与刷新恢复仍以 Leornian 当前合同为准。不能把上游 `ChatEvent`/generation 协议当作 Leornian 公开事件，也不能用上游 optimistic/final 状态替代 accepted 交付、业务评分或 UNKNOWN 判定。
- 不接上游 API、MongoDB/搜索等后台、Agent Runtime、MCP 工具执行或代码执行系统，不保留远程 Runner。模型凭据继续由本人配置并经 Leornian 后端隔离保管，不在 UI 中直连模型提供方。
- 通用聊天基础适配可以先行；正式 `learning_artifact`、闭合 renderer、`allowed_actions`、CAS/幂等及原所有者动作仍按 S09—S10 与 WP05/06 实施。上游普通 Artifact 不是本项目 Learning Artifact。
- 按实际接入范围审查外部资源和原生权限。上游 Sandpack 路径含外部 Tailwind 资源及可配置 bundler；不能因此默认引入联网预览、主 DOM 脚本、宿主桥接或放宽 Tauri CSP。预览与执行资格仍按 S13 和 WP07/11 验证。
- 模型设置、材料上传/来源、路线/课时、概念/Python 练习与 Gate、复习按功能逐项迁移并验证后，才允许退役对应旧入口；同一身份和任务链共用原权威，不另造第二套状态或数据。

来源声明差异：本次提交根 `LICENSE` 为 MIT，根/client `package.json` 的 `license` 字段为 ISC。保留原声明并记录差异，不自行改写上游元数据；实际移植部分及其依赖在发行前核对许可/通知，未宣称整仓依赖许可已清理。完整前端安装跳过生命周期/prepare，仅执行 data-provider、client/chat 配套包和 client 的前端构建脚本；未运行整仓 frontend/API 构建或后台服务，安装与构建后来源工作树仍干净。

## S03. 材料、证据与版本模型

### S03.1 最小记录与身份

| 记录族（归属 `knowledge`，除注明者） | 必须表达的事实 |
|---|---|
| `material_demands` | actor/共享范围、目标/节点、语言与框架版本、用途、required/optional facets、消费者引用与状态 |
| `material_jobs` / 阶段记录 | 需求、当前阶段、策略版本、进度、失败原因、后继、取消根、下次可运行时间 |
| `source_observations` | 抓取/条件请求事实、来源位置、检查时间、响应身份、解析前快照引用；不是新教材版本的同义词 |
| `document_versions` / `document_blocks` | 不可变正文版本、章节路径、页码、块类型、原文标识、代码/表格、可验证定位 |
| `chunks` / `index_builds` | 原文块/范围映射、文本身份、解析/分块策略、向量模型/维度/预处理版本及索引状态 |
| `corpus_releases` | 精确 Subject/版本、材料集合、可用用途、发布状态；active 指针仅作为新选择的默认入口 |
| `material_selections` | 请求需求、精确语料和证据、逐项覆盖结果、未覆盖项与策略；不能只保存查询字符串 |
| `material_checks` / `change_reports` | 检查基线、完整变化、分类、范围、审核事实、可复用结果及理由 |
| `material_update_offers` | 当前绑定到候选后继的提案、影响、准备状态及关联通知；不是切换事实 |
| `learning.material_bindings` | 学习路线/节点的精确版本与证据集合、绑定 revision、用途及适用性复核时间 |
| `learning.material_update_decisions` | 用户决定、原绑定 revision、提案版本、幂等键及生效/后继引用 |

新合同使用 `MaterialRef` 表达 `document_id, document_revision, block_id, span, content_digest, selection_id`，绑定对象还保存 `binding_id, binding_revision, purpose`。完整正文大时使用可分页的受控引用，不将进程对象、裸连接或运行时权限放进 DTO。

首批实现细化：文本/Markdown 块的 span 为原始 Unicode 文本的字符偏移，当前只接受完整精确块的范围/身份；HTML/PDF span 明确属于 `extracted_text`，不是原文件字节偏移。PDF 块只带实际 source_page；无可信边界框时不保存坐标。直接原文读取/初始绑定可没有 selection_id；后续经检索选择的材料须带其真实 selection_id，不能凭空创建选择或覆盖证明。`material-texts` 仅接收最多 2 MB 的显式文本/Markdown，返回 parsed 而非 ready；小文本原文暂存 knowledge 所属版本表，0026 的文件原文保存于模块受控本机存储，索引/消费者仍待 WP02/03。

0025 的私有材料需求保留 exact plan/node、语言/框架版本及 required/optional facets，用户入口的 consumer_ref 由服务端生成，不接收用户伪造的其他业务消费事实。持久任务保留阶段、取消根、租约和输入身份；仅确定性解析允许在 Worker 丢失后承接，不推导任何外部调用许可。未闭合 Markdown 可自动降为精确文本解析，记录独立 parser_version/质量问题而不补写围栏；随后等待真实检查。正常解析等待索引/覆盖，不把 open demand 或 parsed 文档改成 ready。临时输入按完成、取消及真实保留截止清除。

0026 增加需求下的上传引用、原始字节身份及文件任务：原文最多 20 MB，UTF-8 文本/Markdown/HTML 与可提取 PDF 的确定性解析复用现有 Worker/relay。HTML 不渲染、不自动请求外部资源；PDF 空/低质量页保存真实页级 OCR 需求与 partial 状态，缺本人专用配置为 waiting_config，有配置但材料调用链未实现仍 waiting_dependency。提取文字最多 2 MB/10,000 块，PDF 最多 200 页，解压受限；独立进程 60 秒/512 MB 且无应用凭据。Windows 已验证，Linux/Compose 只更新配方。真实保留到期清除文件、派生文本和章节路径，保留定位/内容摘要/绑定/任务失败等审计身份；命令只保存正文内容身份，避免重复原文无限留存。取消仅清除未消费文件，不能借取消删除已合法保存版本或历史事实。来源区的折叠上传入口已接本人用途声明、任务状态/分页、取消及附件下载，权限默认不勾选、期限默认留空；旧摘录入口不提前移除。受控联网获取、实际 OCR/质量修复和索引仍未交付。

来源内容身份校验是材料与索引协议的一部分，不另外创建“完成证明”校验清单。抓取时间、任务 ID 不参与正文等价判定。私有材料与共享材料必须有明确隔离范围，缓存复用不扩大可读范围。

当前文件入口保留 20 MB 原文上限，完整文本/Markdown/HTML 按文件容量处理；直接文本导入仍为 2 MB，PDF 的单个提取分段仍受 2 MB 限制，后续按原分段流程承接。各入口的容量分别校验，不通过扩大直接文本合同接收大文件。

### S03.2 原文与定位

- 原始文件/正文存所属模块授权的文件或对象存储；数据库保存版本、元信息和受控引用。
- 段落、代码、表格与检索块可回到精确页/块/范围。引用显示原文，不用生成摘要冒充引用。
- 工件来源阅读的 `CompositionSourceView.location` 返回与该块 `source_page` 对应的真实 `DocumentPage`。`document_page` 显示页号，`image_region` 显示图片区域号，`document_part` 显示文档部件；区域坐标和原部件身份沿解析记录保留，不把图片切片序号写成物理页码。旧来源没有定位记录时保持原页号/块引用。
- PNG/JPEG 的 `image-original.v2` 尽量保留整页，超大图按原始坐标均衡分区；单区边长不超过 2200、面积不超过 250 万像素，以符合原 OCR 图像容量。OCR 使用该版本冻结的 `DocumentPage.region`，不按新策略重算旧区域；没有显式坐标的旧编号请求保留 v1 的 1000 网格语义。原图、新旧派生版本与调用回执分别保留，解析器升级不改写已发布引用。
- 坐标只在解析器/服务真实提供且可验证时保存；OCR 文本输出不意味着已获得可信边界框。
- 文档版本内的块身份稳定；跨版本使用显式映射，不能把相似位置当同一块。
- 模型原始响应、私有材料和完整提交不能进入一般日志或公开 SSE；保留与清理按实际数据策略执行。

## S04. 自动接入、修复与完成条件

主路径：`queued → discovering/fetching → parsing/ocr → checking → indexing → validating → ready`。

可恢复状态为 `repairing, waiting_dependency, waiting_config, blocked_unknown`；用户取消为 `cancelled`，被明确后继替代为 `superseded`。`ready` 必须对应具体 facets/章节/用途，不允许把部分可用标成整本合格。

- 优先已有材料；缺口才从登记/获准来源发现和获取。HTML、Markdown、可提取文本的 PDF 优先直接解析，扫描页或低质量区域才 OCR。
- 获取采用受控出口，检查目标、重定向与地址范围；不访问宿主/内网或携带无关凭据。下载、解压、解析和模型输入有实际容量约束，超大材料拆批，不静默丢弃。
- 根据空正文、错序、表格缺失、代码字符/缩进疑点、版本冲突、覆盖不足等原因定向换策略。代码语法异常触发原页复核，不自动“修正原文”。
- 模型提取结果和材料正文均是不可信输入，不将其中指令当系统或工具指令。
- 同一失败候选和同一配置不反复付费审核；连续无进展改变处理/选材策略或等待真实依赖，不以新增 job ID 伪装新输入。
- 每批保存已完成页/块、覆盖进度与下一步，公平让出资源；不设任务总版数/修复次数上限。不扫描固定队首后忽略全部可运行后项。
- 用户不承担片段审批、格式补正、发布或任务恢复。无权获取时自动找其他获准来源；确无替代依赖时保持等待，不绕过权限或虚构材料。

材料任务进入 `ready` 需同时满足：可用正文/结构、可追溯原文、当前允许用途、索引与实际检索验证、明确覆盖结果。消费者可以在此后读取并完成接受；4.1 的产品验收还要求至少一条真实消费者链，不能让消费者等待 `ready`、而 `ready` 又等待消费者形成循环。网络和模型调用不在业务长事务内。

### S04.1 授权来源与完整目标

0055 保存 HTTPS 来源登记、精确 URL/允许路径前缀、用户输入的语言/框架版本、用途、私有材料外发许可和独立保留期限。每次获取与重定向均重验获准范围及实际连接地址；条件请求、原始响应、原文上传和解析是独立事实。`changed/unchanged` 只描述来源观测，正文仍须走原材料处理链。撤销停止后续获取及衍生使用，在途结果保留回执但不能恢复权限。

原始响应已记录、原文尚未清理的观察在 `material_storage_unavailable` 后，可定向续行原观察，重验会话/来源许可并复用原文，不新建 HTTP 请求。未记录响应、UNKNOWN 或原文已清理不进入此存储续行。`html-main-text.v2` 在唯一 main 内只有一篇 article 时优先该正文；多篇 article 保留完整 main。正文内有意义的图形/公式仍保持待处理，旧提取经 `html-main.v2` 修复派生新 revision，原版本与固定引用保留。

0058 在原目标请求和目标上保存可选 `goal-material-scope.v1`：必填明确语言，语言版本、框架和框架版本可选；框架版本必须对应明确框架，`authorized_official_sources` 必须为严格的 `true`。新目标表单默认不开启，同一请求键比较完整范围；UNKNOWN 只读取原请求，不重新附加范围。Learning 公开目标 DTO 向正常材料需求提供四个明确科目字段，匹配的内置官方目录据此登记来源。目录不虚构目标未指定的版本，不用标题、首问或旧请求推断联网授权；未提交范围的目标继续保持 `None`，输出省略该可选字段。

上传支持完整来源 `whole_source`；自由教学目标使用 `teaching_goal + goal_text`，不截成字面 facets、不根据标题猜版本。既有 `facets` 继续使用其显式词面合同。长来源、选材及变更复核按完整范围拆批，保存每批身份和进度；合并覆盖使用全部子结果，不能以默认第一页或前若干块代表全书。

`material_check.v1` 是同一 Agent Runtime 中的独立材料职责。每个源页/汇总部分有原 Run、本人模型绑定与外部调用账本；结果必须引用实际提供的全部来源或子部分，并保存可供消费者使用的教学摘要。`supported/partial/missing/uncertain` 根据完整目标判断，词面命中和 rerank 分数不授予充分覆盖。只有 `semantic-goal-evidence.v1/sufficient` 才能解除正常消费者的 `material_pending`。

摘要的 JSON schema、提示词和接受校验与公开 `MaterialCoverage.synopsis` 使用同一 Knowledge 域内常量，保持既有 4000 字符容量；完整请求仍按本人 Profile 和实际输入预算拆分。正常查询推进重验原会话、材料权限、精确引用和模型绑定后，若已完整收到的未消费结果在当前合同下合法，恢复同一 Run，由原 AgentLoop 消费原回执，不新派发；仍不符合合同的结果通过 `Runs.repair` 在原 Run 登记下一步格式修复，原调用按非法结果消耗并保留。已经合格的部分继续复用。修复只使用最终内容和具体诊断，不传递原 wire 或私有推理；引用差异列出实际范围及原允许范围，不改写模型结果。摘要超限反馈包含实际长度；旧通用反馈可升级为具体反馈，最近一次具体反馈后长度下降可续，未下降时等待；其他同类诊断无进展时等待。UNKNOWN、已消费、取消或权限失效不授权新派发。

0057 将该职责的 `scope_id/input_ref` 分别约束到真实 search/coverage part；其他既有 policy 仍以条件生成列保留 Tutor conversation/turn 外键，原输入唯一性及同 scope 活跃 Run 约束保持。材料 Run 不创建 Tutor 发言或投影虚构的 `tutor.*` 会话事件。保留清理经 Runtime 所有者清除请求/响应内容，UNKNOWN、调用身份和迟到回执元数据保持。

## S05. 模型 Profile 与协议

### S05.1 用户配置与凭据边界

所有模型职责均支持用户自行配置（BYOK）：教学/规划/课时/检查/讲评、作者/盲解/审核、材料变更复核/完整目标检查及 OCR/Embedding/Rerank。界面提供“提供方连接 + 模型 Profile + 角色映射”，允许一份凭据供本用户多个兼容 Profile 使用，不要求重复填写密钥或自行构造 API 请求。

- `provider_connection` 保存 owner、协议类型、base URL、region、连接 revision、启用状态及 `credential_ref`；`model_profile` 保存模型、能力/容量、参数/思考策略、超时与 role mapping revision。非秘密配置与凭据分开，提供方协议及能力须实际匹配，不能仅改模型名。
- 凭据仅在本机系统安全凭据库或受其保护的本机加密存储中保管，主密钥与密文数据分离。本地 Worker 只经可信本机凭据解析入口取得短时使用的明文；不设远程保管/执行模式，不靠前端 localStorage 或明文配置表保管，也不为此引入第二套 Runtime。
- API 仅在写入时接收明文，读取只返回安全描述、状态与 revision。模型请求正文/持久回执、业务 job、公开快照/SSE、普通日志、工件和学习者容器均不得携带 key；身份取自服务端，不能由模型另选凭据 owner。
- 用户可保存、主动测试、轮换、停用和删除凭据；连接测试说明是否调用模型及可能计费，非自动静默探测。删除先撤销新使用并按实际保留策略清理秘密，历史配置引用、请求/回执和用量事实保留且不含密钥。
- 新步骤保存非秘密 Profile/policy revision 与 credential reference/version，派发前重新检查当前启用/撤销和外发范围。旧请求不能静默改用其他用户、平台或新版本凭据；未派发后继使用新配置须有明确版本化绑定，已 `dispatching/unknown` 的旧请求绝不因换 key 重发。
- 外部模型 base URL 仍受提供方协议、TLS 和出口地址检查约束，不授予本地 Worker 任意访问本机/内网的权限。用户明确配置的本地模型回环端点单独识别并限定范围，不把任意远程 URL 视作本地模型；外部模型协议不能转为远程代码执行入口。
- 私有材料只发送给当前用户为该用途启用的通道，缓存和索引隔离不变；本用户的云处理许可不替其他用户做同意决定。

当前 `Settings` 的进程级模型环境变量只代表已有开发配置，不是已完成的用户配置功能。迁移时显式标记原开发范围，不把其密钥复制为全部用户默认值；缺失或撤销凭据进入 `waiting_config`，不假报模型质量失败。

### S05.2 专用模型候选与当前授权

| Profile | 优先候选 | 必须验证 |
|---|---|---|
| OCR | `qwen3.5-ocr` | 扫描页/双栏/代码/表格识别与原页定位，失败修复及耗时 |
| 文本向量 | `qwen3.7-text-embedding`；对照 `text-embedding-v4` | 中文、英文与代码检索；真实输出维度、延迟、用量及索引兼容 |
| 重排序 | `qwen3.7-text-rerank`；对照 `qwen3-rerank` | 同一候选集中的排序与下游覆盖，跨语言及长输入 |

以上为 2026-11-02 官方文档核对的候选，不是账号可用性或质量结论。本用户已明确授权其私有材料发送千问处理，允许使用已有账号进行 OCR/Embedding/Rerank 收费开发与验收，无地域和费用限制；无需重复申请，不自动充值、升级或开通新收费服务。账号/端点/地域/模型仍须实际匹配，正式组合和依赖版本在真实比较后锁定；不因无指定地域而跨地域发送不兼容请求。

Profile 冻结 provider、region、model requested/resolved（若服务返回）、操作类型、输入/输出合同、预处理/参数、超时与 policy version。保留请求/回执/用量/耗时；缺失用量为未知。OCR、Embedding、Rerank 使用各自真实协议，不强套 Chat Completions。

OCR 不承诺直接返回结构化教材或可信坐标；解析层负责重建与验证。向量以“模型、维度、文本预处理版本”定义独立索引空间，更换后新建索引、验证再切换，不能混写；正文未变的模型切换不触发教材/题包重新制作。排序分数不是可跨请求比较的教材质量或授权分数。

模型适配复用既有外部调用记录、当前权限、取消及未知处理保证，不另建 Agent 引擎。教学/规划/课时/检查/讲评及作者/盲解/六审保留既有分阶段思考策略与工具协议；材料通道不会自动替换 Tutor 主模型。没有应用侧独立推理总量硬限额，供应商单次容量、完整请求预算和心跳仍有效。

### S05.3 当前独立模型与用途分配

设置沿用指定 5180 LibreChat 的原位置，侧栏只保留“外观、模型配置、用途分配”。外观提供主题、语言和界面缩放；模型配置按“教学与路线规划 / 材料处理”分类，两类均支持预设及自定义，连接和模型编辑、显式测试直接从提供方进入。用途分配作为独立设置。界面移除高级配置入口、重新读取和说明小字，展开栏保持完整点击区域与明确状态，鼠标点击不显示整块焦点框，交互控件保留键盘焦点。

连接保存协议、端点及本人的凭据引用；Profile 保存具体模型、操作类型、允许用途、真实容量、思考策略和超时。自定义连接继续使用现有 `chat_completions/dashscope` 协议。

`ModelConfiguration.capabilities` 的 `explicit-role-assignment.v1` 表示后台支持独立分配。新界面仅在该能力存在时以 `POST/PATCH /v1/model-profiles?assign_roles=false` 保存模型，保存不改变当前用途。`PUT /v1/model-role-mappings/{role}` 接收 `profile_id, expected_profile_revision, expected_mapping_revision`，同时检查本人、启用连接、允许用途、操作类型、凭据及双版本 CAS；未配置 mapping 的预期版本为 0。失效 mapping 保留 revision，业务解析拒绝已失效配置，避免删除重建造成版本回退。旧创建命令的默认自动分配行为及幂等请求保持兼容。

连接测试可直接选择尚未分配用途的启用 Profile。新探针冻结 `purpose=connection-probe.v1`、本人 Profile/connection/credential 版本，发送合成固定样例；必须明确同意本次可能计费，不要求私有材料外发许可。聊天样例只接受单个完整、无工具调用的 assistant 回复，其正文必须为合法 JSON 对象，仅含 `ok` 键且值为布尔 true；数值 1 不算成功。提交、派发及接受均重验原身份和冻结配置。UNKNOWN 不重发，配置变化后的完整迟到回执保存但不应用；历史探针维持原角色解释。

API Key 只在组件内存中接收，提交立即清空；切换身份重建编辑器。新增、编辑、启停、轮换及用途选择均不触发协议测试；独立用途分配的每项选择只有明确点击应用才提交映射。缺少能力标记的旧后台不能接收新界面的独立保存或用途切换写入。

### S05.4 DeepSeek 与千问快捷配置

快捷界面按需适配复用 CCS 的提供方选择器、Key 输入与模型选择组件，保留原 LibreChat 外壳。先选择类别与提供方，再填写 API Key 并“保存并启用”；默认选择该类别全部预设模型，也可在可取消的模型草稿中调整。按钮前保留简短的对话/材料外发与账号计费确认；服务端要求 `allow_private_material=true`，同事务保存本人连接、所选启用 Profile 和相应用途映射。固定来源、具体改动及 MIT 分发声明见 [CCS-UPSTREAM.md](../../apps/librechat/CCS-UPSTREAM.md)。

| 预设 | 连接与模型 | 用途规则 |
|---|---|---|
| `deepseek` | `https://api.deepseek.com`，`chat_completions`；`deepseek-flash`，上下文 1,048,576、最大输出 393,216、thinking enabled、超时 600 秒 | 明确应用全部 13 项聊天/教学职责 |
| `qwen` | 北京 `https://dashscope.aliyuncs.com`，`dashscope`；`qwen-plus`（上下文 1,000,000、最大输出 32,768、超时 600 秒）、`qwen3.5-ocr`、`text-embedding-v4`（1024 维）、`qwen3-rerank` | teaching 只配置聊天并应用 13 项职责；material 只配置所选材料模型且保持教学映射；旧无类别请求仍只补齐空缺教学职责 |

预设采用 2026-11-08 核对的官方别名和容量；千问其他区域及自定义模型从所属类别的“自定义”进入。千问聊天不发送 DeepSeek 专用的 `thinking` 参数；OCR、Embedding、Rerank 继续走各自现有真实协议。保存预设不发供应商请求、不创建协议测试或教学 Run。

`GET /v1/model-configuration` 返回 `provider-presets.v1/v2/v3` 能力和非秘密 `presets` 目录，附 Key 管理链接与 `model_details`。`POST /v1/model-presets/{preset_id}` 要求幂等键，正文为秘密 `api_key`、明确许可、当前 `expected_mapping_revisions` 及可选 `group/models`；指定 `group=teaching|material` 后，模型集合须为该类别的非空、无重复子集，省略时使用类别内全部模型。教学类别只允许 chat，材料类别只允许 OCR/Embedding/Rerank；无类别请求保持原语义。服务端复核本人和版本，任一失败回滚整个配置；相同命令只回放原结果，变更输入不能复用原键。v1 的已有连接 `connection_id/expected_connection_revision` 重新应用请求保持兼容。

`POST /v1/model-providers/custom` 要求幂等键、`group`、启用的 `connection`、`profile` 参数、`allow_private_material=true` 和映射修订号。参数包括具体模型、操作类型、实际容量、向量维度、思考策略和超时；先验证类别与操作，再由原配置所有者在同一事务保存连接、密文凭据引用、Profile 及组内映射。教学模型允许 13 项聊天职责，材料模型只分配其操作对应职责。任一失败完整回滚，原键回放不重复创建，不发供应商请求或创建 Run。

已配置连接按 ID 展示和选择，不用名称或端点推断要覆盖的账号。单独更新 Key 使用带 `expected_revision` 的 `PATCH /v1/model-connections/{id}`，模型、映射与启用状态保持。类别初始化复用原 `POST /v1/model-connections/{id}/use` 所有者操作，公开接口继续兼容旧客户端；提交 `expected_connection_revision`、`group`、`profiles[{profile_id,expected_revision}]` 与 `expected_mapping_revisions` 后，校验本人、连接归属、启用/凭据、材料许可、无重叠允许用途及操作类型，原子分配组内映射。教学组须覆盖 13 项职责；材料组保留教学映射。后续单项调整在独立“用途分配”明确应用，保存与切换均不发起模型请求。

前端凭据经不持久化的请求入口提交，禁止进入待重发命令队列、浏览器存储或草稿。失联只读核对配置，不重发秘密；更换提供方、身份或返回列表均清除临时 Key。当前类别预设与自定义写入要求 `provider-presets.v3`。复用既有 0024 存储，无新增迁移。

## S06. 检索、覆盖与消费者

`RetrieveMaterial` 请求由服务端绑定 actor、当前目标/节点、材料绑定、Subject/版本和用途。模型可表达查询和知识需求，不能另选用户、扩大私有语料或自报授权。

流程为：有效范围过滤 → 词法/语义召回 → 去重与融合 → 重排序 → 必要邻块/章节扩展 → 覆盖判断 → 保存精确选择。

完整 `teaching_goal` 检查直接消费本次冻结的正文范围，由独立材料职责拆组和汇总；
不先调用不会影响该范围的查询 Embedding 与 Rerank。普通片段查询保留原混合召回和重排。
两条路径均重验权限、索引空间及精确引用；跳过无用查询不减少必须检查的正文。

- PostgreSQL 全文检索与 pgvector 为首选部署方向，先复用现有数据库，不默认新增独立向量服务。中文正文、英文术语和代码标识符分别评估处理策略。
- 当前无真实语义通道时明确词法模式；不能用假向量或模型自述充当混合检索验收。
- 覆盖结果包含 `sufficient/partial/insufficient/unavailable`、缺失 facets、来源/版本/用途事实、所选范围及未装入原因。相似度或固定 top-k 不代表覆盖。
- 输入容量不足时对原文和需求分批，保留覆盖范围及最终组合检查；摘要不替代必需事实。输出不得假报已处理完整教材。
- 规划检查核心目标/先修是否可支撑；课时绑定节点证据；Tutor 按当前问题读取；作者和审核分别获得其职责所需材料，盲解不接收私有答案。
- 生成角色可由服务端在调用前选材，不因此开放全套工具。接受/公开前重新核对精确绑定、当前用途和业务条件。
- 索引和语料 active 指针是可重建/默认选择，不是旧路线的读权限或切换命令。

规划需求逐步澄清时，仅最新有效批次继续获取与检查，已就绪批次、索引和回执保留。
被替代批次不再派发新获取或审核；没有有效消费者的自动来源准备进入原后台暂缓状态，
后续明确选中时复用已保存原文和原作业。已完成的同目标、同权限范围和同检查阶段的
检查可供新请求复用，初始/增量讨论属于同一检查阶段，完整路线检查单独匹配；
新目标或版本不能继承旧充分结论，UNKNOWN 不因需求更新重发。

选源以当前未覆盖主题为主，语言和版本约束继续保留；明确需要的数据库或其他生态依赖
可以选择其实际语言的资料，不把学习者已有语言经验当作新目标。每个来源入口至多读取
三个资源，同一网站的不同框架入口分别计数，单任务总上限仍为十二个。
目录读取达到八个且仍不充分时，为定向补搜及新来源保留额度；补搜至多两轮。
旧任务保留的公开候选不阻止当前缺口的首次补搜；当前任务补搜得到的候选先使用，
不足时再决定第二轮搜索，避免连续搜索而不消费已返回候选。
HTML 关键图文未处理或空正文保留真实问题，自动来源的失败回到请求它的发现任务换源，
不把图文标记清空以换取通过；显式上传材料仍保留其原范围和处理需求。
处理耗尽的说明依据真实搜索回执，公开任务提供实际阻塞原因、不要求学习者点击修复。
取消子作业同步终结其未完成来源观察，已完成观察和 UNKNOWN 保持原事实。

### S06.1 当前后端切片与证据边界

2026-11-04 的 S06 实现说明：当前词法投影为 PostgreSQL `tsvector`，中文采用词项/双字片段；向量以数据库数组保存并在已授权范围内精确余弦检索，再做倒数排名融合和专用重排，不声称已安装 pgvector 或完成 ANN/大规模性能验收。查询显式选择 `lexical/hybrid`；缺语义通道允许词法查询，混合模式等待配置/索引而不暗降级。下一次混合查询发现缺少当前空间时，在原索引/调用账本中按批重建精确文档版本的向量，再开始查询/重排；不复解析/OCR/生题，不混写旧向量，不用当前已匹配的子集暗中排除其余材料。保存配置本身不立即启动全库重建；GET 不触发。

`POST /v1/material-searches` 当前返回 202 持久查询任务，输入为精确 demand/revision、query、mode 和可选 exact binding/revision；GET 任务/选择不调用模型。同输入换命令键仍指向原任务，不借新 ID 重发未知调用。选择保存精确 refs、逐 facet 文本证据、容量未装入数量和来源范围；`lexical-evidence.v1` 只检查词项支持，显式 `semantic_quality=not_certified`，不替代目标中的语义/教学覆盖验收。

精确选择可进入既有 MaterialBinding，Tutor 在当前用途下读取并冻结进交付清单，接受前检查绑定及权限。`MaterialRef.span` 现在也可指向精确块内子范围，同块多个不同范围可以分别绑定，内容身份必须与该范围一致；有 selection_id 时还须与本人/目标/用途下已保存选择中的完整 ref 相同。GET 历史选择只读取仍获准的原范围，不将原 scope 当作新动作许可。

2026-11-07 精确选区检索续接：带 binding 的查询按绑定 ref 与父索引 chunk 的交集形成候选，使用交集的原文、span 和内容身份；同一 chunk 中分离的范围分别保留。词法排序按实际切片重新计算，绑定外命中词不使切片入选。混合模式仍用已索引父 chunk 的向量做语义召回，选择 scope 保存 `semantic_recall_basis=indexed-parent-chunk.v1`；重排和实际消费者只接收精确切片，不为切片伪造独立向量。保存后的 selection 可按原合同进入新 binding revision，读取及执行继续复核当前用途、绑定和撤权状态。

新合格交付教学/规划/课时请求原子登记 `tutor-turn:<id>:<purpose>` 材料需求，重放不重复。语言/框架未知时为空，不从自由文本猜版本。新需求可检索同本人/目标、当前用途获准且来源任务未取消的已有索引，覆盖仍按新需求计算；显式 binding 不随默认索引变化。规划节点和课时章节的 `material_citations` 为 `{binding_id,binding_revision,purpose,ref}`，必须逐项等于实际供应的引用，保存于既有不可变文档 JSON。确认/消费复核精确绑定和活用途，不改读文档 head。课时/教学另建节点用途绑定时，原规划引用保留 selection_id，派生引用去除不适用于新用途的 selection_id，并单独验证文档对新用途的许可，不继承规划授权。题库作者/审核续接合同见下段。

已公开提交的 `attempt` 教学复核精确 plan/revision/node、题包与来源权限。材料型题目按公开标题和要求登记 `attempt-source.v1` 需求并绑定原 Turn，不要求覆盖整个节点；原提交、评分和私有测试不作为检索目标。仅有旧 `SourceRef` 的原题目继续使用其当前有效的固定来源，不因新增无关上传而自动迁移或要求全库覆盖。旧服务端整节点需求导致的零调用 `material_pending` 可在原交付恢复时冻结正确范围，后续工具及审核步骤继续使用该范围，旧需求与失败记录保留。已有调用及显式材料需求保持原范围；UNKNOWN 不通过此分支重发。

题包当前切片（0032）：新题包保存 `PackMaterialContext`，版本为 `item-materials.v1`，同题包固定 `origin_citations`、`author_citations`、`review_citations`，两组角色引用覆盖原节点的相同精确内容范围，但分别验证 `item_author` / `item_review` 许可和 plan/revision/node 作用域。派生引用不冒用规划 selection_id；文档 head 或绑定 head 的后续变化不重定向历史题包。自动修订与补充供题也沿这套入口，不另开生题/评分链。

模型主导路线允许节点在制定时没有原文引用。此时供题使用 `curriculum_node`：可以登记需求，但作者、审核必须先取得各自用途下充分的节点材料并固定引用，才能调用模型；盲解不接收这些材料。证据投影保留实际作者引用，不补造规划来源。

作者和六审阶段在同事务登记 `item-pack:<pack_id>:<role>` 消费者需求，重放/格式修复不增加需求，盲解不登记私有材料需求。作者/审核各自获得固定引用、当前仍获准的正文和本阶段需求；正文按不可信数据处理，角色工具不扩大。概念单选/Python IO 题目保留必填 `source_refs`（无旧来源时为 `[]`），另加 `material_citations`，至少有一种引用且必须实际供应；不将 document_id 伪装为 source_id。六审有新材料时逐题提供非空、精确的 `item_review` 引用，不能用作者用途的引用代替。引用本身不认证语义质量、独立性或通过结论；写入和发布资格都检查它，不改变负面审核修复的结论锁。

盲解仍只接公开题面，不接材料正文/需求、私有 gold/测试、作者轨迹或其他审核；Python 资格继续由原 Runner 链处理。派发、接受、发布及练习/Gate 继续复核固定引用与当前许可，Gate 增补课时精确材料范围/用途检查，工件或普通练习成功不直接写正式进度。旧题包的 material_context 保持 NULL，空的新引用不出现在旧题目/审核序列化中，不改变既有候选身份和曝光快照。关系检查/讲评等其余角色自动材料需求、真实检索/语义/教学覆盖与正式来源阅读联调仍未完成。

内部修订与学习者曝光分别解释：作者与六审收到实际前驱身份、发布事实、自动策略和指令是否继承的 `revision_scope`；审核另有准确的 `revision_baseline`。未曝光的私有上一版不单独构成独立性缺陷。继承初始请求的自动质量修订保留正确、未受影响的槽位，修复具体题面、选项或解释问题；实际已曝光内容和明确的新修订要求仍可要求重做。盲解不接私有基线、修订上下文或其他审核结果。

没有关联补救/迁移供给需求的独立自动题包，在历史版本已发布、后继路线已确认后继续保持已完成；新路线消费须使用对应供题。旧版尚未发布的 ready 题包仍复核当前路线，不能借后继确认获得发布许可。

## S07. 分层复核、稳定绑定与增量失效

### S07.1 分开四类时间与状态

1. `next_check_at`：来源变化检查。稳定来源初始默认约 30 天，快速变化来源可配置更短；到期只创建检查任务。
2. `review_due_at`：特定学习绑定的适用性复核。初始取 `max(绑定可用时间 + 180 天, 预计课程结束 + 30 天)`；无预计值使用 180 天。它不是硬失效许可，学习延长/暂停不会自动停用。
3. 使用权限：当前是否允许特定用途，存在真实截止/撤销时独立保存。未有真实限制不人为制造七天/180天授权到期。
4. 保留策略：原文/派生数据可保存的范围与期限。到期处理存储，不以检查日期推导；仅保留获准的非秘密审计事实。

日期、HTTP 状态、材料质量与当前权限各自判定。暂时无法完成后台检查不自动停用仍合法的固定版本；明确撤权或实际运行安全故障只限制对应操作，不能靠“保留旧版”绕过。

### S07.2 差异分类与复用

| 分类 | 判定与操作 |
|---|---|
| `unchanged` | 条件请求确认/精确正文未变；追加观察与复核记录，复用既有处理 |
| `metadata_only` | 已验证非教学区域的更新时间、导航等变化；只更新观察/展示元信息 |
| `editorial_equivalent` | 措辞/排版变化；比较变更块及必要上下文，规则与独立定向审查通过后记录等价依据 |
| `semantic_change` | 代码、条件、事实、版本、示例结论等变化；准备后继，计算影响依赖并通知用户 |
| `authority_or_policy_change` | 权限、用途、保留或审核要求变化；单独处理当前许可/必要重验，不默认全文重做 |
| `uncertain` | 不能证明等价；定向扩大检查范围或补材料，不能默认通过，也不直接全链重做 |

- 正文归一化只能去除已明确识别的非教学噪声，不能统一删除数字、日期、否定词、代码标点或条件。
- 实际字面变化保存新原文/块标识；等价是独立结论，不能让新正文冒充旧摘要/哈希。
- 未变块复用解析/向量；变更块只重做必要处理。处理缓存依据真实内容、配置和审核要求，不依据 fetched_at、job ID 或“最新版本号”。
- 影响分析按实际被引用块、必要上下文与用途依赖传播，不让全局 corpus revision 变更使全部消费者失效。
- 通知和差异以用户当前绑定为基线，不能只比较连续抓取的相邻版本而漏掉累积语义变化。
- HTTP 条件验证只解决表示复用，不授予使用许可。缓存事实复用后仍检查当前权限。
- 教材等价不等于 Gate 独立性等价；凡真正新增展示的内容仍记录曝光，不以续检或等价报告清除旧曝光。

### S07.3 不自动切换

新材料可先在合格用途/范围发布并成为新学习的默认候选；现有路线继续精确绑定旧版。新版本可用、active 指针变化、复核过期、通知已读都不能改变既有绑定。

发现已知错误时明确标注并给出更新建议；留用旧版不豁免题目正确性和评分规则，已证实不可用的题目不能继续伪造正式评分。历史事实保存，其他合法学习不整体重置。

### S07.4 当前增量处理与比较接口

0050 的索引增量处理只复用同 actor、同文档且版本不晚于目标、完整相同空间的精确文本输入。来源索引须已完成，原任务/需求仍有效，原版本当前允许 indexing；新版本也独立检查权限。新块保留自己的版本、块及 span，通过 `reused_from_chunk_id` 追溯实际复用；只为剩余块调用向量 API，全部复用时直接完成索引。此缓存只复用向量，不复用教学质量、语义等价或 Gate 独立性结论。同一精确文档/版本/块/范围的重复索引在词法/向量融合前去重，不合并不同版本。

`POST /v1/material-change-checks` 接收 `binding_id, expected_binding_revision, document_id, candidate_revision` 及幂等键。服务端从本人当前绑定推导基线，要求候选为该文档更晚的明确版本，并在同一短事务校验作用域及两版本当前用途。返回 `material-change.v1`，保存完整块级变化、未变块映射、实际引用影响、同章节上下文影响及精确子范围的新定位；派生定位不继承旧 selection_id。按 actor/binding/revision/文档/候选版本唯一，另存命令回执；GET 和同键回放仍复核当前材料权限。

精确正文未变为 `unchanged/no_content_change`；字面变化为 `uncertain/waiting_dependency`，原因 `change_review_required`。该确定性报告保持原结论和 `semantic_quality=not_certified`，后续定向复核单独保存，不改写原比较事实。页脚日期等非教学噪声不由规则猜测；未变引用周围的改动仍进入上下文影响。报告不触发更新接受或通知。

### S07.5 当前定向材料变更复核

0051 增加一份 change check 对应的唯一持久复核任务。新的显式 compare 调用为 `uncertain` 报告同事务登记；`unchanged` 不登记，同命令键回放返回原事实，不向旧命令追溯新增任务。任务由原 Worker/relay 协调，不创建 Tutor Run；`material_review.v1` 使用本人启用的 Chat Profile、私有材料许可和冻结的非秘密模型绑定，复用原 `ChatCompletionsGateway` 及 `Runs.prepare_operation/dispatch/record/applied` 外部调用账本。

复核输入为原变化块、候选变化块、受影响的原上下文引用及其已定位的候选范围；来源正文按不可信数据处理，不开放工具。闭合结果 `MaterialChangeVerdict` 包含 `classification=editorial_equivalent/semantic_change/uncertain`、最多 1,200 字符的 `summary` 及 `reviewed_refs`。每个要求复核的精确 ref 必须恰好出现一次；漏项、重复或换范围均不接受。完整且分类非 uncertain 的结果保存为 `reviewed`；uncertain 结果保存并进入 `waiting_dependency`。格式、引用覆盖或当前单次容量不满足时也保持 `waiting_dependency`，缺本人配置为 `waiting_config`。

大输入按实际调用容量持久拆批，每个版本内先按原块序号和精确偏移排列。每批携带 `comparison_scope`：完整文档的未匹配新旧块数量、当前窗口的真实变化/未变上下文身份，以及已验证的原文等价对应引用。窗口中没有出现对应段落不等于原文删除；确定性差异清单也不替模型判断新增内容的教学影响。超大块仍按完整子范围处理，汇总复核全部要求范围，任何实际不确定结论继续阻塞。

模型仅在 `reviewed_refs` 中返回本次输入块的短键 `r0…rN`，精确引用映射冻结在原调用的 `reference_keys` 中；后端还原完整 `MaterialRef`，继续检查全量覆盖、重复、未知键及原权限。对应段落的说明性引用不属于待回显集合，不能作为额外结果混入。既有完整引用格式回执仍按原记录解释。旧格式的已知完整响应若仅在引用集合校验失败，工程恢复入口 `repair_reference_output` 只补做未通过分段，保留原响应并记录后继调用；已采用短键协议的失败、UNKNOWN 和已接受分段不经该入口重做。

旧分段请求缺少上述差异上下文且已得到完整 `uncertain` 回执时，具名工程恢复入口 `MaterialChangeReviewWorkflow.repair_context` 可在重新核对所有权、绑定、权限、冻结配置和原回执后，只补做这些不确定分段。新操作以 `previous_call_id` 关联原回执，其余已完成分段及原调用正文/结论保留；已获得完整差异上下文的新请求仍不确定时不再通过此入口重做。UNKNOWN、未完成分段和取消任务不能进入该恢复。

派发及接受事务重新认证原 session，复核当前绑定 head、计划/用途、两版本权限和冻结配置；更换绑定、撤权或取消后到达的完整回执仍入原账本，不应用其结论。UNKNOWN 保留原操作，不因租约到期、重复投递、换 key 或新命令重新调用。已完成结果和原调用事实按当前权限保留；真实保留截止清除复核 result、操作请求正文和响应正文，调用身份及已发生状态继续保存。

`GET /v1/material-change-checks/{check_id}/review` 读取本人当前获准的任务/结果，无任务返回 null；`POST /v1/material-change-checks/{check_id}/review/cancel` 取消该复核。GET 不登记或派发任务。0052 在完整 `semantic_change` 结果的接受事务登记唯一更新准备，按 S08.1 推进；复核结论不改既有绑定、课时或评分。获准来源自动续检及完整分段复核沿原 Worker/relay 推进。

## S08. 更新通知、用户决定与迁移事务

更新准备优先保留原选材需求的完整目标或显式 facets。没有原选材需求的直接绑定按 `whole_source` 准备精确候选版本，再用原变更报告要求的完整范围选材；不从旧标题、版次或章节名推导新的教学目标。旧的服务端推导 facets 导致覆盖失败时，`repair_inferred_scope` 可在确认原来源需求不存在、绑定/权限有效且原调用全部已知后，以新的具名需求替换该准备分支。旧需求、失败步骤和引用保留，替换原因是 `inferred_scope_replaced`；原教学目标、用户显式需求及正式进度不改写。

`knowledge` 生成合格后继、差异和 `material_update_offer`；`delivery` 订阅已提交事实，维护通知内容、已读/稍后展示状态；`learning` 独占用户决定及材料绑定迁移。

通知包含：当前/候选版本、改变原因、影响章节/课时/练习、建议级别、更新代价、可选操作。元数据/已确认等价变化默认不通知。按“用户/路线、当前绑定 revision、候选实质变化身份”去重，不能因多次抓取或重投事件反复弹窗。

站内通知中心及未读提示是本阶段的持久入口，通知可重新打开并跳转到对应路线/差异；桌面系统通知仅在用户启用且平台权限允许后投递，不以系统通知是否展示作为业务送达或更新同意，不自动新增外部收费通知渠道。

决定为 `accept_update / decide_later / keep_current_for_track`：

- 未选择、通知已读、关闭或稍后决定均不迁移；本轮保留旧版仅针对该后继，后续新的实质变化可产生新提案。
- 接受操作携带幂等键、提案版本和 `expected_binding_revision`。服务器检查当前路线、后继准备情况、当前权限及受影响依赖。
- 调用具名协调器，通过模块公开 Facade 在同一短事务保存决定、材料绑定 successor、必要计划/课时迁移标记和事件。若路线结构必须修改，先形成明确可确认的迁移提案，不借教材更新默默接受新的学习目标。
- 不覆盖已完成课时、Attempt、评分和证据；新版本的适用性分别判断，不给旧通过伪造新版本通过。
- 迁移准备、解析、模型检查在事务外；并发变化返回冲突并重读，不能自动换基线提交。
- 通知/迁移不等待用户做材料审核；用户只决定是否切换已由系统准备的版本。

### S08.1 当前准备、通知与决定接口

0052 的唯一 preparation 固定原 change check、binding revision 及明确候选版本。新的 compare 命令复用历史已完成 `semantic_change` 复核时，也登记同一唯一准备，不重发原复核调用；GET 和原 compare 键回放不追溯登记。原 Worker/relay 自动创建正常材料需求/job，达到 ready 后调用限定文档/版本的正常词法 search，再由服务端装配 selection。原需求仍有效时保留其真实 facets、语言及范围；旧直接绑定或已取消需求沿原精确引用建立准备范围，不将学习目标动作句当字面词项。每个 required ref 和实际必需 facet 均须覆盖，部分覆盖等待，不扩大原选区。`editorial_equivalent/uncertain` 不登记更新准备；缺配置、依赖和 UNKNOWN 保留准确状态。

`GET /v1/material-change-checks/{check_id}/preparation` 只读状态及 demand/job/search/offer 关联；已有合格 selection 可通过 `POST /v1/material-change-checks/{check_id}/offers`、幂等键和 `{expected_binding_revision, candidate_selection_id}` 使用相同检查登记提案。`GET /v1/material-update-offers/{offer_id}` 返回 `material-update-offer.v1`，包含精确候选 refs、差异摘要、影响和准备/迁移代价。提案按本人当前绑定 revision 与候选正文身份去重，同内容跨候选版本复用原提案，保留本轮留用旧版的决定。

每份提案对应唯一持久通知。`GET /v1/notifications?limit=&before=` 分页读取，`POST /v1/notifications/{id}/read` 只标已读；关闭详情也不迁移。原材料入口及工程学习菜单复用同一教材更新组件，不另设独立业务状态。三种决定均通过 `POST /v1/material-update-offers/{offer_id}/decisions` 明确提交，并携带幂等键及 `expected_offer_revision, expected_binding_revision`。丢失回应后仅用 `GET /v1/material-update-offers/{offer_id}/decisions/{request_key}` 核对原决定，原命令未核清时不能另起决定；撤权后仍可读取本人决定的非正文元数据。

接受在同一短事务追加不可变 binding revision、predecessor/successor、决定及事件。实际计划/课时依赖按文档、revision、block/span 交集识别，跨用途也计算；DTO 保存真实 plan revision，派生课时关联其 plan/node，不虚构可变课时 revision。`requires_reprepare` 标记受影响内容，既有计划、课时、Attempt、评分和证据保持原引用。后续新消费仅沿明确接受的精确 successor 链读取新绑定，任意手工替换 head 仍判 stale；新内容经原准备链，路线结构变化仍须明确确认。

保留截止复用原清理入口，取消相关 preparation/demand/job/search，清除 review、自动查询、复制的 facets、selection 覆盖正文及原外调请求/响应；提案摘要从 review 投影，不另存正文。取消后的需求输出允许空 facets，创建输入仍要求非空。通知、决定、后继关系及已发生调用的非正文事实继续保存。自动来源续检、大输入拆批和完整内容重准备仍按原计划推进。

## S09. 对话内 Learning Artifact 合同

新公开类型 `learning_artifact.v1`，独立于旧教学文档合同：

当前 2026-11-04 后台切片只开放 `knowledge_check`（原概念单选）与 `code_workspace`（原 Python IO）。服务端从当前已发布普通练习生成候选；`TurnInput.learning_candidate_id` 的显式选择保留，须匹配精确 focus。新 Run 冻结增加候选列表工具，模型只可在该回合已返回的精确节点候选中选择，排除已作答/交付与考核题；普通 goal/attempt focus 不自动猜节点。回复闭合为 `{text,interaction}`，interaction 的 type 为 none/composer/artifact，artifact 仅允许 exact_handle 与 introduce_only。普通纯文本保留兼容，显式候选纯文本仍按原约定交付。旧冻结工具集合不升级，不接受其未声明的交互选择。

独立检查与接受前均验证候选；接受时重新核对当前发布/来源/锁定/focus。正文、`Turn.learning_interaction`、shell、timeline 身份、教学 CAS、Turn 终态与事件同事务保存。模型中间工具结果不发布工件，也不执行、作答或评分。client/model 选择来源分别保存，已接受模型选择的回合重放仍按原客户端输入幂等。修改后多 Attempt、其余完整业务工件与逐场景真实验收仍待实施；V2 组合及独立宿主进展见下文，不再将最初的“未接前端”当作全部现状。

候选身份固定到精确节点；原 Turn 如果带课时锚点，不由候选列表清除或替换，继续由原交付清单独立冻结、复核该课时。显式客户端候选仍保持原完整 focus 匹配合同。

```text
id, conversation_id, source_turn_id, timeline_item_id
revision, kind, state, title
focus { goal_id, plan_id, plan_revision, node_key, lesson_id }
content_ref { owner, id, revision, public_identity }
presentation { type, ...严格的类型字段 }
allowed_actions[], attempt_summary?, assistance_summary?, source_refs[]
```

`presentation` 为闭合联合：知识检查、代码工作区、执行结果、代码评审、SQL 工作区、演示、受限预览、来源定位。大详情经 scoped GET 分页读取；无当前操作时 `allowed_actions=[]`，不生成假按钮。

状态为 `pending/ready/active/running/completed/cancelled/superseded`，必要的错误由对应运行/作答结果表达。`completed` 仅表示该交互完成，不能成为独立掌握证据。

候选由服务端从当前会话/节点、已发布精确内容、有效来源、未见/辅助要求、scorer 与运行 Profile 构建。handle 只引用候选，不是可长期复用的权限；接受时重新解析与重验。模型输出是 `none`、`composer` 或 `artifact + exact_handle + allowed_intent` 的闭合组合。

工件局部状态（折叠、草稿、滚动）不决定业务状态。草稿按 actor/conversation/artifact/内容版本隔离缓存，不进入公共历史或普通日志；刷新不能自动提交或执行，版本冲突保留旧稿并显式处理。

### S09.1 V2 组件组合与独立原生宿主

- 新请求显式声明 `learning_composition.v2` 能力，冻结 `get_learning_component_contracts` / `prepare_learning_composition`；旧 Run 不增加工具。模型只能提供闭合组件、typed 状态/输入/timeline/意图，不提供脚本、表达式、URL 回调、权限、答案或结果。31 组件单一目录用于指南、Schema 与端口校验；结构合格仍须原独立教学检查与接受事务。
- `learning_artifact.v2` 的组合内容固定到独立 presentation、准备 Run、来源/计划清单和真实检查回执，不伪造题库 pack/slot。不可变 `content_ref` 与动作 revision 分开。当前 31 组件均已有受控准备路径；24 个本地组件不生成成绩，其余作答/反馈通过普通单选/Python 或新 response 题包的原 owner 绑定。准入不等于 SQL/多文件执行、自由简答语义评分或全部真实场景通过；逐项边界见界面方案 8.4。
- `presentation_capabilities.actions=["learning_practice.v2"]` 另行声明动作兼容能力，且必须已有 V2 renderer；仅新 Run 冻结 `prepare_learning_practice_composition`。模型先列普通候选，再按本 Run 实际回执中的精确 candidate_id 提议组件绑定。服务端固定原公开题面/选项/起始代码/样例；单选不可改为多选，不同 owner 不共享作答状态。准备、复核与交付均重新检查当前节点、原质量/发布与权限，未交付的准备不生成题目曝光。
- 新准备的每个练习绑定必须有指向自身的 `ArtifactAction`：ChoiceAnswer/TextAnswer/OrderingAnswer 使用 `submit_answer`，LineRangeAnswer 使用 `submit_review`，CodeEditor/CodeDiff 使用 `check_code`。其他 owner 的按钮、编辑器、反馈、提示或演示控件不能代替提交/运行。缺少动作时原准备失败且不留下 presentation/组合候选；历史定义读取和 owner 层原命令回放保留原解释，不给旧工件补造按钮。
- `ArtifactAction(event=cancel)` 始终取消整件工件，`for_component` 不将其变成单题取消；新准备禁止将该事件指向练习 owner。单题取消由宿主在排队/运行时提供，命令固定当前精确 Attempt；同稿重试须明确操作。作者与独立检查按实际作用域核对按钮和说明，历史定义与原回执不重新解释。
- 当前原生 CodeDiff 对固定 `before` 与可编辑当前代码使用可切换的行内增删对照，不提供左右分栏；作者与独立检查按实际渲染说明操作，不承诺组件没有的布局。历史定义、标签和消息保持原样，必要的更正另经原教学回合发布。
- 独立检查将所选准备回执的 `owner_bindings[].source.presentation` 与组合定义一起评审。宿主在绑定组件前显示原题面、Python 公开样例及程序环境/Schema/样例；审核按最终可见内容判断，不要求模型再复制进标签、Explanation 或正文。仍检查原起始代码/选项、矛盾替代、答案和锁定提示泄露；公开样例期望值与实际执行回执、成绩分别对待。
- 交互质量修订保留前次回复、原问题及精确选中的 `previous_preparation`：只从本任务前次实际作者输入的成功工具回执中匹配 `exact_handle`，带回该定义、原题绑定及私有提示，供定点修订。私有提示继续留在作者/检查上下文；新定义仍走原准备、检查和接受事务，既有候选、负面报告与调用记录保留。
- `learning_responses.v1` 是独立新能力：仅新 Run 获得 `list_learning_response_candidates` / `prepare_learning_response_composition`，从已发布 `kind=response` 题包列出多选、预测、参考型简答、排序及逐行定位；原列题工具不混入新 source kind。旧 Run 不升级，直接 V1 candidate/交付拒绝响应型源。读取带这类绑定的 V2 详情须另声明 `response_capability=learning_responses.v1`；旧读者得到明确不可读结果，公开摘要/取消仍可用，不给旧标签页返回不认识的题面结构。
- response 作者/盲答/六审仍使用原任务链与精确材料许可。题包私有参考和 findings 不进入盲答/候选；排序和逐行代码的公开初始身份不可改，批注状态必须为空。多选/输出/排序/行定位使用固定比较规则，简答仅保存参考，不新建语义评分服务。含参考型简答的 `blind_passed` 保持 null；发布须完整盲答格式/其他机械比对与原六审，不称参考已被机器认证正确。新 response 题包未取得原概念/Python Gate 资格。
- `learning_code_review.v1` 单独冻结 `prepare_learning_code_review_composition`，不暗授供题、作答或运行工具。原 `attempt` focus 须指定同节点/计划版本、已完成且公开的普通 Python 提交；服务端从原公开评价/Attempt 填入完整只读 `CodeBlock` 和 `submitted-code-review.v1` 绑定，模型仅提供指向该组件的逐行精确引文/教学意见。原独立教学检查校对完整程序、原任务/结果和建议，不把执行异常当作学习者错误、不产生新评分。批注经 exact_handle 接受后才同事务写原辅助/曝光，未选中、失败或取消的准备不曝光。新 Attempt 不改指旧批注，原评价文档/评分不被改写；修订/运行仍在原工作区。含此绑定的详情须另声明 `code_review_capability=learning_code_review.v1`，不支持者只保留摘要/取消；旧冻结 Run 不增权。
- `learning_code_review.v2` 为新 Run 替换 v1 能力，冻结 `prepare_learning_code_review_composition_v2`，准备 `submitted-code-review.v2` 并沿用完整原提交检查。两个 review 版本互斥，动作能力上限仍为七项。新绑定增加显式 `complete_review`；详情通过 `review_reports` 投影状态、可用动作及已保存时间，空列表省略。v2 读取能力兼容旧 v1 绑定；v1 读者须先升级才能读取 v2。旧工具、绑定与 pending 请求保持原合同。
- `learning_programs.v1` 单独冻结 `list_learning_program_candidates` / `prepare_learning_program_composition`，只列精确节点已发布普通 SQL/项目的公开内容。原始 program 候选只能绑定到组合，不准入旧直接交付；SQL CodeEditor/CodeDiff 固定起始查询，项目 CodeEditor 的 files 状态固定完整清单、顺序/只读标志和受保护内容。可动态混合其他组件/业务 owner，但每个 owner 都须本 Run 的独立能力及实际列材回执；不能借新能力升级旧工具或混用作答状态。只有准备组合的 exact_handle 可经过原独立检查/CAS 原子交付；未交付不曝光。详情另协商 `program_capability=learning_programs.v1`，旧读者保留摘要/取消。宿主沿原状态端口提交 query/files，区分公开参考与所有者投影的实际样例表格/整数，复制 Schema 名称不插入、不运行；各稿、取消/重试、历史与草稿沿原身份。
- `learning_direct_answers.v1` 是第五项独立动作兼容能力，仅新 Run 冻结 `prepare_learning_assisted_composition`。每个普通 owner 仍分别要求原 practice/response/program 能力与本 Run 实际列材；不能借辅助扩大旧文件预算或取得程序权。准备/原独立检查/exact_handle 交付只固定 `practice-direct-answer.v1` 标记，不读取或携带答案，未交付不写辅助。原生宿主按该绑定提供精确用户辅助控件，不接受模型事件回调、答案或评分。含此标记的详情另须 `direct_answer_capability=learning_direct_answers.v1`；旧读者保留摘要/取消，旧 Run/工件不升级。
- `learning_hints.v1` 为第六项独立能力，仅新 Run 冻结 `prepare_learning_hint_composition`，各普通 owner 仍须原能力与实际列材。H1 概念/H2 策略/H3 下一步的私有系列保存在原 Tutor presentation 并参与既有内容身份；实际工具回执作为原独立教学检查输入，不作为公开工件正文。严格用途/顺序及不同文本不等于正确性/渐进性认证；检查须拒绝拆段解释、泛化占位、完整答案和公开泄露。只给被明确请求的级别创建原 Assessment/ItemBank 事实，详情另须 `hint_capability=learning_hints.v1`；不增加任意模型事件端口、组件或配方，旧 Run/读者不增权。
- `learning_demo_events.v1` 为第七项独立能力，仅新 Run 冻结 `prepare_learning_demo_composition`，绑定既有 AlgorithmPlayer/StepPlayer/SequenceDiagram/IsolatedPreview。服务端从组件推导闭合事件，仍经原独立检查及 exact_handle 原子交付；混合 owner/提示须各自能力与实际列材。详情另协商 `demo_capability=learning_demo_events.v1`，旧读者保留摘要和取消；不增加任意回调、配方或第 32 个组件，旧 Run/工件不升级。
- 新支持动作的教学 Run 可冻结 `request_learning_practice_supply` / `get_learning_practice_supply`，为当前精确确认节点登记原供给任务。response 的两道普通练习格式固定，作者/修订不得换型；kind 仍受对应原动作能力限制。排队不在当前 Run 中嵌套作者，协调器待前台让位后经原作者/盲答/六审/发布推进。模型须结束回合，不循环等待；后续学习者回合读状态、列实际候选、准备/检查/交付，既不将 task_id 当候选，也不增加主动教学。任务保留发起 Run 的配置作用域和取消关系，UNKNOWN 不重发。
- 独立 `native-server.mjs` 只接回环 Leornian API，以真实本机会话的 HttpOnly / SameSite Cookie 代理原公开合同与 SSE，忽略前端伪造的 Authorization。它复用固定完整客户端，不连接上游后端；旧入口继续保留。模型设置按 S05.3 提供独立保存、用途分配和显式测试；其余旧功能继续逐项迁移，当前入口职责和部署见根 README。
- 本机会话刷新沿 Identity owner 续期当前有效令牌七天，同时更新 HttpOnly Cookie；活动壳每 15 分钟及回到前台时核对，隐藏页不保活，卸载中止续期。令牌不旋转，原 Run 的 `session_digest` 保持；已过期、撤销或身份停用不能自动续期。退出撤销当前令牌，迟到的续期响应不能恢复其权限。明确授权的本机维护仅为指定原身份另签新令牌，不复活旧会话；十分钟私有交接由显式配置的宿主处理，原 Cookie 确认后删除。交接不覆盖其他已登录身份，不对匿名 HTTP 开放 actor ID 恢复入口。
- V2 的共享 `playback` 是 0 基观察索引；时序图、算法和步骤条同序，既有计数式 `StepPlayer` 仅在 V2 适配层换算。恢复旧末步计数时显示固定末步，不丢草稿或修改业务回执。工件取消停止自动播放；播放/定位/改参不生成执行、题目曝光或成绩，旧 V1 组件语义不变。
- `GET /v2/conversations/{id}/learning-artifacts/{artifact}/sources/{component}` 只读已接受 `SourceReference`，检查精确历史绑定、当前用途/权限及原范围，返回真实使用/保留截止。`knowledge.material_permission_changed` 在撤权事务提交；客户端先清空当前阅读正文再重新核对，到期也清空，不改读 head 或其他材料。工件内容不可读仍可依据公开摘要提交原取消命令。
- `GET /v2/conversations/{id}/learning-artifacts/{artifact}/actions/{action}` 与 `GET /v1/conversations/{id}/turn-requests/{key}` 只读原已提交回执，不触发重派。宿主发写命令前保存 actor 作用域命令/幂等键；网络不确定保留 unknown，刷新或 SSE 只读同步，显式核对也仅 GET。
- 0033—0044 只在临时专用测试库应用后冻结，提示切片当时源码 readiness 要求 0044。0035 只为普通 Python 训练增加显式多 Attempt 策略和逐次反馈身份，0036 保存组合 owner 绑定与组件投影，0037 保存原 Assessment 的响应型结果、独立 source kind 和组件回执引用，0038 固定原供给请求格式/发起 Run/配置作用域，0039 在原 presentation 增加固定提交审查绑定。0040—0042 只在所属 5452 库固定 SQL/项目题包环境、资格、原 Assessment Attempt/公开样例投影、原执行队列输入及原候选/组件的 program 关联；0043 在新 5453 库新增唯一直接答案辅助事实，0044 在新 5454 库保存私有提示系列及唯一逐级辅助事实，旧 5451/5452/5453 与原开发库/服务不自动升级。旧行不回填样例或辅助，无新 Runtime/评分服务。原生宿主构建、本机身份/目标/会话/SSE、离线模型回归和部分真实 Runner 场景不代替真实模型教学质量、全部组件业务互动或 Tauri 验收。

## S10. 动作、原子提交与结果

统一动作命令包含 `client_action_id, expected_artifact_revision, action, typed_payload`，身份和业务 scope 从当前会话取得。目标动作包括 `respond, run, request_hint, request_direct_answer, complete_review, start_demo, acknowledge_demo_event, complete_demo, cancel`，各版本只开放对应的闭合 DTO。正式 Gate 提交使用其现有整组锁定合同，不能退化成任意单题试跑。

`complete_review` 仅用于已检查交付的 `submitted-code-review.v2`，命令另收精确 `component_id`。当前 scope、权限、原公开 Attempt/评价与固定内容复核后，Tutor 同事务写入唯一 `learner_review_report.v1`、原 presentation/内容身份/Attempt/评价/服务端时间、工件 revision/completed、动作回执和既有工件事件。相同命令回放返回原结果，新命令不能生成第二份报告；取消后保留既有确认。它记录学员阅读确认，原 Assessment 结果和正式进度保持原记录；即使会话启用 `after_result.v1` 也不产生教学意图。Native 在原逐行批注下提供明确控件，时间只取已提交事实，UNKNOWN 仅核对原动作回执。0049 在新所属 5458 安装后冻结，当前源码 readiness 要求 0049。

演示续接另外实现明确的 `start_demo`：只有新 Run 冻结 `learning_demo_events.v1` / `prepare_learning_demo_composition`，并经原检查及 exact_handle 原子交付后，宿主才可对绑定的 AlgorithmPlayer/StepPlayer/SequenceDiagram/IsolatedPreview 开始记录。服务端推导闭合事件（timeline_end/preview_snapshot），不把这些命令加入模型可自造的 ArtifactAction 回调。开始动作只保存本端口的已明确提交输入快照并签发代际/nonce；登记 sequence 1 校验末步/预览，完成 sequence 2 还须另行确认。八种算法的服务端端点计数与实际前端轨迹定向对照，未实现通用执行器或防伪可见时钟。

`tutor.demo_observations/demo_completions` 与原工件动作回执、revision 和事件同事务保存；旧完成不被重开覆盖，取消/运行/旧版本/旧 nonce/撤权不能继续写。报告标记为 `learner_demo_report.v1`，既不是可见时间、理解或独立掌握证明，也不产生 Assessment Attempt、执行、评分或自动教学意图。混合 owner 保留各自能力/列材及原分数；原 owner 完成仍须等待未完成的演示，纯演示不能借用 program 文件预算。详情另须 `demo_capability=learning_demo_events.v1`，初始最近五份，更多历史通过 `GET /v2/conversations/{id}/learning-artifacts/{artifact}/demos/{component}/completions?before=&limit=&demo_capability=learning_demo_events.v1` 分页；GET 沿原材料 share-lock 检查当前权限，不写新事实。

0045 仅在新所属 5455 测试库安装后冻结，该演示切片时点源码 readiness 要求 0045；0033—0044 和旧验收服务不升级。新准备工具的 wire 声明采用紧凑组件索引与按需目录属性，实际接收仍使用完整闭合 V2 DTO/关系校验；六种旧工具声明不变，保留原 128k 全能力预算回归。用户另确认的 512,000/声明输出 131,072/倍率 4 只属本轮离线验收配置，真实供应商能力、全部 BYOK Profile 和旧 prepared policy 不由此升级。此处不完成 S11 的单层答疑、续行仲裁或全量真实模型验收。

- 同幂等键同输入返回同业务结果，不重复执行；同键异输入冲突。过期版本不调用 scorer 或 Runner。
- `request_hint` 只收精确组件、原动作身份/CAS 和 `level=1/2/3`；只允许下一层，不接提示正文、答案、pack/slot、测试、分数或执行输入。已检查系列在当前计划/材料及非考试、非运行/取消状态下释放；原 Assessment 的逐级事实、原实际曝光、Tutor revision/event/动作回执同事务提交，失败均回滚。GET/回看/刷新不写辅助或重发命令，后续级别不换系列；不作答、运行、改旧成绩或生成正式进度。直接答案始终是另一个明确动作。
- `request_direct_answer` 只收精确组件和通用动作身份/CAS，不接 caller 的答案、pack/slot、测试或执行参数。仅已检查交付、当前材料/计划仍合法且不在运行/考试中的普通槽可请求；原 ItemBank 返回原已审答案/解释，Python/SQL/项目引用原已资格验证盲解程序，不返回私有测试/输出。原 Assessment 辅助、原实际曝光、Tutor revision/event 及原动作回执同事务提交，失败均回滚。请求不创建作答/Attempt、不覆盖原成绩；原操作后续仍可明确作答/运行，辅助事实保留且不授予独立证据。GET/重看不重写，不以结果未知授权重发；回执仅回身份，正文读取仍重验当前权限。
- SQL/项目的 `run_program_component` 仅接原 typed query/files、精确父 Attempt 和显式 retry，不接环境/测试/评分/命令。原 Assessment/执行的排队与最终回调同事务更新组件、原反馈和事件；原普通 API 创建新稿也沿同一绑定，不在 Tutor 复制成绩。取消精确匹配当前 Attempt，取消后迟到不改指新稿；同稿只在 error 后显式重试，普通通过不等于正式 Gate/掌握。
- 旧 files 准备/读者仍按每文件 20,000 字符解释；较大文件只在含实际 program owner 的专用准备中准入，且保持项目合计 100KB 与独立 program 读取协商，不将新文件预算隐式授予旧 Run/读者。
- 普通练习的 `run` 原子创建 Attempt/执行任务，异步执行后由 Assessment 判定；不把 exit code 当通过。修改后新 Attempt 仍保留旧结果。
- Run 通过即完成对应练习，不要求第二次 Submit。正式 Gate 仍需明确开考、独立性和整组一次提交；训练入口不能打开考试试跑旁路。
- 教学发布事务保存 Tutor message、工件、timeline item、教学版本/CAS、Turn 终态和 Outbox；任何一项失败不公开半交付。调用/生成发生在事务外。
- 操作事务保存动作回执与所有者的业务命令/事件；任务完成事务保存真实结果、评分/证据及后续意图。消息只是已提交事实，不是运行许可。
- 运行/评分事实不依赖讲评服务可用。讲评未完成时可读安全结果并显示“讲评待完成”；不回滚已完成评分，不写假成功讲评。配对讲评与结果条目的一致公开由明确事务完成。
- GET 只读，不在读取详情时发起模型、代码执行或重新评分。Worker 处理终态投影与后续意图。
- 工件动作和旧业务 API 共用业务幂等/资格检查，不能因双入口产生两个 Attempt 或绕过 Gate。

V1 动作仍为 `respond/run/cancel`，普通单选和 V1 Python 保留原一次锁定及旧回执。V2 组合另含 `respond_component/answer_component/run_component/cancel_component_run`，使用 `client_action_id`、`expected_artifact_revision` 和严格 payload；组件绑定决定原 pack/slot，不接用户分数、测试或运行配方。多个原 owner 独立投影，直接业务 API 写入的结果不伪造工件动作身份。`answer_component` 的多选为精确 ID 集合，预测按已公布的 lines-rstrip.v1 对照、无输出须明确确认，排序为完整 ID 排列，逐行定位只比行号且明确理由未评分；简答 `correct=null`，不是失败或通过。锁定回答/参考及反馈曝光不依赖讲评模型可用，也不写正式进度。

`python-practice.v2` 只允许普通训练：新代码精确指向最新且已终止的父 Attempt，保存独立代码、原固定测试和成绩；同代码仅在 error 后显式 `retry=true` 新建尝试。旧 Attempt 不被改分或替换。最新训练决定当前训练资格，资格执行、后继、正式 Gate 仍为原一次性策略；旧在途 V1 不因关闭组合而增授取消权限。取消 V2 普通执行后保留 error、迟到回执和原身份，显式重试另建 Attempt，不宣称物理立即终止。完成整工件取消后不得由迟到结果复活。completed 仅表示交互/该次练习结果，不写正式 Gate 进度。

## S11. 丰富工件、辅助与教学编排

左侧「题库」以当前学员的路线、精确修订与节点为索引。`GET /v1/plans/{plan_id}/question-bank` 返回本版全部节点，以及生成过题包的历史节点；`GET /v1/packs/{pack_id}/generation` 只读取本人的阶段回执。公开说明是各角色在同一次输出中选取的检查或发现，历史回执没有该字段时只显示已有结果。作者题面、盲解程序、评审私有理由与隐藏用例不通过过程接口分发。打开已发布练习走原题型的公开题面接口并记曝光；浏览目录和过程不触发生成、作答或评分。

| 类型 | 交互/结果规则 |
|---|---|
| 知识检查 | 单/多选、预测、排序、代码范围、简答按各自评分 Profile；未验收的 scorer 不可宣称独立通过 |
| 代码练习/执行结果 | 对话内编辑、显式 Run、可见反馈、返回修改；隐藏测试/答案不公开 |
| 代码评审 | 基于当前提交与受控任务，问题定位/解释/修订有版本与结果引用，模型评价不自动变为编译或 Gate 成功 |
| SQL | 明确方言，隔离数据；宽屏编辑器/Schema 两栏、结果下方，窄屏堆叠；复制名称不自动插入 |
| 演示 | 已发布步骤/期望事件；当前学员报告有代际、nonce/序列约束，不认证可见时长、理解或独立掌握；防伪可见时钟未实现 |
| HTML/CSS | 预览隔离于主应用 DOM/宿主权限，限定桥接/资源；新准备的可编辑预览必须有指向自己的 `ArtifactAction(event=preview)`，编辑或演示报告不自动更新画面；预览不代替显式检查或 Attempt |
| 来源定位 | 绑定 document/version/block/范围/内容身份，右侧阅读并稳定定位，不创建新的学习工作区 |

交互引入的最终选择使用完整 `LearningReply` JSON，`exact_handle` 只能来自当前 Run 实际成功回执；介绍和说明放在 `text` 内，不将选择 JSON 粘在普通正文或 Markdown 围栏中。带交互合同的混合格式及无顶层交互的最终分片中嵌入可识别的选择对象时应进入原已知格式修复；封装含未转义换行或缺尾括号时也不能降为普通文本。不提取 JSON 自动挂载，也不提前公开；普通无交互文本与未声明交互合同的旧冻结角色保持兼容。审核区分异步文档任务与检查接受后同事务公开的交互，按其实际发布时点检查引入文案，不要求学员批准发布或展示私有待审流程；不因此补造执行、评分或掌握回执。

可编辑预览的更新动作检查只约束新准备记录；`CodeEditor/CodeDiff` 实际写入 HTML/CSS 状态时才要求本预览的明确动作，其他预览的按钮不能代替。更新仅重绘本地隔离画面，不向服务器登记事件或确认完成，按钮标签和介绍也不得混同这三种动作。只读编辑器和静态预览不被强制增加动作。历史内容读取及同键原准备回放保留原解释，不追改已接受定义、草稿、浏览完成或原外部回执。

H1—H3 按序解锁并记录唯一 assistance receipt；直接答案是单独动作，只展示获准的答案/解释，写入辅助和实际曝光。回看/重放不重复写；辅助后成功不能成为无辅助独立证据。新情境后继沿用原未见候选、完整审核与关系检查。

当前已接独立直接答案能力及单选、Python、五种 response 与 SQL/项目的原发布参考；H1—H3 也已通过独立能力、私有准备/原检查、按序明确动作与只读宿主接入同九类普通题源。记录保留原题目版本、公开/系列身份与明确交付时间，不重写先前评分；不把原解释切成三段、把直接答案改名为提示或以本切片代替完整辅助资格。新 8094/5184 与 5454/0044 的局部原生对话验证三层提示、独立直接答案、B 草稿及刷新去重；随后明确提交 B 仍为错误、五个动作、正式进度 0。私有审查的待补充摘要不公开锁定内容。九类题源后端回归、宿主 DOM/类型/构建、真实浏览器与离线模型/真实供应商质量仍分别记录，不称全部辅助场景或阶段完成。

2026-11-06 起，WP08 的显式会话、单层答疑及原生呈现已部分实施；随后新增显式同意的结果续行。演示报告默认不产生教学续行：

- `open` 显式启用，旧会话不追认；新教学请求携带 `teaching_session_revision`，原受理请求始终按精确原输入只读重放原 Run/Task。会话保存 `guided/free_reading`、暂停、精确 focus、revision/generation 和活动分支。
- 闭合 `open/set_mode/pause/resume/return_to_main/set_topic` 校验命令身份/CAS，保存不可变回执；控制不创建 Turn/模型调用。已有 queued/running/blocked_unknown 前台 Run 时先完成或由用户明确取消，不隐式替换；暂停引导仍允许明确提问。
- 待工件时新教学问题由服务端选择与明确 focus 相同的最新主线待办锚点，活动分支复用且只有一层，不从措辞改主题、猜组件或接受客户端锚点。答疑 Run 只冻结 read 工具，原作者/独立检查/接受事务不变，禁止 `interaction=artifact` 替换主线。
- 主线历史排除分支；答疑历史限本分支和原锚点公开消息，context 仅含锚点公开/已释放内容，不搬入其准备工具或私有推理。锁定 H1—H3、私有答案/测试不因提问释放。实际接受后按整件工件的真实原练习/提交审查 owner 向原 ItemBank 追加 `artifact_question.v1` 接触事实和唯一回执，不从正文猜某个 owner；准备、拒绝或失效迟到回复不写。纯演示无 owner 不虚构事实，不新增评分、Attempt、正式进度或提示/直接答案辅助回执。
- 明确返回只将分支 `closed`，不声称“已理解”；明确主题切换将原分支 `superseded`，历史/命令回执不删。代际、活动分支、上下文冻结后的锚点 revision/内容与原权限在派发及接受时复核。快照仅补有界会话/分支元数据，完整消息继续原分页；GET 无写入。
- 原生“当前学习与路线”复用现有控件接六类显式控制；原输入框等待当前 actor/会话教学元数据，开启后使用服务端 focus/revision，未开启保持旧合同。读取失败不当作旧会话许可，未决控制或前台 Run 阻止新冲突命令，草稿保留；SSE 刷新和迟到读取有原身份/会话边界。
- 消息桥接在原身份与归属检查后读完公开 history 分页，保留原 message ID、角色、parent 链及 `teaching_branch_id` 的公开投影；后页失败不降为半段成功。单层分组仍委托原 Row/Markdown 渲染，活动展开，明确返回/主题退役后折叠为“答疑 · N 轮”，历史可只读重开，用户右侧/Tutor 左侧不改；没有新增组件类别或评分权威。
- 0046 仅在新所属 5456 测试库安装后冻结，该会话切片时点源码 readiness 要求 0046；独立 8096/5186 实际验证六类控制、同锚点两轮答疑、暂停后提问、主题退役、B 草稿及刷新恢复。最终 session revision 8、六个控制回执、三份接触，工件 ready/revision 1，无已释放提示、作答/Attempt/正式进度；实际 391 像素窄屏无页面横向溢出。旧库/服务与 5180 不升级；模型仍为离线 HTTP，不以本组浏览器或原生测试完成供应商质量、Tauri 或持久续行仲裁。

续行设计顺序为用户消息 > 显式工件动作 > 期望结果/交互事件 > 定时 > 后台。2026-11-06 的结果切片已实现前三类的持久准入/仲裁；未预建定时/后台生产者，不据此完成 WP10：

- `set_continuation_policy` 显式选择 `manual/after_result.v1`，旧会话默认 manual。只有引导模式下已提交 choice/response、完成的 Python/program 结果与明确 demo completion 才由原 owner 事务写 `teaching_intent`；运行排队、start/末步、阅读、准备及 Tutor 回复不生产意图。唯一触发引用、一个原 Run 和原命令回执限制重放，UNKNOWN 不变成替代派发授权。
- 原 relay 有界扫描；同会话前台、活动分支、暂停、考试或较高优先级意图等待，等待行延后复查以免饿死其他会话。新的明确消息/动作/控制优先通过原取消链接管自动 Run，不抢占普通用户 Run，旧键重放不接管。原 Run 先于会话/工件写锁，接管与新输入准入同事务，无效输入不会提交取消。
- 新 `continuation_generation` 在模式/主题/策略变化时撤销旧待办，暂停/恢复/返回保留队列；已派发仍受原 Session generation/Runtime lease 约束。原精确源工件/内容、最新结果或 demo 代际、原计划与材料权限及冻结源 revision 在派发/接受时复核；新代际/Attempt 不拿旧结果继续教学。
- 认领复用原 Turn/Run/wakeup、作者/独立检查、候选 exact_handle 和原子交付，复制原工具版本和模型配置作用域，同用户当前配置仍须有效。源结果只用公开视图，不搬入旧准备协议/锁定提示，不代答、执行、开考、确认路线、改材料或写正式进度。Turn 的可空 `teaching_intent_id` 是服务端来源；Native pending 不投影，接受后只有原助手正文/ID/真实 parent，不伪造用户消息。
- 原菜单接默认关闭开关和模型用途说明、最近 20 条 scoped 意图/原 Run 状态；精确取消保存原 `client_action_id` 回执，UNKNOWN 只读核对不重发。新增 20 项专项分批、原影响范围 104 项、81 Node + 77 DOM、严格类型/合同/Ruff/独立构建通过。8097/5187 的真实 API/数据库/Runtime/SSE 已验暂停提交 B、返回/恢复后唯一续讲及刷新恢复，原错误评分和零正式进度不改；391 像素窄屏无横向溢出，默认视口恢复。
- 0047/0048 仅安装并冻结在新所属 5457，源码 readiness 要求 0048，旧服务/库与共享 renderer/CSS/演示/5180 不动。作者/检查仍离线 HTTP，浏览器由显式原仲裁扫描/AgentLoop 驱动，不代替真实供应商、broker/常驻 relay、Tauri、完整主动教学或全场景验收。

**节点讲解的前台节奏（0071）。** 5180 逐节点提交 `TurnInput.node_pacing=true`，Tutor 的作者与独立检查共同使用 `PacedLearningReply`。通过检查后，正文、交互与 `pacing` 一起提交。`next_step` 取 `can_continue / wait_for_reply / wait_for_action / wrap_up`；`resume_at` 保存未讲完的主线，`check_topic` 标记主动确认过的卡点。后续回合按确切节点读取停点与已确认主题，重复确认退回修正。沉默开场仅允许讲解或收尾，用户提问或主动要求实践不受开场限制。

学员说“先跳过”或重新要求练习时，`practice_choice` 附当前本人消息的原话。节点内后续回合复用最近的决定；学员已暂缓练习时，自动回合不得再次要求做题、运行或贴结果。自动回合使用公开学习记忆和停点，不把先前回复搭成缺少原始推理的模型对话，也不冒充学员补一句“继续”。

讲解直接回应眼前的问题或代码。只有影响学员下一步时才说明限制；作者与独立审核都不把“你只需要……”或边界说明当作固定结尾。学员纠正老师时，承认具体错误，说明正确事实；是否展开由学员眼前的问题决定。轮到学员动手时，改示例用可编辑代码，观察变化用预览或分步演示，评分练习用绑定原题目的工作台。`wait_for_action` 对应已选工件、当前答疑所依附的工件，或确实在准备中的题目或环境。只想思考或阅读用 `wait_for_reply` 静候。

**复用教学工件。** 客户端声明 `learning_templates.v1` 后，Tutor 优先用 `prepare_learning_template` 选代码工作台、网页预览、分步演示、选择、排序、随记或代码批注，传入本节内容。服务端组装已有组件，原独立审核检查选中的完整工件。选择、排序、随记和批注保存在学员本地草稿；需要正式提交时仍使用已发布题目的原工件、原题面与原评测入口。自定义组合用于现成工件不能表达的教学活动。

**编辑器试跑（0072/0073）。** 自由示例的工作台显示说明、编辑器和终端；已发布练习显示题面、测试用例和评测结果。已有单文件示例打开时保留原稿。客户端声明 `learning_example_runs.v2` 后，点击「运行」以当时的草稿在路线许可的本机隔离环境里启动一次程序。终端显示实时输出，学员可按提示逐行输入，也可以停止。例如分钟换算先输入 `65`，看到换算结果后再输入 `q`；示例输入只作参考。终端按运行标识恢复，重新运行打开新的记录。每次试跑最长 180 秒，不创建作答或成绩。

面板、Tutor 和独立审核共用 `example_run_surface`。v2 先运行再输入，需支持交互的本机 Runner；v1 客户端仍在运行前一次填写多行，原有回执继续可读。卡片的 `example_runners` 决定哪个编辑器、哪种语言可用。编辑器内追问按本人、会话、卡片、版本和提问时点读取已回报的试跑；按组件、语言、阶段、结果和退出是否成功分组，给出次数及最近回执。

教学中的自由示例成功运行后，代码自动供本路线的 Tutor 接着使用，工作台不显示分享选项。下一个节点在同一会话和路线版本内，优先引用提问前已分享并跑通的作品；没有合适作品时，可引用本节、上一节或先修节点已发布的普通单编辑器示例。`observations.project_state.example_work` 标明来源、节点、卡片版本、组件和代码范围。终端输入、输出和诊断不随代码分享。

**完成后自由练习。** 卡片不提供整卡取消按钮。工件完成任务或学员明确结束本节后，仍可改选项、编辑、更新网页预览和重播演示。已发布代码题可用原题的公开样例试跑；自由示例保留交互终端和「停止运行」。这些操作不提交作答、改变原成绩或进度，也不向 Tutor 提供新代码、试跑观察或续教事件。原提交记录可回看。进行中的编程练习未通过或执行出错时，仍可按原流程修改再提交。

纯展示或编辑示例可以承接就地答疑。学员显式返回主线后，示例和草稿仍在，下一次发言不再自动回到该示例的只读答疑。仍有原作答、评审、提示或演示报告动作的工件保持原有分支规则。

`TeachingSession.node_window` 按当前节点完整历史投影，没有正文的未完或失败回合、没有节奏字段的旧回合均保持等待。前台仅在首次进入或 `can_continue` 正文显示完毕时计时；到期调用 `POST /v2/conversations/{id}/teaching-session/continue`，附精确 focus、session revision、上一回合 ID（首次为 null）和客户端展示能力。后端串行校验前台、考试、模式与代际，同一窗口只创建一个 `node_window` 意图及原生 Run，无后台定时生产者。未知提交以原 turn-request 查询；新的用户消息可以接管自动回合。`finish_node` 要求实际的收尾回合与显式用户动作，同事务记录本节导航回执并选中下一节点（末节停留）；不评分。

#### 节点教学回合的职责划分（2026-11-23 后端实现）

首讲、追问、纠正、超纲讨论、练习反馈和收尾采用同一条交付流程。流程约束的是谁提供事实、谁作教学决定、谁可以修改结果；不规定老师每轮怎样说话。沿用现有 Tutor、业务模块、Runtime 和独立审核。

| 环节 | 输入与产出 | 谁作决定 |
| --- | --- | --- |
| 准备本轮事实 | 学员原话独立传递，自动触发保留来源。`node` 放目标与停点，`history` 区分学员自述和已交付教学，`workspace` 放工件及可用操作，`observations` 放业务回执，`materials` 放材料依据。 | `TeachingContext` 按本人、节点、版本和时点汇集事实。分支可引用原工件的公开教学；显式回主线可接回同节点最近关闭分支的公开对话。旧推理和准备工具对话不进入下一回合。 |
| 作教学决定 | Tutor 在同一候选中分别给出正文和交接决定：是否使用已有或新准备的工件、接下来谁行动、主线从哪里接回。当前疑问答完即可；值得深挖时可连续讨论。 | 怎样讲、何时回主线由 Tutor 根据对话判断。可用控件来自客户端能力和工件实际状态。模型可以邀请动手，执行和评分仍由原业务模块完成。 |
| 校验与修订 | 正文、交接决定和工件引用分别校验。可唯一确定的字段由程序补齐；缺失字段或字段值不符合合同时，固定已校验的正文和决定，只把错误路径、原因和允许值交给 Tutor 修复。例如操作说明写进 `next_step` 时，只需返回这个枚举字段。正文与动作冲突则重新审核内容。 | 交付层只合并尚待修复的字段。独立审核读合并后的完整候选、学员原话和相关证据；有内容问题时指出具体位置与依据。 |
| 一次交付和接续 | 审核通过后，按原提交路径一起交付正文、真实工件与节奏。下一轮能区分“教过”“学员说过”“实际运行过”和“正式评估过”。 | 前端用已提交的节奏决定是否开启插话窗口；交接尚不明确时保持等待。暂停、学员接手沿用原仲裁，结果未知的调用不重发；沉默或执行示例不写掌握。 |

运行权限、评分方式和控件可用性由系统执行并在相应界面呈现。只有这些条件会改变学员眼前的操作，才需要在教学正文里解释。例如，学员在问循环为何提前结束时，老师讲循环；学员要运行代码时，交付能运行的编辑器或说明眼下缺哪个条件。

Tutor 用学员能看到的代码、控件名称或表格内容说明改哪里、怎么改。首审检查完整正文、所选工件与下一步动作。若工件和动作正确，只有操作说明写错，审核用 `candidate.text.operation:` 标出可唯一定位的原文。Tutor 只替换这些片段；系统保留其余正文、工件和节奏，修订阶段没有工件准备工具。独立复审读取合并后的完整答复、原工件、原问题及改动，核对原退回项和改动造成的事实、操作或提示泄露问题。涉及工件、交接或其他内容的缺陷，以及定位不唯一的退回，沿用完整修订和审核。审核通过后才一起发布。

普通节点已有本节获准使用的教材绑定即可开讲；没有绑定时，RAG 从本阶段教材选读相关章节。语义检查已经找出可用段落时，备料以 `ready` 交给 Tutor，原覆盖结论仍可为 `partial`，未覆盖项继续保留。只交付通过检查且未被标为有缺陷的片段，不再为凑齐基础概念或同款示例追加搜索。补搜耗尽时，Tutor 用已有教材或自拟示例回答能确定的部分。

课中碰到具体版本或指定出处，Tutor 可调用 `lookup_public_teaching_fact`。当前目标允许公开来源、本人教学角色启用了支持联网的 DeepSeek 连接时，Runtime 才向同一连接单独发送公开问题片段和必要的技术名词。DeepSeek 返回的来源、摘录和有归属的结论作为本轮工具回执交给作者与独立审核，不混入学员原话。普通讲解和原创示例按正确性、相关性及实际控件审核；版本断言要对得上所问的功能，指定引文要对得上原文。已知无结果就继续讲能确定的部分；结果未知时保留原调用等待核对。

学员从工件答疑显式返回主线时，如果本节点最新已交付的答疑已收尾，主线沿用这次 `wrap_up`，直接显示结束本节的操作。普通答疑返回原停点，切换节点仍由学员选择。

**上下文与成本。** 作者与审核使用同一回合冻结的事实。作者可以调用业务工具；`learning_get_context` 只传相对初始快照变化的字段路径、值或删除操作。审核请求先写适用的固定规则，再写本轮必查项、材料、节点和工作区证据，最后写完整候选与调用 ID。交付工件时保留所选工件的定义、原所有者绑定及必要的防泄露依据。若多个检查指出同一位置、同一证据和同一改法，原审核回执保留各项判定，作者只收到一次这条修订要求。

节点审核的调用快照记录 `review_scope`：首审与涉及事实、工件或交接的完整复审是 `full`；只改已定位的操作原句是 `operation_impact`。支持低推理强度且启用思考的 DeepSeek 连接在后一种复审使用 `low`，正文和输出预算保留。分析耗时时，按范围分别统计有回执的输入缓存命中／未命中 token、生成与推理 token、耗时及是否再次退回。

**切换与验收。** 创建新的节点或作答反馈教学回合时固定内部版本 `node_turn_contract=1`；已创建的任务按原合同消费回执。对外仍使用原回复合同与 5180 交互。完整 JSON 的外层代码围栏、已明确选定的工件和可唯一推导的交接字段在本地组装。需要补决定时按字段名合并，正文和已有决定不可替换；缺正文或内容冲突走内容修订，新候选重新独立审核。按学习行为验收：用“那换成双引号也行吗？”“这题先跳过吧”等自然输入，检查是否接得住追问、能回到目标、等待操作时不催。模型效果与费用按同类真实新回合分别记录教学质量、从提交到可读的时间、调用次数和整轮命中与未命中输入。

### S11.1 路线讨论的持久约束

2026-11-09 新增 `0060`，由 Tutor 的 `tutor.route_requirements` 按会话保存学习目标、已有基础、可用时间、包含范围、排除范围和偏好。每个用户事实附原 `source_turn_id` 和逐字 `source_quote`。0066 起路线讨论只使用已确认事实；建议附理由等待用户选择，不创建学习者假设，`PlanDocument.assumptions` 留空。

- 路线讨论的 `RouteDiscussionReply.requirement_updates` 只更新指定字段，省略字段保留原值。后续明确改口覆盖旧值，明确撤回可置空；存在歧义时保留原值并澄清。
- 当前约束及尚未归纳的用户消息进入必需上下文，与最新完整路线一起冻结到原交付任务。普通对话历史仍可按预算裁剪，不裁剪持久约束。已有会话在下一次正常讨论中读取其已完成的目标级用户记录，无额外后台模型调用。
- 候选校验要求更新引用本次实际供应的用户消息及原文；原独立交付检查核对提取完整性、修改依据和合并后约束下的路线可行性。未通过的候选不写约束；接受时以原冻结 revision 在同一事务保存约束、回复及可选路线草案。
- 创建目标后，无模型的首条问题交给所属会话草稿，结束创建状态；旧的已创建且未派发规划的记录可保留草稿后让出新目标入口。未决提交仍使用原键只读恢复。
- 重新进入首节点先核对未决动作、读取当前教学会话，再为实际需要的新切换生成新 `client_action_id`。原首轮教学按原键读取，不重复派发；路线确认仍须用户明确操作。
- 同版本确认回执确定后，确认按钮立即禁用并显示“路线已确认”，不再兼作首节点入口；实际返回节点使用路线文件夹。已确认版本及本机保存的原确认结果阻止重复启动，未决首轮请求只读核对；新草案 revision 保留独立确认入口。

2026-11-10 显式制定计划与增量资料（0065/0066）：

- 同一 `RouteDiscussionReply` 的 `rag_intent` 动作是 `none/prepare/supplement/revise`。非空动作需要规范化目标、主题、理由和逐字用户证据；不增加假设。原作者和独立检查共同审核，不另开每轮分类调用。
- 讨论使用 `preparation=initial/incremental` 小批次，按原阶段完成有效正文、可定位引用、版本与权限检查，相关官方正文与已就绪用户教材联合检索；不在信息收集期间审核全路线覆盖。`planning-batch-evidence.v1` 只表示选中批次可用。用户发起制定后，由原计划审核检查完整约定范围及节点依据，只为具体缺口补取正文；之前选中的有效证据继续复用，未变节点沿已有合格审核复用，新增/修改及受影响依赖重新检查。全局需求、可行性和依赖关系继续核对。
- 规范化范围与授权相同的需求跨回合、重新生成复用；活动检索冻结源版本，不因新资料到达另起同范围检查。补充资料沿原文档、索引空间和精确引用复用，已就绪材料继续可用。新的已审核范围可使过时的逐回合整目标消费者停止扩展，保留历史事实。
- 就绪批次合入规划绑定时，命令身份同时固定批次、selection 和当前基线 revision。绑定产生后继后，同一批次按新基线合入，保留原引用与旧命令；当前绑定已包含全部选中内容时直接复用，不增加版本。
- `Turn.material_demand_id` 关联当前批次，`planning_state` 保存已审核的信息完整性、需求版本及材料范围。普通回复完成后不因资料就绪自动续行。信息完整时展示「制定计划」；按钮使用 `start_plan/expected_requirements_revision`，用户原文明确发起也可启动。只有显式请求的未交付计划才等待 RAG，在思考步骤显示实际等待；资料就绪后交付完整草案，用户另行确认才开始教学。
- 0065 的历史 `Turn.stage_replies` 保留稳定消息身份与独立思考快照，后续任务只更新自己的步骤。刷新和 SSE 重放不另发消息，取消后的任务不被 RAG 重新唤醒。
- 阻塞以正文和「修复并继续」呈现，实时回复与历史消息都挂载同一动作区。`POST /v1/conversations/{id}/material-repair` 先诊断和本地核验回执，恢复原材料需求与原规划任务，不制造新的用户发言。已知无效搜索回执、失败提取自动切换原站；已授权的官方目录按本次目标组合基础语言、依赖工具与框架入口，仍保留各来源自己的主题、版本及 URL 前缀。配置变化只重建已知未发送或已明确失败的尝试；UNKNOWN 先核对。已明确请求的规划仅因资料阻塞而产生的诊断正文不视为路线交付，资料就绪后自动续接原任务；普通讨论、已交付路线、取消任务及更新请求之前的旧阻塞不自动恢复。相同资料和相同缺口没有新进展时停止自动续检，要求补充来源或修正配置。
- Tavily 使用本人受保护的配置，`GET/PUT /v1/material-search-configuration` 以配置版本保存，读取不回传 Key。已有资料优先；定向搜索限制在已授权域名并复核 URL 前缀，只有选中页面才提取正文进入 RAG，搜索摘要不作证据。图文转回原站获取；深度仍是一跳及明确缺口二跳。所有搜索/提取沿原外部调用账本先保存回执再应用。
- 进度 `preparation/goal` 标明本批用途和范围；当前计数包括实际检索冻结的 `source_versions`。显式整份 HTML 的未解决图文停在识别步骤；自动任务选中的可用文字可按下述局部范围参与检查，未解析区域保持可追溯状态。

2026-11-14 自动选材与纠错（0067）：

- 准备顺序固定为当前用途获准的合格材料及检查复用、内置候选目录、缺口定向联网搜索。目录按语言、框架、主题、版本说明、正文语言和访问观察限量排序；登记并获取选中的条目，不让后台扫描器提前抓取整个候选清单。官方、原作者和社区译文依据实际正文检查，目录身份和搜索摘要都不充当正文证据。
- `GoalMaterialScope.authorized_public_sources` 是可选且默认关闭的扩展许可。connected 新目标启用公开资料自动准备；旧目标、原请求键和未决请求正文不附加新许可，仅官方目标仍可复用目录中的官方入口。未知确认与外部调用只核对原回执。
- 规划 `initial/incremental` 批次也进入独立正文检查；`complete` 规划检查技术选择、版本约束、前置知识和学习顺序。课时与题包按自己的目标补齐详细解释和例子。检查返回来源问题及 `missing_topics`，错误、不适配、无关和无法核实的已记录片段不参与下一批；原结果保留。
- 规划自动获取及补建来源使用 `MaterialDemandInput.index_mode=lexical`，先以精确词法索引的正文完成独立检查，不准备当前覆盖任务用不到的文档向量；后续混合检索按需补向量。该字段默认 `hybrid` 且默认值不写入旧命令身份。正文完整性、局部处理范围与权限检查保持。
- `scoped-source-evidence.v1` 的 `findings` 包含问题、精确 refs、`refs/document` 适用范围、受影响主题和解释；缺陷区域不能作为支持证据。自动、未绑定选择可在排除局部坏区域后重新独立检查其余范围，整份文档缺陷继续整份排除，显式冻结绑定不缩小。聚合必须保留子检查的缺陷、findings 和不确定性，互补的 partial 保留；`supported_topics` 与 `missing_topics` 分别记录本次已支持和缺失的具体主题。公开文章的付费宣传不等于正文访问受限，规划不提前要求完整项目实现或练习级测试。旧合同结果保留，只有同一检查合同才复用原审核回执。
- 相同目标、阶段、用途、计划作用域和有效来源可复用原选择；补充检查按精确片段和模型绑定复用原回执。实时绑定的增补沿原 owner/CAS 产生后继。`required_refs`、显式冻结绑定、旧提交和旧版本不随默认材料扩展。
- 自动 PDF 获取根据书签目录和本次缺口选择最多 20 个新页，实际选择固定在上传请求中，解析、OCR、索引和引用保留原页码。下一章节复用当前仍获准的原文文件和已处理页面范围；显式整份文件请求沿原范围处理。
- 初始额度为 12 个选中资源、两轮搜索，每轮接纳至多八个结果。新增经过检查的可用正文可续配四个资源和一轮搜索，整条自动续接链最多 24 个资源、四轮搜索；没有新证据，仅允许一次有明确未读候选的探索续配。续接规划的新材料批次继承原预算，已知失败仍计入消耗，缓存复用和新获取分别记账；新的显式用户请求才能有独立额度。新发现的安全公开入口进入本人持久目录，不修改随包目录。已知获取失败切换方式或来源，格式无效沿原有界修正，质量和覆盖不足只补缺口。充分即停止；耗尽或检查不可完成则给出具体缺口并结束本轮处理。登录、付费和访问受限内容选择公开替代，学习者不负责选网址、补文档或点击修复。
- `html-main-text.v8` 使用固定版本 `readability-lxml` 对已获得 HTML 本地定位正文，按内部节点身份取回原 DOM 中的选中区域，代码、表格、标题和非文本区域由原结构解析器处理；不直接将库清洗后的结果作为教材。正文 HTML 换行统一为 LF，原文件保持原字节，仓库源码仍走原始数据提取分支。库未选出收敛正文或明确解析失败时，本地原选择器仅回退一次，不触发新抓取或模型调用。正文主区域中的主要语义文章与页面控件、贡献者信息分离。旧解析版本不以“原始字节未变”跳过升级，冻结引用仍保留原版本。自动选中的 HTML 仅有未解析图文问题时，保存精确版本与正文范围 `selected-source-text.v1`，原文档仍为 `partial`，`unresolved_regions` 记录类型、说明、来源及章节/块定位。覆盖检查收到按文档版本去重的区域元数据，不得推测图片或公式内容；缺失区域影响当前目标时继续换源。显式整份来源、其他解析错误、权限及 UNKNOWN 继续沿原阻塞处理。
- 规划预算继承以当前 Turn 的创建时间为界，前后两个批次都属于本 Turn 才建立 `budget_root` 关系。新请求可复用旧合格材料和精确检查，不将旧 Turn 的消耗、探索续配或耗尽状态带入新的自动后继链。
- 新覆盖合同的预算进展按新增已审核 `supported_topics` 计算，只有实际支持证据且没有未限定范围的致命问题才计入；新增文档数量本身不触发续配。命名依赖缺口要求候选的实际标题、路径或主题匹配，泛语言入口不占用定向补源的优先位置。
- 依赖和框架缺口优先选择标题、路径或主题真实匹配的候选，公开搜索结果不继承用户目标中的框架标签。作者与审核提示要求材料目标和缺口仅描述所需教学证据，不加入处理诊断、等待说明、重试文字或预算；目标的大小写、空白、重复主题和主题顺序进行规范化。相同精确来源、目标、阶段和模型绑定的已知负面检查同样复用，解析版本或来源版本改变后重新检查。
- 就绪沿原 `material_ready` 继续已明确请求且仍活动的任务，不创建用户发言；取消、替代与已交付任务不自动恢复。排队的自动读取在原需求取消后不再发送，UNKNOWN 保留原操作，不因换配置或换源重发。
- `source-structure.v2` 将链接目录、文章列表和简短教程入口用于发现章节，保留原始响应但不将目录词条作为教学正文检查。包含实际教程代码的 README 仍可参与正文检查；目录中的缩略图、徽章和短描述不构成教学证据。已有索引的入口通过保存的响应在本地补充结构判断，同一原文和解析版本复用判断；原文档、检查和冻结绑定保留。章节按当前缺口匹配选择，不顺序抓取整站。原 URL 前缀外的同站链接只登记为候选，仅在当前目标已有公开资料许可时另建自己的来源授权再获取，不修改旧的精确前缀。
- 材料叶子检查显式列出预期 `reviewed_refs` 且 `reviewed_parts=[]`，父级汇总使用精确子检查 ID。协议修复指出错误字段及缺陷证据关系，允许删除冲突的支持证据、降低覆盖结论，同时保留已有合法的负面问题和 findings；不能通过丢弃负面结论获得通过。同一错误修复后仍无效的自动、未绑定叶子检查返回换源路径，失败回执与原引用保留。冻结绑定、权限等待、取消及 UNKNOWN 沿原处理边界。
- 路线独立审核区分 `discussion / plan_request / material_gap / complete_route`。首次从用户原文提取制定请求时，审核准确引文、需求记录和当前阶段陈述，要求 `route=null`；请求记录后在原任务中继续生成。完整节点、前置、时长、来源与环境清单只在完整路线候选中审核。所需检查清单随原外部请求保存，历史审核与修复仍使用其冻结清单。

2026-11-16 路线教材与节点按需准备：

- `PlanDocument.curriculum` 随不可变路线修订保存主教材、补充资料、技术版本和贯穿项目；`PlanNode.curriculum_chapters` 与 `project_milestone` 记录节点选读及项目目标。教材选择来自实际获准材料与已观察的章节目录，引用保持精确文档、版本、块和范围。项目目标与代码约定属于路线安排，实际完成状态来自学习记录。
- 新制定采用模型主导、RAG 定向补证。`curriculum.basis=model_knowledge` 保存模型设计的技术与项目主线，允许无教材或无选读章节的节点；默认 `selected_materials` 保留教材与节点映射要求。已有材料只是可用参考，明确指定原文的要求仍按原文满足，实际使用的引用仍需精确核对。需求确认后不自动登记整路线的材料覆盖任务。
- 作者可同时返回完整 `route` 与真正影响路线成立的 `material_gaps`，独立审核先确认缺口的必要性。原交付任务在 `planning_route_draft` 保留该草案，按具体问题补证后续接原 Turn；尚有阻塞缺口时不写入正式路线修订。没有外部疑点时，模型知识可直接支撑稳定概念、学习顺序与项目设计，经原独立审核后保存草案。用户确认与课程环境授权保持独立。
- 定向缺口批次使用 `planning-question-source-evidence.v1`，仅判断声明的外部问题，禁止自动扩展为主教材、全部课程主题或完整课时要求。来源授权、精确引用、缺陷、UNKNOWN 和取消沿原流程保持；详细教学与示例在对应节点准备。
- `route-planning-evidence.v1` 判断资料能否支持路线的技术选择、版本与先修安排。目录用于判断章节范围和顺序，必要正文用于判断内容适用性；后续课时的完整讲解、代码示例和练习缺失不单独阻塞路线。原独立交付审核继续检查完整用户目标、顺序、时间及关键技术依据。
- 自动完整规划批次已有经过检查且不受已知缺陷影响的可用证据时，以 `usable_for_planning` 允许路线作者先形成候选，原 `partial` 结论、缺口和质量问题保留。路线作者与独立审核判断具体教材、技术选择和先修安排；缺少关键依据才提出定向规划缺口。定向规划缺口与显式冻结材料仍按各自范围核对，发布沿用该次检查。普通节点按本节可用读物开讲。
- 历史检查供新检查复用质量摘要、已支持主题和精确缺陷，不重复携带旧覆盖清单；父级汇总接收本次子检查及必要来源信息。完整旧回执保留在原记录中。
- 完整规划的材料范围从当前已审核用户目标、纳入范围及偏好顺序构建，替换讨论阶段累积的发现措辞。用户已确定的技术选择不再继承旧的“待确认”描述，相同需求不会因各轮主题改写重复膨胀；明确规划缺口仍单独检查。
- 自动排除坏片段后的规划补查继续从剩余正文选择简介与相关代表段落，仅将选中的引用固定给后续检查；不因自动生成 `required_refs` 扩为整份正文。显式材料范围继续逐条满足原精确引用。
- 节点准备优先使用已选教材的相关章节，复用合格正文和检查，缺口再补充其他兼容来源。规划所用代表性段落不限制后续节点只能读取这些段落；旧提交、显式冻结材料和历史引用继续使用各自的精确范围。
- 基础语言、原生能力和框架缺口分别匹配候选；一个缺口出现框架名称，不排除其他缺口所需的基础资料。只有选中资源才进入获取、解析和检查。
- `Plans.curriculum_snapshot` 提供精确路线修订的公开教材快照；原路线没有该字段时保留原合同。新教材选择不自动迁移已确认路线或历史学习记录。

跨节点教学上下文：

- `learning_memory` 从已提交的业务事实按当前身份、路线修订、节点和教学分支构建，包含先前交付内容、学习者原话、评估证据、实际提交代码的摘录及原记录引用。既有会话通过读取原记录获得连续性上下文，不额外派发逐轮模型摘要。
- 已讲过、学习者自述、普通练习、实际执行结果和独立评估分别表达；生成正文与项目里程碑不能写成已掌握或已完成。代码摘录属于其具体提交快照，不推测用户当前文件内容。
- 上下文按容量选择相关记录并标出省略或截断。生成时读取真实课文，发布前重查已使用历史材料的当前许可；当前节点合法材料继续负责新解释的知识依据。候选、私有推理、隐藏答案与评分私有数据不进入记忆。

## S12. 能力证据、复习与主动教学

Learning 按概念理解、执行、新情境应用维护可解释投影。每条证据引用 owner receipt、题目/策略/材料版本、辅助、曝光及时间；不把阅读、工件状态、单次通过或失败替代整个语言能力。历史事实追加，当前适用性可以变化。

复习记录至少有 `review_activity, due_at, scheduling_state, algorithm_version, parameter_version, evidence_kind, source_receipt`。评分/自评、辅助、耗时与算法输入分别保存：

- FSRS 处理记忆调度，不裁定编程能力或 Gate；实现/版本依据官方实现核对后锁定。
- 旧 `again/good/easy` 作为原自评事实保留；新合同如补 `hard` 必须版本化，不虚构旧日志或回算成客观分数。
- 冷启动使用明确默认参数，个人拟合只使用真实可用日志。暂停/恢复、到期与回答幂等。
- 到期活动在对话内展现对应工件；新题要求继续遵守题库、辅助、曝光与评分资格。

0053 的实现固定 `fsrs==6.3.2`、`py-fsrs.6.3.2` 与 `fsrs6-default-cold-start.v1`。期望保持率为 0.9、关闭 fuzzing，完整调度器参数、前后记忆状态、原算法日志及下一到期时间写入不可变 review log。旧固定间隔记录保留原算法标识，第一次新回答才冷启动真实 FSRS，不回算或补造过去评分；继续接收原三值 `again/good/easy` 自评。

动态节点的正式 Gate 证据产生精确 plan/node/source receipt 复习卡；到期活动可在原会话明确展示、回答或取消。Learning 通过 Assessment/ItemBank 的公开投影读取概念、执行和新情境证据，分别呈现辅助、实际曝光和原成绩，不重复写评分事实。

主动教学依据用户允许模式/时段、当前状态和持久触发事实产生意图。自由问答无默认自动连续推进；暂停、前台问题、活动考试及失效 scope 均受尊重。每个触发事实最多消费为对应一次意图；没有新事实时不无限自我发问/续行。不能代替用户确认路线、切教材、开考或作答。

到期扫描复用原 `teaching_intent` 队列和唯一原 Run。用户明确启用 proactive、选择 IANA 时区/允许时段且处于允许教学模式后才可推进；时段外、暂停、活动考试和用户前台任务等待。未生成 Run 的到期意图也可明确取消，读取或刷新不登记新意图。

## S13. 语言与执行矩阵

### S13.1 基座适配与课程交付分开

| 课程范围 | 必须逐项核对的执行类别 |
|---|---|
| Python | stdin/stdout、函数类任务与对应真实评分；不能以现有整数数组样例覆盖全部 |
| JavaScript / TypeScript | 运行与 TS 编译/类型结果分开，函数或程序测试 |
| SQL | 首批 MySQL/PostgreSQL/SQLite 独立 Profile，Schema/隔离数据、查询结果评分及安全展示 |
| HTML/CSS | 受限预览、交互/结构/样式检查与非评分演示分别声明 |
| Java / Go / C# | 固定编译/运行 Profile、程序/函数合同与服务端判定 |

矩阵每一组合记录：材料覆盖、计划/课时、可用题型、运行环境、scorer、工件、盲解/六审、补救/关系/Gate、复习和验收层次。旧 registry 的 Rust/C++ 等注册事实不自动等于公开课程；额外正式产品承诺另列，不静默标通过或删除。

语言基座先消除现有 `code + list[list[int]]`、Python 命令和固定用例结果的耦合，再逐个接入真实 Profile。保留旧执行合同解释，不能直接改变既有 Python Attempt/回执。基座合格与课程合格为独立里程碑，八组课程不因基座通过而全部标绿。

### S13.2 项目、编译与运行合同

- 项目输入为不可变 `project_ref/revision + files manifest + execution_profile_ref/version + test_protocol_ref`，绑定原 Attempt/题目/当前用户；由服务端解析，模型或学习者不能任意指定镜像、shell 命令或 Docker 参数。
- 文件仅接受验证后的相对路径、允许类型与实际容量，拒绝绝对路径、越界、符号链接及宿主路径；使用每任务独立临时工作区，缓存不构成跨用户可写共享目录。
- Profile 包含 runtime/compiler/dialect/framework 版本、可信环境身份、构建/运行入口、依赖锁/环境模板版本、scorer、测试协议、网络/文件/资源规则及结果合同。执行 job、租约、回执和上报幂等继续复用，不增加第二套执行或评分引擎。
- 依赖准备、编译、运行、检查分别记录事实。学习者构建脚本和安装脚本同样不可信，编译不能放在宿主、仅把最终程序放入容器；只读依赖环境与有界临时构建目录分开。
- 编译/运行分别设置实际 CPU、内存、进程、磁盘/输出和时间额度，并配套任务心跳、取消和定向清理。不能把当前 Python 的 128 MiB/6 秒直接套到所有编译器，也不能因准备长请求而无界占用资源。
- 可信 Controller 与不可信构建/运行环境分离；学习者环境不获得业务 DB、模型/API 凭据、宿主目录或 Docker 控制权限。编译错误、测试失败、基础设施错误和过期迟到结果分别处理。

Rust/C++ 先评估标准库程序的编译/运行 Profile。Rust 工具链与 Cargo 依赖、C++ 编译器/链接器及可选构建系统分别准备；普通 CPU 程序练习不需要 GPU。第三方依赖和大型构建的缓存、资源及测试成本另测，不能以安装了编译器宣称完整课程可用。

### S13.3 SQL 方言与隔离数据

首批实施按 MySQL、PostgreSQL、SQLite 分开建模和验收，SQL Server/Oracle 等保留扩展状态；这个顺序不表示其他方言不主流，也不宣称全 SQL 兼容。教材、Schema、题目、运行器及 scorer 必须绑定同一方言与版本，不用 SQLite 通过代替 MySQL/PostgreSQL 证据。

练习数据库/数据集与业务 PostgreSQL 完全隔离，每 Attempt 有独立可清理范围及最小权限，不能给学习者业务连接或数据库管理权限。DDL/DML 只作用于该练习范围，查询/测试资源有实际限制。结果比较明确有序/无序、重复行、类型/NULL 等题目语义，隐藏期望结果留在可信评分方。

2026-11-06 工程及原业务链：原控制器实现 `sql-query.v1`，SQLite 内存库及 PostgreSQL/MySQL 临时服务各真实执行，服务关闭网络/宿主端口，仅通过本作业 Unix socket 使用 SELECT-only 账户和只读事务；SQLite 另限制 authorizer/扩展。输入为有界类型化 Schema/数据，不接初始化 SQL；`sql-table.v1` 返回实际列名/行、逐 cell 类型/NULL 和不丢 Decimal 精度的规范文本，Runner 不排序、去重或判分。每组数据库与命名卷定向销毁，仍不支持 DDL/DML。

`kind=sql_query` 在原 ItemBank 固定显式方言/精确版本，走原 Runtime 作者、公有题面盲解、五槽实际资格、六审及发布。原 Assessment 固定 `sql-result-typed.v1`，按题面公开的有序或 multiset 比较（含重复数）、精确列名/列序、实际类型和值/NULL；查询 exit 0 不等于正确。原队列只向精确声明 `program_environments` 的 Runner 分派新任务，旧声明/错误版本不获得新权限，运行前复核版本；新租约 300 秒，旧 Python 90 秒不变。普通提交、父 Attempt CAS、显式重试、取消/迟到/过期、当前权限及原讲评已接，失败基础设施不生成错误成绩。环境失败让原供给等待，不借自动修订再调用作者；环境修复后重新资格的授权/恢复仍待完成。工件已按 S09 接独立候选/准备/检查/交付及原动作，原生宿主已接控件/草稿/实际样例，但本次未做新浏览器/全场景验收；真实 Docker/数据库、离线模型与产品验收分开，详见根 README。

`program-public-sample.v1` 只从原所有者在创建 Attempt 时固定的 `sample_case_index` 投影实际类型化 SQL 表格或项目整数，包括答错时的真实值；不假设样例为第一组，不取预期答案，不暴露其余两组、原始 stdout/stderr 或资格 Attempt。项目实际整数附带精确十进制 `integer_text`，超出 JavaScript 安全整数时 output 为 NULL、以该文本为准；旧整数行在读取时派生文本而不改数据库/成绩。无效/未成功输出仅保留安全 outcome/exit code、output 为 NULL 且无整数文本；未适用、取消、迟到及无样例身份的旧行不产生投影。该投影与成绩/原反馈事务一致，普通 GET/请求恢复/历史/快照同源只读，读取不再执行。

### S13.4 第三方依赖与框架的受控项目

框架教材学习与可执行项目练习分别验收。可执行范围按课程 Profile 声明：框架/依赖精确版本、模板、允许修改的文件/入口、测试方法及隔离服务；不把任意仓库托管平台作为前置条件。

1. 路线提出环境需求 → 解析依赖/版本并展示影响 → 用户明确安装授权 → 本机隔离准备与构建验证 → 发布精确环境 → 每 Attempt 创建独立项目 → 真实测试 → 本机业务评分 → 定向清理。已获同范围授权及合格环境可复用，学习者不维护镜像或每次手工安装。
2. 依赖获取使用获准源和受控出口，不携带业务/模型凭据；安装/构建脚本也在隔离准备环境运行。已锁定依赖预备好后，学习者执行默认不访问互联网，不在学习者容器中开放任意 `pip/npm/cargo` 联网安装。
3. HTTP 框架使用内部测试客户端或隔离测试端点；需要数据库等服务时提供仅本次任务可达的私有测试网络/临时数据，不暴露公共宿主端口或连业务数据库。前端预览继续按 S11 隔离主应用权限。
4. 新依赖/框架须完成环境与课程资格后才开放执行；未完成时显示准备/不支持的具体状态，不能偷偷转为宿主执行或取消隔离。用户可学习材料，不将阅读冒充该框架实操通过。
5. 准备、构建、测试和学习者运行均在用户本机，不提供远程 Runner、公开执行节点或跨设备调度。仍验证本机隔离、资源、网络、凭据和清理边界，不以“本地”绕过安全要求。

2026-11-06 同一控制器增加 `python-project-io.v1`：2—20 个真实文本文件、最多 100KB UTF-8，拒绝点路径别名/穿越并检查唯一 `.py` 入口；可信暂存后只读卷进入非 root 学习者容器，支持标准库跨文件导入及声明数据文件，每用例独立受限 tmpfs。`kind=python_project` 固定运行时精确版本，已续接原题包作者/公有盲解/实际资格/六审/发布、能力协商队列与 Assessment 多 Attempt/取消；原业务所有者验证完整固定清单、入口/只读标志与受保护内容，仅可编辑文件内容能改，重排按原顺序规范化以保持重放。每 Attempt 固定观测后的本地镜像 ID，可信预检在挂载学习者文件前核对版本，不以学习者退出码冒充环境失败。工件/宿主按 S09 接独立能力、固定 files 和原动作，文件组件逐文件内容可承载同一 100KB 总预算；没有框架安装、宿主挂载或任意命令，不可变环境发布、完整原生场景及课程资格仍未完成，不把这些证据标为完整框架项目旅程完成。

### S13.5 本机按需环境与安装授权

三层分别为应用及其本地后台、本机隔离执行引擎、课程环境包。应用管理自己的后台组件；安装包内置支持规则、受控入口和可信配方，不一次捆绑全部语言 SDK。底层引擎首次检测/安装是独立系统操作，涉及权限或重启须明确引导；课程依赖同意不是提权或执行任意安装脚本的许可。

安装授权只管理本机环境资源，不把教材检查、生题审核、修订或合格发布重新变成人工确认步骤；已授权范围内的自动化和质量条件保持不变。

由 execution 拥有 `environment_demands`、`environment_install_decisions`、准备 job 及不可变 `environment_releases`，沿用原持久任务/回执机制，不另建环境工作流平台：

- 需求保存 actor、本机作用域、路线/plan revision、执行 Profile、运行时/编译器、框架及传递依赖锁、版本策略、获准来源、所需网络/测试服务、资源估算和 requirement revision。估算未知时明确未知。
- 基础语言、SQL 引擎和浏览器检查工具链由应用按明确学习需要自动准备；工具链自身锁定依赖包含在基座范围，不逐包询问。课程额外框架由可信配方明确分类，不能仅因依赖锁非空就当作课程额外安装。现有配方中 Flask 需要用户安装同意，TypeScript 类型包、SQL 驱动及浏览器依赖随各自基座准备。
- 完整路线用 `PlanDocument.environment_recipes` 汇总基础及既有受控配方，用 `environment_dependencies` 声明课程新增依赖。新增项包含 `language/title/dependencies[{name,version}]/build`，同语言及构建方式合并为一个环境；版本必须明确，不能提交 shell、镜像、下载 URL 或仓库凭据。`build=stdio` 接六语言项目，JS/TS 的 `build=vite` 接离线构建与浏览器检查，`build=http` 接任务内服务及可选 `database=sqlite/postgresql/mysql`。标准库 HTTP 服务可使用空依赖列表；常驻托管、外部联网服务及未支持的系统需求记录在 `environment_gaps`。作者与原独立检查共同核对覆盖，路线草案及只读预检不下载或安装。旧文档空清单保持原序列化，不根据标题猜测并改写历史路线。
- execution 按规范化课程声明派生环境标识，合并基础工具链与课程直接依赖生成完整 `EnvironmentRequirement`；`course_environment` 进入展示快照、需求、授权和准备任务。`EnvironmentDemandInput` 可携带该声明，但必须与派生标识一致。所有课程新增依赖均须额外授权，不因使用通用包管理器变成自动安装。
- 准备器复用基础环境，分别使用应用维护的 pip、npm、Maven、Go modules、NuGet 步骤构建专用成品。安装指令及公开来源由应用管理，课程只声明包和版本。核对实际直接依赖版本，成品镜像冻结解析后的依赖树；准备报告必须对应获准声明及依赖锁。同一声明可复用缓存，新增范围重新决定。
- 在确认路线时统一询问额外环境。`GET /v1/plans/{id}/environment-requirements/{revision}` 返回本人精确草案或活动版本的完整需求、基础环境分类、待同意项和现有状态，不登记需求。基准界面的按钮弹出气泡只直接展示用途、主要环境及应用自动管理专用隔离存储；版本、完整依赖、来源和资源信息默认折叠，用户不逐次选择目录。
- “确认路线并安装”向原确认命令明确提交 `environment_requirements`，后端逐项比对实际展示的完整需求快照，清单变化则整体拒绝；路线确认、需求登记和安装决定在同一事务中保存。“仅确认路线”不携带安装同意，只启动基础环境准备，额外环境保留待同意。已确认路线的“安装所需环境”复用各需求原决定 API、双 CAS、幂等键和 GET 回执；不重新开始学习或运行代码。
- 额外环境授权命令仍携带 `expected_requirement_revision`、决定 revision、幂等键及 `allow / defer / decline / revoke`。模型或普通路线确认不能代为同意；按钮的明确组合动作分别形成路线与安装事实。基础自动准备的决定在原 command JSON 中标记 `authorization_basis=managed_base`，用户同意为 `user`，同一路线相同锁的后继复用为 `reused_consent` 并引用原决定，不把自动准备伪装成用户点击。
- 额外环境无同意时为 `waiting_authorization`，引擎未就绪为 `waiting_engine`；获准后进入 `queued → preparing → verifying → ready`，必要时按原保证进入修复/依赖等待/取消/未知。GET 和模型输出不授予额外环境安装权限。用户明确停止的基础环境不会因重新登记或路线确认自行恢复；已有合格且获准的兼容环境可满足基座需求，不自动降级覆盖。
- 同范围、同一锁定环境的重用/重建不重复确认；超出依赖/版本策略、增加服务或网络权限、产生未获准费用时新建需求 revision 再确认。授权内准备新候选也不能静默改变已锁定 Attempt/Gate 的环境绑定。
- `defer/decline` 保留路线及可读教材，不自动删学习目标，不以重开 job 反复弹窗。撤销阻止后续准备/使用，已有事实保留；在途任务检查取消及清理，不将 UI 取消当作已停止证明。
- 成品环境绑定精确工具链、依赖锁、可信配方和验证结果；仅在当前授权与资格成立时对该路线可用。安装成功不等于题目合格、评分通过或框架课程完整支持。
- Vite 课程继续使用 `web-check.v1`，语言可为 JS/TS。项目提交 HTML、源文件和检查操作，依赖清单及构建配置由环境拥有；Runner 先构建独立产物，再让隔离浏览器检查实际 DOM、样式与交互。编译失败单独回报，未运行的浏览器检查不伪造结果。资源经浏览器内部的本地映射读取，不启动公开端口，不开放学习者容器互联网。
- HTTP 课程使用 `project-http.v1`，题包种类为 `http_project`，作答仅含 `type=http` 的完整源文件。`HttpProgram` 包含入口、可选数据库结构及一至三个场景；每个场景包含一至六个本地路径请求和可选类型化初始数据。每个场景独立启动、初始化、等待就绪、执行请求和清理，场景内保留数据库写入。服务监听回环 8080，客户端、服务及 PostgreSQL/MySQL 共享任务网络命名空间，SQLite 使用 64 MiB 临时内存卷；无宿主端口、互联网或业务数据库。`DATABASE_URL`、`DB_*`、任务数据库凭据和 SQLite 路径由应用提供。
- HTTP 回报使用原 `RunnerReport`，场景 stdout 为 `http-scenario-result.v1`。私有预期响应不下发 Runner；Assessment 的 `http-response.v1` 按顺序比较状态码、解析后的 JSON 结构或精确文本。三组用例包含一个公开场景，普通回执只投影该场景。HTTP 租约为 600 秒；编译失败、取消、过期、迟到和当前授权检查沿原流程处理。数据库增加写入只发生在任务私有范围，原 `sql-query.v1` 查询权限保持。
- HTTP 工作台读取要求 `program_capability=learning_programs.v2`；新版客户端声明同名动作能力。旧 `learning_programs.v1` 继续读取原 SQL/项目，遇到 HTTP 工件时得到明确升级错误，不返回无法解析的新任务联合类型。
- 环境准备仅走获准下载源/出口；学习者运行不继承下载权限。隔离构建、临时工作区和可复用环境分离，不修改系统全局 SDK，不自动采用用户已有全局工具链评分，也不开放任意 shell/镜像参数。
- 取消、应用退出或故障恢复只处理本应用有权管理的资源：定向停止任务、核验停止并清理临时工作区，不 prune 其他容器/环境，不删除学习记录。合格缓存可复用，不每题重新安装。

首次使用、安装授权、准备进度/失败恢复及版本冲突属于桌面产品验收；当前手工预置 Python 镜像/终端启动 Runner 的证据不能替代这些功能。

编译成功、可打开预览和运行退出 0 不等于正确。正式 Gate 不泄露中间测试/答案、不因语言切换清空曝光，不增加另一个评分循环。允许的单次 CPU/内存/时间限制不构成教材/供题任务总修订上限。

### S13.6 当前多语言与环境接线

0054/0056 把受控环境及 SQL/项目补入原 ItemBank、Assessment、执行队列与关系审查链。新增 `project-stdio.v1` 接 Python、JavaScript、TypeScript、Java、Go、C#：声明实际完整文件、不可修改文件和入口，使用 UTF-8 原始字符串 stdin/stdout；固定 `stdio-text.v1` 仅统一 CRLF 并移除一条末尾换行，其余空白保留。Go 固定可信模块 `learner.local/project`，跨目录导入使用该路径，不接学习者 `go.mod/go.sum`。

构建诊断作为独立 `compilation` 回执。编译失败时 `cases=[]`，不虚构未运行用例；没有失败编译事实的空 case 报告拒绝。可信编译与学习者运行使用各自受限容器/卷，学习者不获得宿主源码目录、网络或构建工具控制权限。`web-check.v1` 在隔离 Chromium 中产生结构、文本、实际计算样式及明确点击后的观测，隐藏期望值留在 Assessment。

普通练习、多 Attempt、补救、新情境及两题整组 Gate 均复用原所有者和评分；SQL 三方言分别冻结精确环境。后继仍要求同节点/版本/来源、同实际环境、未曝光及难度约束，并通过原关系检查；后继通过仅解除对应补救阻断。编译/运行/基础设施错误、原成绩和正式证据分开保存。

模型工具 `get_execution_environments/request_execution_environment` 只读当前范围或登记正常需求；`request_learning_program_supply/get_learning_program_supply` 使用真实获准环境进入原质量链。工具只授予新 Run 并按原 map 冻结，模型不能允许安装。新 `project_stdio/web_project` 题包及派发强制有效的显式授权 release；已存旧 SQL/Python 合同继续按原可选 release 解释。

Controller 仅接受本机 npipe/Unix Docker IPC，并把已核对端点固定到本进程，不修改用户全局 context。运行前、逐用例及运行期间复核原执行权限和 release；撤销定向停止实际容器，停止/移除未确认时终止 Controller 领取。应用打包携带隔离 Python、Node、本地后台及可信配方，通过专用本机项目管理自己的服务；实际 portable 首启、窗口预览/CSP 与完整真实课程仍单独验收，工程工具链测试不替代课程退出。

## S14. HTTP、工具与公开事件目标

### S14.1 HTTP 目标

新写入命令使用现有身份解析、严格 DTO 和幂等机制；长任务返回 `202 + job_id`。以下是目标合同，不表示现有路由已存在。

| 路由 | 所有者/语义 |
|---|---|
| `POST /v1/material-texts` | 首批低阶同步文本/Markdown 接入，仅 parsed，不代替下面的自动 material-imports |
| `POST /v1/sources/{id}/material-compatibility` | 显式映射当前有效旧摘录，保留旧截止、版本和撤销检查 |
| `GET /v1/documents/{id}/versions/{revision}`、`POST .../permissions` | 精确版本安全元信息；权限端点当前只支持带 expected revision 的撤销 |
| `POST /v1/material-bindings`、`GET /v1/material-bindings/{id}`、`GET /v1/material-bindings/{id}/blocks` | learning 拥有固定版本和历史，非检索/覆盖入口；没有根路径 GET 列表 |
| `GET /v1/model-configuration` | 当前身份的安全配置/职责映射与本机凭据保管状态 |
| `GET /v1/model-connection-tests`、`GET /{id}` | 恢复显式测试状态，GET 不重新调用；固定样例可测聊天、OCR、向量、排序协议，不认证教材质量 |
| `GET /v1/execution-environments` | execution 读取本机引擎、环境可用性与安全进度，不启动安装或学习代码 |
| `POST /v1/environment-demands` | execution 接收具名协调器解析的当前路线需求；建立待授权记录不是安装许可 |
| `POST /v1/environment-demands/{id}/decisions` | 当前用户明确允许/稍后/拒绝/撤销，检查 requirement revision、scope 与幂等，再由本机后台推进 |
| `GET/POST /v1/model-connections`、`PATCH/DELETE /v1/model-connections/{id}` | platform 管当前用户连接与凭据写入/轮换/撤销；GET 永不返回密钥，写入校验 expected revision |
| `GET/POST /v1/model-profiles`、`PATCH /v1/model-profiles/{id}` | platform 管当前用户非秘密模型配置/角色映射及版本；不允许跨 owner 引用 |
| `POST /v1/model-connections/{id}/tests` | 用户显式发起的连接/模型能力测试，按真实协议保存安全结果、用量和状态，不重发 UNKNOWN |
| `POST/GET /v1/material-demands`、`GET /v1/material-demands/{id}` | 私有需求入口；教学/规划/课时命令内部自动登记服务端消费者需求，读取不登记；其余消费者待接线 |
| `POST /v1/material-demands/{id}/texts`、`GET /v1/material-demands/{id}/jobs`、`GET /v1/material-jobs/{id}` | 已实现的 202 持久解析及分页状态；正常材料任务继续索引/验证，缺配置或质量问题仍等待，不以 parsed 代替 ready/覆盖；GET 不触发 |
| `POST /v1/material-demands/{id}/uploads`、`GET /v1/material-uploads/{id}` | 已实现需求下的原文上传引用/状态，身份和用途由服务端复核，公开 DTO 无宿主路径 |
| `PUT/GET /v1/material-uploads/{id}/content` | 原始字节上传/当前用途下附件下载，不渲染 HTML，不触发解析 |
| `POST /v1/material-demands/{id}/files` | 已实现引用上传原文的 202 文件解析；取代原设计同义 material-imports 路由，不增加第二入口 |
| `POST /v1/material-jobs/{id}/cancel` | 取消本根及未完成后继，不伪造已停止远端 |
| `GET /v1/documents/{id}/versions/{revision}/blocks` | 当前权限下分页精确读取，支持 block 定位 |
| `POST /v1/material-searches` | 已实现 202 持久检索任务；服务端绑定需求/用途/可选精确 binding，显式 lexical/hybrid |
| `GET /v1/material-searches/{id}`、`POST .../cancel` | 读取/取消同一检索任务；GET 不重发模型 |
| `GET /v1/material-selections/{id}` | 当前原文权限下读取精确选择与词项证据覆盖，不授予新的业务动作 |
| `POST /v1/material-change-checks`、`GET /v1/material-change-checks/{check_id}` | 已实现精确绑定基线的累计比较和持久回执；新显式 uncertain 比较唯一登记定向复核，原键回放不追加任务 |
| `GET /v1/material-change-checks/{check_id}/review` | 已实现当前权限下只读复核状态/闭合结果，无任务返回 null，不派发模型 |
| `POST /v1/material-change-checks/{check_id}/review/cancel` | 已实现复核取消及原操作账本承接；不迁移绑定，迟到回执不应用 |
| `GET /v1/notifications`、`POST /v1/notifications/{id}/read` | delivery 查询/记录已读；不迁移教材 |
| `POST /v1/material-update-offers/{id}/decisions` | learning 协调用户选择，校验 expected binding/proposal revision |
| `GET /v1/conversations/{id}/learning-artifacts/{artifact_id}` | 只读精确交互工件，不与旧 `/v1/artifacts` 文档混义 |
| `POST /v1/conversations/{id}/learning-artifacts/{artifact_id}/actions` | 统一动作/CAS/幂等，委派原业务 owner |
| `GET /v2/conversations/{id}/learning-artifacts/{artifact_id}` | V2 组合详情；program/response/提交审查/直接答案/提示/demo 分别协商读取，不给旧读者返回不认识的绑定 |
| `POST /v2/conversations/{id}/learning-artifacts/{artifact_id}/actions` | 原组件作答/代码、typed program 提交、辅助、demo 明确开始/登记/完成、精确取消/显式重试；共用原 CAS/幂等/只读回执 |
| `GET /v2/conversations/{id}/learning-artifacts/{artifact_id}/demos/{component_id}/completions` | 本人当前权限下只读分页；demo 能力、精确组件、before/limit，不产生动作或独立掌握证据 |
| `POST /v1/conversations/{id}/learning-artifact-candidates` | 已实现两类普通练习候选；不开放考核/任意代码入口 |
| `GET /v1/conversations/{id}/learning-artifacts` | 已实现 keyset 分页；与 snapshot.learning_artifacts、同 actor SSE 共用身份与游标 |
| `GET /v2/packs/{id}/program-practice`、`POST /v2/packs/{id}/program-submissions` | 原公开 SQL/项目普通练习与 typed answer；原 Assessment 多 Attempt，不走正式 Gate |
| `GET /v2/packs/{id}/program-practice-attempts`、`GET /v2/program-practice-attempts/{id}`、`GET /v2/program-practice-requests/{key}` | 本人普通历史/请求只读恢复，不暴露资格、隐藏数据/期望或私有实际输出 |
| `POST /v2/program-practice-attempts/{id}/cancel`、`POST /v2/packs/{id}/program-review` | 原队列取消及资格后的原审核续接；不自动重跑资格或升级旧 Run/工件 |
| `GET /v2/conversations/{id}/teaching-session` | 只读显式开启的会话，无会话返回 null，不补建 |
| `POST /v2/conversations/{id}/teaching-session/actions`、`GET .../actions/{action_id}` | 开启、模式、暂停/恢复、返回、切题、结果续行策略及显式结束本节；精确命令身份/CAS 与只读原回执，不调用模型 |
| `POST /v2/conversations/{id}/teaching-session/continue` | 可见引导窗口到期；返回原 `TurnAccepted`，重复按会话、版本及上回合复用 |
| `GET /v2/conversations/{id}/teaching-branches?before=&limit=` | 已实现同 actor/会话 keyset 分页元数据；完整内容仍读原 Turn 历史 |
| `GET /v1/review-activities`、`POST /v1/review-activities/{id}/responses` | 到期活动与版本化自评/业务作答结果引用 |

继续使用 `/v1/snapshot`、`/v1/events` 的同一 actor 游标和已存在的历史分页；增加类型化 conversation item/通知引用，不为每个工件开第二套 SSE。近期窗口不是永久历史上限；过旧 cursor/缺口通过一致快照和分页恢复。

### S14.2 Tutor 工具目标

保留旧冻结合同。新 Run 按当前角色显式声明以下能力的版本交集：

- `learning_get_context`：当前绑定、公开反馈与可用动作；
- `knowledge_search`、`knowledge_read`：作用域内材料查询/分页读取；
- `list_learning_artifact_candidates`：已实现精确节点下两类普通练习的公开分页候选，冻结工具版本；`read_learning_artifact` 工具尚待接线，现有 scoped HTTP GET 可读公开交互状态；
- `list_learning_program_candidates` / `prepare_learning_program_composition`：另由 `learning_programs.v1` 冻结；公开 SQL/项目源只可按真实回执绑定组合，经原独立检查/原子交付，不授予运行/安装或正式 Gate 资格；
- `request_learning_activity`：幂等提出缺失活动需求，返回 accepted/job_id，不直接执行或评分。

工具权限、参数 schema、结果合同、并行条件、当前业务检查继续共源。独立只读可并行；同一业务写、共同快照要求和版本依赖保持正确顺序。公开工具摘要不输出参数、推理或私有正文。最终工件选择仍进入同次教学交付事务，不在中途工具结果发布半条消息。

### S14.3 事件与错误

事件仅承载已提交事实及稳定引用，例如材料可用/检查完成、更新提案就绪、用户选择已保存、工件创建/更新、复习安排/完成、教学意图变化。使用原 Outbox/Inbox 与幂等键，不以事件/通知当新执行授权。

公开错误区分无权/未找到、版本冲突、材料等待、环境不可用、结果未知；提供安全状态与下一步，不能返回凭据、宿主路径、私有 rubric/test、原模型回执或推理。

## S15. 迁移、兼容与启用

- 使用新增增量迁移，编号从实施时当前末尾继续；已安装 0001—0022 不回改、不 destructive down migration。
- 旧 `valid_until` 是旧合同事实，不能机械改成真实来源授权或把到期批量延长伪装成新许可。按来源 provenance 和真实政策构建新检查/绑定模型，保留可追溯映射。
- 旧 SourceRef、文档工件、固定课时/复习、旧 Run 的输入与工具权限继续按原合同解释；新语义以新版本合同消费，不原地重解释。
- 后台准备/索引可先启用；当前路线切换必须有用户决定。新写入和客户端渲染按实际依赖协调启用，不能发旧客户端无法解析的新联合类型。
- 本机环境管理先支持需求、明确授权、引擎检测/引导及合格环境绑定，再开放对应一键执行；不把既有手动配置追认为用户安装授权，不为兼容预留远程 Runner。产品由应用管理本地后台，当前开发 Compose 不等于安装包交付。
- 回退优先停止新任务准入/新模式发布，保留历史、索引快照、待办和外部调用事实；不靠清库或删除 UNKNOWN 回退。
- 配置仅复用已明确授权的必要凭据，不打印/提交。千问新增三个通道的私有材料云处理及真实付费开发/验收授权已于 2026-11-02 明确，无地域/费用上限，不重复索取；不等于开通新收费服务、自动充值/升级或其他用户同意。按 S05 落地用户配置，未完成的调用/部署不写成完成。

## S16. 需求追踪与规范参考

| PRD 需求 | 本 spec 约束 |
|---|---|
| P4-FR-01 | S03、S04 |
| P4-FR-02 | S04、S01 |
| P4-FR-03 | S05 |
| P4-FR-04 | S06 |
| P4-FR-05 | S06、S03 |
| P4-FR-06 | S07 |
| P4-FR-07 | S07 |
| P4-FR-08 | S08 |
| P4-FR-09 | S09、S10 |
| P4-FR-10 | S09、S14 |
| P4-FR-11 | S10、S13 |
| P4-FR-12 | S11、S10 |
| P4-FR-13 | S11、S13 |
| P4-FR-14 | S11、S12 |
| P4-FR-15 | S12 |
| P4-FR-16 | S12、S15 |
| P4-FR-17 | S12、S11 |
| P4-FR-18 | S13、S14、S15 |
| P4-FR-19 | S01、S10、S14、S15 |
| P4-FR-20 | S01、S13、实施计划的分层验收 |

本轮仅核对设计所需官方说明，未调用真实模型。候选/接口资料核对日期：2026-11-02；实施时核对当前账号地域、文档与正式版本。

2026-11-03 实施补核：通过 Exa 实际打开下列官方协议页，并核对 DashScope 官方 SDK 的 HTTP 路径说明。专用连接探针据此区分 native embedding 的 `input.texts/parameters.dimension/text_index`、兼容 embeddings 的 `input/dimensions/index`、原生 rerank 的 `input.query/documents`，以及 OCR 官方支持的多模态兼容请求；不发送 thinking、tools 或结构化输出参数。区域守卫增加匹配的官方工作空间域名，不放开任意 DashScope 根地址。仍未获得实际用户通道配置，未作真实调用或把文档候选升级为正式质量组合。

- OCR 兼容协议：`https://help.aliyun.com/en/model-studio/qwen-vl-ocr-api-reference`
- 文本向量协议：`https://www.alibabacloud.com/help/en/model-studio/text-embedding-synchronous-api`
- 重排序协议：`https://help.aliyun.com/zh/model-studio/text-rerank-api`
- DashScope 官方端点：`https://github.com/dashscope/dashscope-sdk-python/blob/main/_autodocs/endpoints.md`

- 千问 OCR：`https://help.aliyun.com/zh/model-studio/qwen3-5-ocr`
- 文本向量：`https://help.aliyun.com/zh/model-studio/text-embedding-synchronous-api/`
- 重排序：`https://help.aliyun.com/zh/model-studio/text-rerank-api`
- PostgreSQL 全文检索：`https://www.postgresql.org/docs/current/textsearch-controls.html`
- pgvector 与混合检索：`https://github.com/pgvector/pgvector`
- FSRS 记忆模型说明：`https://github.com/open-spaced-repetition/awesome-fsrs/wiki/ABC-of-FSRS`
- HTTP 条件验证：RFC 9110，`https://www.rfc-editor.org/rfc/rfc9110.html`
- Docker 隔离与权限：`https://docs.docker.com/engine/security/`
- Cargo 构建脚本：`https://doc.rust-lang.org/cargo/reference/build-scripts.html`
- GCC 的 G++ 前端说明：`https://gnu.googlesource.com/gcc/+/7b815107f403c526b7e201ca00494f06d1c20768/gcc/doc/frontends.texi`
- SQL 方言差异：`https://www.sqlite.org/quirks.html`

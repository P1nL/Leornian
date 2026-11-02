# 公开 API 与事件合同

`TurnInput.focus` 绑定目标、精确节点/课时或已公开评测回执；提交可返回 delivery_task_id。交付任务 list/get/cancel/resume 与 snapshot.delivery_tasks 仅公开状态、恢复所需信息和时间，不公开候选、原始检查或会话摘要。合格计划仍需确认，正文合格不等于学习完成；UNKNOWN 只有已有完整回执才可承接。对话历史和计划版本支持 keyset 分页。

0022 增加 ArtifactRequestInput/ArtifactJob/ArtifactView/ArtifactSummary，以及只含名称、合同版本、状态、耗时的 ToolActivity。生成/修订端点返回 202 任务，不返回未通过候选；读取可指定精确 revision，正文和代码只用于安全展示。snapshot.artifacts/artifact_jobs/tool_activities 与 tutor.artifact_updated 事件支持刷新承接；无私有工具参数、原始结果、会话摘要或思考。

新 PackRequest / SupplyRequest 默认 automatic=true；PackSummary 包含 automatic、历史 automation_error、supply_task_id 和 automation_status/action/reason。供给状态属于跨版本任务，不以修订版数或补正次数封顶；修订沿用父版策略，旧手动行不追溯接管。摘要不包含会话 digest 或修复提示词。普通供给 completed 表示合格发布，缺题供给 completed 表示后继已可分配，不表示学习者已经开题、作答或学习完成。

任意版本的 cancel 映射全供给任务；已发布内容、旧报告与已开启的学习者作答保留。automation-resume 用当前本人授权恢复等待任务，不恢复取消任务。历史查看和自动跟随是客户端两种明确模式，不改变服务端授权或重置质量报告。

已生成目标、Tutor、路线/正文、概念题包、补救与 Gate 准备/allowed_actions/开始/一次提交/取消、节点概念进度、固定评测、来源和复习合同。`openapi.json` 由 Pydantic/FastAPI 导出，`src/generated.ts` 由 openapi-typescript 生成；私有答案、关系报告和六审全文不作为公开响应模型。考核 public questions 仅 start 后给出，逐题反馈仅 terminal 后给出，类型存在本身不解锁动作。

包含关联 Gate 失败的题包修订请求，以及新情境后继 request/view/open/一次提交/cancel 和安全摘要事件。候选检查上下文/报告不公开；后继明确 open 前无 question，结果不赋予 Gate 或 mastery。概念提交选项，Python 提交程序，不能指定候选、分数或模型 verdict。

新增 SupplyDemand/讲评、python_io 题包、PythonQuestion/本人 PythonAttempt 和独立执行证据。GateView.questions 为概念题或 Python 公开题面，策略区分 concept-gate.v1/python-io-gate.v1；submitted 是等待执行，不是通过。Python 两份考核程序整组提交，隐藏测试/预期值/盲解程序不作为公开模型；公开样例的输入与输出不属于隐藏用例。现有 Gate 资源路径保留，新增 execution-submissions 命令，不由客户端指定分数。

TransferSummary/SupplyDemand 用 kind 与互斥的 remediation_id/python_remediation_id 表示精确起点。TransferView.question 可以是公开概念或 Python 题；python_attempt 只公开本人已锁定程序和安全反馈。代码后继的 submitted/error 状态不表示通过，原补救仍失败。`PythonAttempt.transfer_id` 区分后继与普通训练，客户端不能把候选题作答混作原包训练。

从仓库根目录运行 `pnpm contracts`。不要手工修改两份生成文件；变更源合同后一起重新生成并运行客户端类型检查。

- 服务端 schema 是类型来源，不手工维护相同 DTO 的第二套定义。
- 公开合同显式版本化，客户端只收到允许公开的数据。
- 隐藏答案、私有评审、授权 token、内部推理和仓储对象不进入公开事件。
- HTTP 接受长任务不等于业务完成，返回值区分 accepted 与 completed。
- Schema 也包含经独立认证的内部 Runner 路由，类型存在不赋予客户端调用权限。浏览器只使用 `/v1` 公共模型，不取得 Runner token、claim 或私有报告。

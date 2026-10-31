# 公开 API 与事件合同

已生成目标、Tutor、动态路线/节点正文、固定评测、来源与复习的客户端 API、快照和 SSE 类型。`openapi.json` 由 Python Pydantic/FastAPI 合同导出，`src/generated.ts` 由 openapi-typescript 生成。

从仓库根目录运行 `pnpm contracts`。不要手工修改两份生成文件；变更源合同后一起重新生成并运行客户端类型检查。

- 服务端 schema 是类型来源，不手工维护相同 DTO 的第二套定义。
- 公开合同显式版本化，客户端只收到允许公开的数据。
- 隐藏答案、私有评审、授权 token、内部推理和仓储对象不进入公开事件。
- HTTP 接受长任务不等于业务完成，返回值区分 accepted 与 completed。
- Schema 也包含经独立认证的内部 Runner 路由，类型存在不赋予客户端调用权限。浏览器只使用 `/v1` 公共模型，不取得 Runner token、claim 或私有报告。

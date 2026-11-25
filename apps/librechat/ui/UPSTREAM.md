# 可编辑的 LibreChat 界面组件

来源为本项目固定的 LibreChat `f4154b6` 前端，许可证见本目录的 `LICENSE`。

这里保存产品正在使用的页面外框、导航、最近会话、消息、设置和共享样式。构建与组件工作台都由 `pinned-client.mjs` 加载这些文件；相对导入按原组件路径解析。修改这里后，组件工作台会热更新，产品重新构建后使用相同修改。

Leornian 的业务接线继续由 `connected-overlay.mjs`、`native-overlay.mjs` 和 `connected-settings.mjs` 完成。编辑带有这些接线的组件时保留对应的调用位置；原固定上游目录用于依赖和来源参考。

输入框、学习路线、材料、模型和学习工件的本地组件位于本目录上一层。全部修改入口可从 `pnpm librechat:components` 的组件目录和源码面板查看。

# 内置学习资料目录

整理日期：2026-11-14。范围为当前六种编程语言、HTML/CSS 及三种 SQL 方言，并包含相关框架和第三方依赖资料。

## 使用方式

- 数据源：`backend/src/leornian/modules/knowledge/source_catalog_resources.json`。
- 查询入口：`modules.knowledge.source_catalog.catalog_resources`，支持语言、框架、载体、正文语言、入口可达性和数量筛选；返回独立副本。
- 检索结果是候选资料。URL、发布者、版本说明、访问观察和原文检查分别保留；HTTP 成功不等于正文已解析或教学质量通过。
- 目录包含项目官方、第三方作者和社区译文。官方指对应语言、框架或依赖的维护者；MDN 与 web.dev 是第三方参考资料，不标为语言标准发布者。中文资料分别保留项目中文文档、作者原创与独立译文的归属。
- `rolling`、`stable`、`current` 入口保留其滚动性质；固定版本资料单独列出，不把新版本资料标为已安装版本。
- 视频、音频、幻灯片、PDF、Notebook、仓库和交互练习按各自载体获取，不能把入口页或应用空壳当作全部正文。
- 按当前目标和缺口选择少量资料。查询目录不登记来源、不授予网络或索引权限，也不批量抓取全部条目；原有官方来源注册内容和请求键保持不变。
- 抓取、复制、索引和分发使用前核对原站条款及当前用途授权；公开阅读、注册后服务和付费课程分别处理。

## 自动材料任务

- 先检查当前身份、目标和用途内可复用的正文、索引及独立检查，再从目录按当前目标限量选材；缺少内容或选中来源不可用时才联网补搜。
- 官方与第三方候选都按实际正文的相关性、正确性、条件与示例、请求版本和可追溯性检查。优先匹配中文和明确版本，已知不可达的入口不作为本轮首选。
- 每个任务最多选择 12 个读取资源、补搜两轮，每轮保留至多八个搜索结果。只获取选中页面，章节跟随限制为一跳及具体缺口二跳。获取或检查失败自动更换策略和来源，达到所需覆盖就停止。
- PDF 自动选取当前相关章节的至多 20 个新页，保留原页码，后续章节复用原文件；无可用目录时先读少量起始页检查，不自动解析整本书。已明确提交的整份材料范围沿原合同处理。
- 搜索新发现的入口及其发现来源保存到当前身份的 `knowledge.discovered_source_catalog`，后续任务在目录阶段复用；不把运行时发现写回随包 JSON，也不跨账号共享。
- 只有当前用途和有效权限内的内容才能准备与复用。旧的仅官方目标不增加第三方许可；新目标的公开资料许可覆盖自动换站与替代，不逐站打断用户。访问受限、订阅或需要登录的内容自动寻找公开替代；正文处理仍使用本人配置的模型用途许可。

## 路线与节点备料

- 路线节点可保存 `material_plan`：教学主题、引用路线技术名称的 `technologies`、优先阅读的 `readings`。读取地址来自已有教材、已观察目录或内置候选；已上传文档记录精确版本。目录和候选只表达准备方向，不作为正文引用或质量通过的证明。
- `material_plan` 可省略，`readings` 可为空。制定阶段不为填满清单额外取材，也不等待未来课时正文；只有影响路线成立的关键外部事实和明确指定的材料继续沿原制定补证与审核流程处理。
- 读取路线教材快照时，缺少备料计划的节点根据原目标派生待备需求。相关技术只取本节点声明或涉及的路线技术；教材版本、项目约定继续来自同一条已确认路线。
- 进入节点后先复用当前权限内的正文、索引和检查。优先处理选定章节，材料不足时围绕具体缺口补充；再次询问同一节点复用原准备任务。未完成或已取消的任务不会被标成材料就绪。
- 节点材料检查要求实际正文支持编程概念、必要条件与可用示例。应用自身的工作台操作、权限和执行环境状态由宿主教学上下文提供，不要求公开教材证明这些产品事实。版本相关行为继续核对，通用概念不因网页没有标注精确补丁版本而自动成为缺口。
- 停止教学会停止该需求独占的资料发现、来源读取、处理和检查调度，已完成材料继续保留。其他活动需求仍在使用的任务继续处理；已派发调用的未知结果保留在原调用记录，不自动重发。

## 本轮检索

首批进行了五轮、33 次 Exa 检索。本次又进行多轮、48 次定向检索，围绕主流 Web/API、数据访问、测试、工程工具、科学计算/AI、桌面/移动、国内框架与中文原创教材补齐缺口，并追查维护者迁站与中文正文入口。两批共 81 次检索；搜索发现与实际入口检查分别记录。新增入口逐个进行了限量 GET，只读取最多 64 KiB 以观察状态、重定向、媒体类型和标题，不预先解析、索引整站或下载大型教材。

收录优先选择项目维护者、原作者、大学和有明确维护归属的社区。中文原创资料不只收基础语法，还包含框架教程、源码分析、公开实战项目、Notebook 与练习。转载聚合、盗版资源、只有营销介绍或必须付费登录才能取得的正文不用于填补覆盖；公开文章与作者的商业产品分开记录。版本较旧但仍有学习价值的材料注明实际技术代际，使用时按当前目标筛选。

以下清单由数据源生成。同一资料涉及多种语言时会在相应分组重复展示，总数按资料 ID 去重。每个条目的原站最终地址、检查时间、HTTP 状态和注意事项保存在数据源中。

<!-- catalog-tables -->

## 清单统计

共 **556** 个去重入口（原 146，本次新增 410）：项目官方 429，第三方作者 115，社区译文 12。中文入口 **114** 个：项目中文文档 55、中文作者/社区原创 47、独立社区译文 12。入口 HTTP 检查成功 543，待复核 13。

| 语言/方向 | 相关入口 | 项目官方 | 第三方及译文 | 中文 |
| --- | ---: | ---: | ---: | ---: |
| Python | 120 | 95 | 25 | 17 |
| Java | 111 | 93 | 18 | 24 |
| JavaScript | 143 | 119 | 24 | 30 |
| TypeScript | 144 | 123 | 21 | 30 |
| Go | 70 | 52 | 18 | 17 |
| C# | 80 | 70 | 10 | 12 |
| HTML | 22 | 11 | 11 | 5 |
| CSS | 28 | 11 | 17 | 7 |
| SQL | 31 | 19 | 12 | 4 |

## 主流生态核对范围

这里的覆盖指下列方向已登记具体项目或作者资料入口。精确版本、正文质量和可执行环境在使用时分别核对；新库和新框架不受此有限清单限制。

| 方向 | 本次重点补齐 |
| --- | --- |
| Python | HTTP/异步、Django/Flask/FastAPI 生态、ORM/迁移、任务队列；科学计算、数据分析、深度学习/AI；依赖管理、静态检查、测试、CLI、GUI 与浏览器自动化 |
| Java | Spring Security/Data/Cloud/Batch/消息/AI、Hibernate/Jakarta、Quarkus/Micronaut；序列化、日志、连接池、缓存、迁移、测试；MyBatis-Plus/Nacos/Sentinel/Dubbo 等中文生态 |
| JavaScript / TypeScript | Next/Angular/SvelteKit/Nuxt/Astro/Nest 等 Web/全栈框架；状态、路由、验证、ORM、实时通信；构建/单仓库/测试；React Native/Expo/Electron 与可视化 |
| Go | Web 路由、ORM/SQL 工具、驱动、CLI/配置、日志/观测、测试与 Mock；GoFrame/go-zero/Kratos/Kitex/Hertz；桌面与游戏示例 |
| C# | ASP.NET/Blazor、EF/Dapper/FreeSql/SqlSugar、DI/日志/验证/映射/韧性/消息；测试、MAUI/Avalonia/WPF/Unity/Godot；ABP/Furion/MASA 与中文实战源码 |
| HTML / CSS | Tailwind/Bootstrap/Sass/Less/PostCSS/Stylelint、布局、交互与可访问性；中文 CSS 原创、项目示例；组件库资料在对应 JS/TS 分组 |
| SQL | SQLite/MySQL/PostgreSQL、驱动、迁移、执行计划、优化与练习；dbt/SQLFluff/SQLMesh 和分析类资料；补充资料不扩展执行方言支持 |

## 中文资料索引

项目中文文档、原创作者和独立译文分别标记。原项目文档仓库优先于不明来源镜像；路径带中文语言码但实际回退英文的页面不计为中文正文。

| 资料与作者/项目 | 归属 | 方向与生态 | 版本说明 | HTTP |
| --- | --- | --- | --- | --- |
| [Python 3.12 Chinese Tutorial](https://docs.python.org/zh-cn/3.12/tutorial/index.html) / Python documentation translation team | 项目官方 | python | Python 3.12 | 200 |
| [Python Tutorial by Liao Xuefeng](https://liaoxuefeng.com/books/python/introduction/) / Liao Xuefeng | 第三方作者 | python | Python 3; inspect each chapter | 200 |
| [MyBatis 3 Chinese Documentation](https://mybatis.org/mybatis-3/zh_CN/index.html) / MyBatis project | 项目官方 | java / mybatis | MyBatis 3 | 200 |
| [JavaGuide Java Fundamentals](https://javaguide.cn/java/basis/) / JavaGuide / Snailclimb | 第三方作者 | java | article-specific | 200 |
| [Java Tutorial by Liao Xuefeng](https://liaoxuefeng.com/books/java/index.html) / Liao Xuefeng | 第三方作者 | java | publisher advertises Java 22; inspect individual chapters | 200 |
| [MDN JavaScript Guide in Chinese](https://developer.mozilla.org/zh-CN/docs/Web/JavaScript/Guide) / MDN translation contributors | 社区译文 | javascript | translation; compare original when necessary | 200 |
| [React Learn in Simplified Chinese](https://zh-hans.react.dev/learn) / React documentation translation team | 项目官方 | javascript, typescript / react | localized rolling documentation | 200 |
| [Vue Guide in Chinese](https://cn.vuejs.org/guide/introduction.html) / Vue team | 项目官方 | javascript, typescript / vue | Vue 3; check page | 200 |
| [The Modern JavaScript Tutorial in Chinese](https://zh.javascript.info/) / javascript.info Chinese contributors | 社区译文 | javascript | translation; verify synchronization | 200 |
| [TypeScript Documentation in Chinese](https://www.typescriptlang.org/zh/docs/) / TypeScript documentation team | 项目官方 | typescript | localized rolling documentation | 200 |
| [Type Challenges](https://github.com/type-challenges/type-challenges) / Type Challenges contributors | 第三方作者 | typescript | challenge and compiler specific | 200 |
| [GORM Chinese Guides](https://gorm.io/zh_CN/docs/index.html) / GORM project | 项目官方 | go / gorm | rolling | 200 |
| [Go by Example Chinese Translation](https://gobyexample-cn.github.io/) / gobyexample-cn contributors | 社区译文 | go | translation; verify upstream synchronization | 200 |
| [C# Language Documentation in Chinese](https://learn.microsoft.com/zh-cn/dotnet/csharp/) / Microsoft | 项目官方 | csharp | localized rolling documentation | 200 |
| [MDN HTML Reference in Chinese](https://developer.mozilla.org/zh-CN/docs/Web/HTML) / MDN translation contributors | 社区译文 | html | translation; feature support varies | 200 |
| [MDN CSS Reference in Chinese](https://developer.mozilla.org/zh-CN/docs/Web/CSS) / MDN translation contributors | 社区译文 | css | translation; feature support varies | 200 |
| [Flexbox Froggy](https://flexboxfroggy.com/) / Codepip | 第三方作者 | css | exercise-specific | 200 |
| [Grid Garden](https://cssgridgarden.com/) / Codepip | 第三方作者 | css | exercise-specific | 200 |
| [SQL Tutorial by Liao Xuefeng](https://liaoxuefeng.com/books/sql/introduction/index.html) / Liao Xuefeng | 第三方作者 | sql / mysql | chapter-specific; older MySQL examples | 200 |
| [A Tour of Go in Chinese](https://tour.go-zh.org/) / Go Chinese translation contributors | 社区译文 | go | translation; verify upstream synchronization | 200 |
| [Python - 100天从新手到大师](https://github.com/jackfrued/Python-100-Days) / 骆昊 / jackfrued | 第三方作者 | python / django, flask, numpy, pandas, matplotlib | chapter-specific; some examples use older packages | 200 |
| [聪明办法学 Python](https://github.com/datawhalechina/learn-python-the-smart-way) / 小雨姑娘与 Datawhale | 第三方作者 | python / jupyter | notebook-specific | 200 |
| [Joyful Pandas](https://github.com/datawhalechina/joyful-pandas) / Datawhale / Joyful Pandas 作者团队 | 第三方作者 | python / pandas | public web edition uses pandas 1.2; print edition differs | 200 |
| [深入浅出 PyTorch](https://github.com/datawhalechina/thorough-pytorch) / Datawhale 作者团队 | 第三方作者 | python / pytorch, jupyter | chapter-specific; ongoing series | 200 |
| [动手学深度学习](https://zh.d2l.ai/) / 阿斯顿·张、李沐、扎卡里·立顿、亚历山大·斯莫拉 | 第三方作者 | python / pytorch, tensorflow, mxnet | book and backend-specific versions | 200 |
| [动手学数据分析](https://github.com/datawhalechina/hands-on-data-analysis) / Datawhale 作者团队 | 第三方作者 | python / numpy, pandas, matplotlib, seaborn | notebook-specific | 200 |
| [Django 博客教程](https://www.zmrenwu.com/tutorials/hellodjango-blog-tutorial/) / 追梦人物 / zmrenwu | 第三方作者 | python / django | Django 2.2 second-edition tutorial; historical APIs | 200 |
| [Flask 入门教程](https://tutorial.helloflask.com/) / 李辉 Grey Li | 第三方作者 | python / flask | tutorial edition; not the complete commercial book | 200 |
| [HelloFlask 示例项目](https://github.com/greyli/helloflask) / 李辉 Grey Li / HelloFlask | 第三方作者 | python / flask, sqlalchemy, pytest | per-project dependency file; book editions differ | 200 |
| [FastAPI 中文教程](https://fastapi.tiangolo.com/zh/tutorial/) / FastAPI 翻译贡献者 | 项目官方 | python / fastapi, pydantic | rolling; translated pages may lag original | 200 |
| [Django 5.2 中文文档](https://docs.djangoproject.com/zh-hans/5.2/intro/) / Django 文档翻译团队 | 项目官方 | python / django | Django 5.2 | 200 |
| [APIFlask 中文文档](https://zh.apiflask.com/) / APIFlask / 李辉与贡献者 | 项目官方 | python / apiflask, flask | rolling; translated pages may lag original | 200 |
| [TensorFlow 中文教程](https://www.tensorflow.org/tutorials?hl=zh-cn) / TensorFlow 文档团队与翻译贡献者 | 项目官方 | python / tensorflow | tutorial-specific; some linked pages are English | 200 |
| [Hugging Face 中文 NLP 课程](https://huggingface.co/learn/llm-course/zh-CN/chapter1/1) / Hugging Face 课程团队与中文贡献者 | 项目官方 | python / transformers, datasets | chapter-specific; original and translated editions may differ | 200 |
| [Python Cookbook 中文版](https://python3-cookbook.readthedocs.io/zh_CN/latest/) / David Beazley、Brian K. Jones；熊能等译 | 社区译文 | python | Python Cookbook 3rd edition / Python 3.3 era | 200 |
| [MyBatis-Plus 指南](https://baomidou.com/introduce/) / 苞米豆 / MyBatis-Plus | 项目官方 | java / mybatis-plus, mybatis | release-specific; Spring Boot starters differ | 200 |
| [Nacos 中文文档](https://nacos.io/docs/latest/overview/) / Nacos 项目 | 项目官方 | java / nacos | latest alias; choose client and server family | 200 |
| [Sentinel 中文指南](https://github.com/alibaba/Sentinel/wiki) / Alibaba / Sentinel 贡献者 | 项目官方 | java / sentinel | wiki revision and adapter-version specific | 200 |
| [Apache Dubbo 中文文档](https://cn.dubbo.apache.org/zh-cn/overview/) / Apache Dubbo | 项目官方 | java / dubbo | version-selector | 200 |
| [Spring Cloud Alibaba 中文文档](https://sca.aliyun.com/docs/) / Spring Cloud Alibaba | 项目官方 | java / spring-cloud-alibaba, spring-cloud, nacos, sentinel | select matching Spring Boot and Spring Cloud train | 200 |
| [Apache Seata 中文文档](https://seata.apache.org/zh-cn/docs/overview/what-is-seata/) / Apache Seata | 项目官方 | java / seata | version-selector | 200 |
| [Apache RocketMQ 中文文档](https://rocketmq.apache.org/zh/docs/) / Apache RocketMQ | 项目官方 | java / rocketmq | version-selector; broker and client versions differ | 200 |
| [Apache ShardingSphere 中文文档](https://shardingsphere.apache.org/document/current/cn/overview/) / Apache ShardingSphere | 项目官方 | java / shardingsphere | current alias; select JDBC or Proxy product | 200 |
| [Hutool 参考文档](https://doc.hutool.cn/) / Hutool / dromara | 项目官方 | java / hutool | major-version-specific | 200 |
| [Druid 数据库连接池文档](https://github.com/alibaba/druid/wiki) / Alibaba / Druid 贡献者 | 项目官方 | java / druid, jdbc | release-specific; not Apache Druid analytics database | 200 |
| [Sa-Token 中文文档](https://sa-token.cc/) / dromara / Sa-Token | 项目官方 | java / sa-token | release and adapter-version specific | 200 |
| [XXL-JOB 官方文档](https://www.xuxueli.com/xxl-job/) / 许雪里 / XXL-JOB | 项目官方 | java / xxl-job | release-specific | 200 |
| [Redisson 中文指南](https://github.com/redisson/redisson/wiki/目录) / Redisson | 项目官方 | java / redisson, redis | edition and version specific; Redisson PRO is separate | 200 |
| [Fastjson2 项目文档](https://github.com/alibaba/fastjson2) / Alibaba / Fastjson2 | 项目官方 | java / fastjson2 | Fastjson2; not Fastjson 1.x | 200 |
| [JavaGuide Spring 专题](https://javaguide.cn/system-design/framework/spring/) / Guide 哥与 JavaGuide 贡献者 | 第三方作者 | java / spring, spring-boot, spring-security | article-specific | 200 |
| [二哥的 Java 进阶之路](https://javabetter.cn/) / 沉默王二与贡献者 | 第三方作者 | java / spring, spring-boot, maven, mybatis | chapter-specific | 200 |
| [凤凰架构](https://icyfenix.cn/) / 周志明 | 第三方作者 | java / spring, spring-boot | chapter-specific; published book and evolving online text | 200 |
| [mall 学习项目](https://github.com/macrozheng/mall) / macrozheng | 第三方作者 | java / spring-boot, spring-security, mybatis, redis | branch and dependency-file specific | 200 |
| [SpringBoot-Labs 中文实验](https://github.com/yudaocode/SpringBoot-Labs) / 芋道源码 / YunaiV | 第三方作者 | java / spring-boot, spring-cloud, spring-cloud-alibaba, dubbo | primarily Spring Boot 2.x; many historical Cloud components | 200 |
| [Spring Boot 学习示例](https://github.com/dyc87112/SpringBoot-Learning) / 程序猿 DD / 翟永超 | 第三方作者 | java / spring-boot, spring | branch-specific; includes Spring Boot 1.x and 2.x | 200 |
| [SpringAll 学习示例](https://github.com/wuyouzhuguli/SpringAll) / MrBird / wuyouzhuguli | 第三方作者 | java / spring-boot, spring-cloud, spring-security, spring-batch | module-specific; includes historical Spring OAuth/Cloud APIs | 200 |
| [Vite 官方中文指南](https://cn.vite.dev/guide/) / Vite 中文贡献者 | 项目官方 | javascript, typescript / vite | version-specific; Chinese and original editions may differ | 200 |
| [Pinia 中文指南](https://pinia.vuejs.org/zh/introduction.html) / Pinia / Vue 中文贡献者 | 项目官方 | javascript, typescript / pinia, vue | translation revision visible on site; may lag original | 200 |
| [Vue Router 中文指南](https://router.vuejs.org/zh/guide/) / Vue Router 中文贡献者 | 项目官方 | javascript, typescript / vue-router, vue | Vue Router 4 / Vue 3 | 200 |
| [Ant Design 中文文档](https://ant.design/docs/react/introduce-cn) / Ant Design 团队与贡献者 | 项目官方 | javascript, typescript / ant-design, react | major-version-specific | 200 |
| [Element Plus 中文指南](https://element-plus.org/zh-CN/guide/design.html) / Element Plus 贡献者 | 项目官方 | javascript, typescript / element-plus, vue | Vue 3 / Element Plus | 200 |
| [Apache ECharts 中文手册](https://echarts.apache.org/handbook/zh/index.html) / Apache ECharts | 项目官方 | javascript, typescript / echarts | distinguish ECharts 5/6 migration docs | 200 |
| [Axios 中文文档](https://axios-http.com/zh/docs/intro) / Axios 中文贡献者 | 项目官方 | javascript, typescript / axios | translation-version-specific | 200 |
| [pnpm 中文文档](https://pnpm.io/zh/) / pnpm 中文贡献者 | 项目官方 | javascript, typescript / pnpm | major-version-specific | 200 |
| [Vitest 中文指南](https://cn.vitest.dev/guide/) / Vitest 中文贡献者 | 项目官方 | javascript, typescript / vitest | version-specific | 200 |
| [Nuxt 中文文档](https://nuxt.com.cn/docs/getting-started/introduction) / Nuxt 中文社区 | 社区译文 | javascript, typescript / nuxt, vue | community translation; resolve matching original major | 网络错误 |
| [VueUse 中文指南](https://vueuse.org/zh/guide/) / VueUse 中文贡献者 | 项目官方 | javascript, typescript / vueuse, vue | translation coverage varies | 200 |
| [uni-app 文档](https://uniapp.dcloud.net.cn/) / DCloud / uni-app | 项目官方 | javascript, typescript / uniapp, vue | target and toolchain specific; cloud products are separate | 200 |
| [Taro 中文文档](https://docs.taro.zone/docs/) / Taro 贡献者 | 项目官方 | javascript, typescript / taro, react | target and major-version specific | 网络错误 |
| [Umi 中文文档](https://umijs.org/docs/introduce/introduce) / Umi 贡献者 | 项目官方 | javascript, typescript / umi, react | major-version-specific | 200 |
| [Naive UI 中文文档](https://github.com/tusen-ai/naive-ui/tree/main/demo/pages/docs) / Naive UI 贡献者 | 项目官方 | javascript, typescript / naiveui, vue | Vue 3; entry needs client-side rendering | 200 |
| [Vant 中文文档](https://vant-ui.github.io/vant/#/zh-CN/) / Vant 贡献者 | 项目官方 | javascript, typescript / vant, vue | hash-routed docs; resolve actual selected page when acquiring | 200 |
| [网道 JavaScript 教程](https://wangdoc.com/javascript/) / 阮一峰 / 网道 | 第三方作者 | javascript, typescript | chapter-specific | 200 |
| [ECMAScript 6 入门](https://es6.ruanyifeng.com/) / 阮一峰 | 第三方作者 | javascript, typescript | rolling; proposals and standardized features distinguished | 200 |
| [网道 TypeScript 教程](https://wangdoc.com/typescript/) / 阮一峰 / 网道 | 第三方作者 | javascript, typescript | chapter-specific; distinguishes legacy and new decorators | 200 |
| [TypeScript 入门教程](https://ts.xcatliu.com/) / xcatliu | 第三方作者 | javascript, typescript | chapter-specific | 200 |
| [冴羽 JavaScript 与 TypeScript 深入系列](https://github.com/mqyqingfeng/Blog) / 冴羽 / mqyqingfeng | 第三方作者 | javascript, typescript / react, nextjs, svelte | article-specific; historical series and modern articles coexist | 200 |
| [mini-vue 源码学习项目](https://github.com/cuixiaorui/mini-vue) / 崔学锐与贡献者 | 第三方作者 | javascript, typescript / vue | educational implementation; not full Vue compatibility | 200 |
| [Vue.js 技术揭秘](https://ustbhuangyi.github.io/vue-analysis/) / 黄轶 | 第三方作者 | javascript, typescript / vue | Vue 2 source; not Vue 3 reactivity | 200 |
| [深入浅出 Webpack](https://github.com/gwuhaolin/dive-into-webpack) / 吴浩麟 | 第三方作者 | javascript, typescript / webpack | 2017-era webpack; historical configuration | 404 |
| [Node.js 包教不包会](https://github.com/alsotang/node-lessons) / alsotang | 第三方作者 | javascript, typescript / nodejs, express | historical Node/Express lessons; inspect individual dependencies | 200 |
| [网道 HTML 教程](https://wangdoc.com/html/) / 阮一峰 / 网道 | 第三方作者 | html, css | chapter-specific | 200 |
| [张鑫旭 CSS 与 Web 原创文章](https://www.zhangxinxu.com/wordpress/category/css/) / 张鑫旭 | 第三方作者 | html, css | article and browser-support specific | 200 |
| [iCSS CSS 奇思妙想](https://github.com/chokcoco/iCSS) / ChokCoco / 国服第一切图仔 | 第三方作者 | html, css | example and browser-support specific | 200 |
| [CSS Inspiration](https://github.com/chokcoco/CSS-Inspiration) / ChokCoco | 第三方作者 | html, css | example and browser-support specific | 200 |
| [深入理解 TypeScript 中文版](https://jkchao.github.io/typescript-book-chinese/) / Basarat Ali Syed；jkchao 等译 | 社区译文 | javascript, typescript | community translation; original book version may differ | 200 |
| [Gin 中文文档](https://gin-gonic.com/zh-cn/docs/) / Gin 文档贡献者 | 项目官方 | go / gin | version and translation specific | 200 |
| [GoFrame 中文文档](https://goframe.org/docs) / GoFrame 贡献者 | 项目官方 | go / goframe | version-selector | 403 |
| [go-zero 中文指南](https://go-zero.dev/zh-cn/guides/) / go-zero 贡献者 | 项目官方 | go / go-zero | rolling; generator and runtime versions must match | 200 |
| [Kratos 中文文档](https://go-kratos.dev/zh-cn/docs/) / Kratos 贡献者 | 项目官方 | go / kratos | Kratos v3; do not mix v2 module paths | 200 |
| [Kitex 中文文档](https://www.cloudwego.io/zh/docs/kitex/) / CloudWeGo / 字节跳动贡献者 | 项目官方 | go / kitex | release-specific | 200 |
| [Hertz 中文文档](https://www.cloudwego.io/zh/docs/hertz/) / CloudWeGo / 字节跳动贡献者 | 项目官方 | go / hertz | release-specific | 200 |
| [李文周 Go 原创教程](https://liwenzhou.com/) / 李文周 / Q1mi | 第三方作者 | go / gin, zap, viper | article-specific; public blog and course overview differ | 200 |
| [Go 语言高级编程](https://chai2010.cn/advanced-go-programming-book/) / 柴树杉、曹春晖 | 第三方作者 | go / grpc, protobuf | online edition; distinguish commercial second edition | 200 |
| [七天用 Go 从零实现系列](https://geektutu.com/books/7days-golang/) / 极客兔兔 | 第三方作者 | go | 2019-era educational implementations | 200 |
| [Go 语言设计与实现](https://draven.co/golang/) / Draveness | 第三方作者 | go | source-analysis chapter-specific Go revision | 200 |
| [煎鱼的 Go 文章](https://eddycjy.com/) / 煎鱼 / 脑子进煎鱼了 | 第三方作者 | go / gin, grpc | article-specific | 网络错误 |
| [Tony Bai Go 原创文章](https://tonybai.com/) / Tony Bai | 第三方作者 | go | article-specific | 200 |
| [Go 语言圣经中文版](https://gopl-zh.github.io/) / Alan A. A. Donovan、Brian W. Kernighan；柴树杉等译 | 社区译文 | go | The Go Programming Language 2015 edition; predates generics | 200 |
| [通过测试学习 Go 中文版](https://studygolang.gitbook.io/learn-go-with-tests/) / Chris James；Go 中文社区译者 | 社区译文 | go | community translation; original revision may differ | 200 |
| [FreeSql 中文指南](https://freesql.net/guide/) / FreeSql / .NET Core Community | 项目官方 | csharp / freesql | provider and release specific | 200 |
| [SqlSugar 中文文档](https://www.donet5.com/Home/Doc) / SqlSugar / dotnetnext | 项目官方 | csharp / sqlsugar | package and provider version specific | 200 |
| [Furion 中文文档](https://furion.net/docs/) / Furion / 百小僧 | 项目官方 | csharp / furion | release-specific; public documentation and paid support differ | 200 |
| [MASA Framework 中文项目说明](https://github.com/masastack/MASA.Framework) / MASA Stack | 项目官方 | csharp / masa, aspnetcore | selected release; documentation website may require client rendering | 200 |
| [ASP.NET Core 中文文档](https://learn.microsoft.com/zh-cn/aspnet/core/) / Microsoft 文档团队 | 项目官方 | csharp / aspnetcore | select exact ASP.NET Core documentation view | 200 |
| [EF Core 中文文档](https://learn.microsoft.com/zh-cn/ef/core/) / Microsoft 文档团队 | 项目官方 | csharp / efcore | target EF and provider version specific | 200 |
| [Blazor 中文文档](https://learn.microsoft.com/zh-cn/aspnet/core/blazor/) / Microsoft 文档团队 | 项目官方 | csharp / blazor, aspnetcore | select exact ASP.NET Core documentation view | 200 |
| [Blog.Core 中文实战项目](https://github.com/anjoy8/Blog.Core) / 老张的哲学与贡献者 | 第三方作者 | csharp / aspnetcore, sqlsugar, serilog, automapper | branch-specific; repository description and README target versions differ | 200 |
| [.NET Core 中文示例项目](https://github.com/luoyunchong/dotnetcore-examples) / iGeekFan / luoyunchong | 第三方作者 | csharp / aspnetcore, freesql, automapper | historical examples; per-project target framework | 200 |
| [.NET 中文实战教程示例](https://github.com/Meowv/Blog) / Meowv | 第三方作者 | csharp / aspnetcore, abp | .NET 5 / ABP vNext historical tutorial; inspect selected branch | 200 |
| [Wonderful SQL](https://github.com/datawhalechina/wonderful-sql) / Datawhale 作者团队 | 第三方作者 | sql / mysql | MySQL 8.0 course; selected exercise dialect matters | 200 |
| [图解 MySQL](https://www.xiaolincoding.com/mysql/) / 小林 coding | 第三方作者 | sql / mysql | article-specific MySQL version | 200 |
| [PostgreSQL 中文手册翻译项目](https://github.com/postgres-cn/pgdoc-cn) / 彭煜玮与 PostgreSQL 中国用户会翻译组 | 社区译文 | sql / postgresql | version-specific SGML sources and release downloads; 15.x and later separated by major | 200 |
| [CAP 中文文档](https://cap.dotnetcore.xyz/user-guide/zh/getting-started/quick-start/) / .NET Core Community / CAP | 项目官方 | csharp / cap | release and transport specific | 200 |

## 待复核入口

HTTP 403 保留访问拒绝，404 保留不可用观察，连接或证书等错误保留实际异常类型。未绕过站点验证；`reachable_only=True` 可排除这些候选。

| 资料 | 本次保留的观察 |
| --- | --- |
| [Get Started with Java](https://www.baeldung.com/get-started-with-java-series) / Baeldung | HTTP 403 |
| [Spring Boot Tutorials](https://www.baeldung.com/spring-boot) / Baeldung | HTTP 403 |
| [Exploring TypeScript](https://exploringjs.com/ts/book/index.html) / Axel Rauschmayer | HTTP 404 |
| [OpenCV Python Tutorials](https://docs.opencv.org/4.x/d6/d00/tutorial_py_root.html) / OpenCV contributors | HTTP 403 |
| [OkHttp Documentation](https://square.github.io/okhttp/) / Square / OkHttp maintainers | ConnectError |
| [Real Python Web Development Tutorials](https://realpython.com/tutorials/web-dev/) / Real Python authors | HTTP 403 |
| [Real Python Testing Tutorials](https://realpython.com/tutorials/testing/) / Real Python authors | HTTP 403 |
| [Real Python Development Tools Tutorials](https://realpython.com/tutorials/tools/) / Real Python authors | HTTP 403 |
| [Nuxt 中文文档](https://nuxt.com.cn/docs/getting-started/introduction) / Nuxt 中文社区 | ConnectError |
| [Taro 中文文档](https://docs.taro.zone/docs/) / Taro 贡献者 | ConnectError |
| [深入浅出 Webpack](https://github.com/gwuhaolin/dive-into-webpack) / 吴浩麟 | HTTP 404 |
| [GoFrame 中文文档](https://goframe.org/docs) / GoFrame 贡献者 | HTTP 403 |
| [煎鱼的 Go 文章](https://eddycjy.com/) / 煎鱼 / 脑子进煎鱼了 | ConnectError |

## 使用时的版本与获取注意事项

- Spring Boot/Cloud、JUnit、Vue 2/3、Svelte 4/5、Next 路由模式、Go 模块代际和 .NET 目标框架分别匹配；历史教程保留版本说明。
- 项目文档、原作者教程与社区译文都保留来源；译文更新落后、章节未完成、入口跳转和客户端渲染按实际页面处理。
- Datawhale PyTorch 在线站与 Markdown 更新不同步；Joyful Pandas 公开版与纸书版本不同；这些区别已写入条目。
- 部分 .NET 组件或商业增强版的许可要求随版本变化。公开文档入口不等于安装、再分发或付费产品授权。
- 正文、图片、代码和练习可具有不同许可；非商用或禁止转载的作者书籍保留说明，获取和重用时按实际用途核对。
- 查询目录不触发网络、解析、Embedding 或安装。正式材料消费者的授权与按需解析链独立处理。

## Python

| 资料与发布者 | 来源 | 生态 | 载体 / 正文语言 | 适用版本 | HTTP |
| --- | --- | --- | --- | --- | --- |
| [Python Tutorial](https://docs.python.org/3/tutorial/index.html) / Python Software Foundation | 项目官方 | 语言/通用 | 网页、教程 / en | rolling | 200 |
| [Python 3.12 Tutorial](https://docs.python.org/3.12/tutorial/index.html) / Python Software Foundation | 项目官方 | 语言/通用 | 网页、教程 / en | Python 3.12 | 200 |
| [Python 3.12 Standard Library](https://docs.python.org/3.12/library/index.html) / Python Software Foundation | 项目官方 | 语言/通用 | 网页、参考 / en | Python 3.12 | 200 |
| [Python 3.12 Language Reference](https://docs.python.org/3.12/reference/index.html) / Python Software Foundation | 项目官方 | 语言/通用 | 网页、规范 / en | Python 3.12 | 200 |
| [Python 3.12 Chinese Tutorial](https://docs.python.org/zh-cn/3.12/tutorial/index.html) / Python documentation translation team | 项目官方 | 语言/通用 | 网页、教程 / zh-CN | Python 3.12 | 200 |
| [Download Python 3.12 Documentation](https://docs.python.org/3.12/download.html) / Python Software Foundation | 项目官方 | 语言/通用 | 网页、PDF、EPUB、下载包 / en | Python 3.12 | 200 |
| [Python Packaging User Guide](https://packaging.python.org/en/latest/tutorials/) / Python Packaging Authority | 项目官方 | packaging | 网页、教程 / en | rolling | 200 |
| [pytest Getting Started](https://docs.pytest.org/en/stable/getting-started.html) / pytest contributors | 项目官方 | pytest | 网页、教程、参考 / en | stable alias | 200 |
| [Flask Tutorial](https://flask.palletsprojects.com/en/stable/tutorial/) / Pallets | 项目官方 | flask | 网页、教程、示例/源码 / en | stable alias | 200 |
| [Django Introduction and Tutorial](https://docs.djangoproject.com/en/stable/intro/) / Django Software Foundation | 项目官方 | django | 网页、教程 / en | stable alias | 200 |
| [FastAPI Tutorial](https://fastapi.tiangolo.com/tutorial/) / FastAPI project | 项目官方 | fastapi | 网页、教程、示例/源码 / en | rolling | 200 |
| [NumPy Quickstart](https://numpy.org/doc/stable/user/quickstart.html) / NumPy developers | 项目官方 | numpy | 网页、教程 / en | stable alias | 200 |
| [pandas Getting Started](https://pandas.pydata.org/docs/getting_started/index.html) / pandas developers | 项目官方 | pandas | 网页、教程、Notebook / en | rolling | 200 |
| [Matplotlib Tutorials](https://matplotlib.org/stable/tutorials/index.html) / Matplotlib developers | 项目官方 | matplotlib | 网页、教程、Notebook / en | stable alias | 200 |
| [SQLAlchemy Unified Tutorial](https://docs.sqlalchemy.org/en/20/tutorial/) / SQLAlchemy project | 项目官方 | sqlalchemy | 网页、教程 / en | SQLAlchemy 2.0 | 200 |
| [Python for Everybody Course Materials](https://www.py4e.com/materials) / Charles Severance | 第三方作者 | 语言/通用 | 网页、课程、视频、音频、幻灯片、示例/源码、书籍 / en | Python 3 | 200 |
| [Python for Everybody: Exploring Data Using Python 3](https://do1.dr-chuck.com/pythonlearn/EN_us/pythonlearn.pdf) / Charles Severance | 第三方作者 | 语言/通用 | PDF、书籍 / en | Python 3; edition-specific examples | 200 |
| [Think Python, Third Edition](https://allendowney.github.io/ThinkPython/) / Allen B. Downey | 第三方作者 | 语言/通用 | 网页、书籍、Notebook、练习 / en | third edition | 200 |
| [Practical Python Programming](https://dabeaz-course.github.io/practical-python/) / David Beazley | 第三方作者 | 语言/通用 | 网页、课程、练习、示例/源码 / en | course states Python 3.6+ | 200 |
| [CS50 Introduction to Programming with Python](https://cs50.harvard.edu/python/) / Harvard CS50 | 第三方作者 | 语言/通用 | 网页、课程、视频、练习 / en | course edition; resolve before use | 200 |
| [Automate the Boring Stuff with Python](https://automatetheboringstuff.com/) / Al Sweigart | 第三方作者 | 语言/通用 | 网页、书籍、示例/源码 / en | edition-specific; inspect chapter dependencies | 200 |
| [Python Tutorial by Liao Xuefeng](https://liaoxuefeng.com/books/python/introduction/) / Liao Xuefeng | 第三方作者 | 语言/通用 | 网页、教程 / zh-CN | Python 3; inspect each chapter | 200 |
| [Exercism Python Track](https://exercism.org/tracks/python) / Exercism community | 第三方作者 | 语言/通用 | 网页、练习、交互 / en | track-specific | 200 |
| [freeCodeCamp Curriculum](https://www.freecodecamp.org/learn/) / freeCodeCamp | 第三方作者 | 语言/通用 | 网页、课程、交互、项目 / en | certification edition | 200 |
| [Flask Release History](https://flask.palletsprojects.com/en/stable/changes/) / Pallets | 项目官方 | flask | 网页、参考 / en | release-specific entries; stable URL is not an immutable version snapshot | 200 |
| [Requests Quickstart](https://docs.python-requests.org/en/stable/user/quickstart/) / Requests maintainers | 项目官方 | requests | 网页、教程 / en | stable alias | 200 |
| [HTTPX Documentation](https://www.python-httpx.org/) / Encode / HTTPX maintainers | 项目官方 | httpx | 网页、参考 / en | rolling; resolve library major and runtime compatibility before use | 200 |
| [aiohttp Documentation](https://docs.aiohttp.org/en/stable/) / aiohttp maintainers | 项目官方 | aiohttp | 网页、参考 / en | stable alias | 200 |
| [Pydantic Validation Documentation](https://docs.pydantic.dev/latest/) / Pydantic | 项目官方 | pydantic | 网页、参考 / en | latest alias; distinguish Pydantic 1 and 2 | 200 |
| [Django REST Framework Tutorial](https://www.django-rest-framework.org/tutorial/quickstart/) / Django REST framework maintainers | 项目官方 | django, django-rest-framework | 网页、教程 / en | rolling; check Django compatibility | 200 |
| [Starlette Documentation](https://starlette.dev/) / Encode / Starlette maintainers | 项目官方 | starlette | 网页、参考 / en | rolling; resolve library major and runtime compatibility before use | 200 |
| [Uvicorn Documentation](https://uvicorn.dev/) / Uvicorn maintainers | 项目官方 | uvicorn | 网页、参考 / en | rolling; resolve library major and runtime compatibility before use | 200 |
| [Gunicorn Documentation](https://gunicorn.org/quickstart/) / Gunicorn maintainers | 项目官方 | gunicorn | 网页、参考 / en | stable alias; OS support is separate | 200 |
| [Jinja Documentation](https://jinja.palletsprojects.com/en/stable/) / Pallets | 项目官方 | jinja | 网页、参考 / en | stable alias | 200 |
| [Celery Documentation](https://docs.celeryq.dev/en/stable/) / Celery maintainers | 项目官方 | celery | 网页、参考 / en | stable alias | 200 |
| [Alembic Tutorial](https://alembic.sqlalchemy.org/en/latest/tutorial.html) / SQLAlchemy project | 项目官方 | alembic, sqlalchemy | 网页、教程 / en | latest alias | 200 |
| [Psycopg 3 Documentation](https://www.psycopg.org/psycopg3/docs/) / Psycopg maintainers | 项目官方 | psycopg, postgresql | 网页、参考 / en | Psycopg 3; not Psycopg 2 | 200 |
| [PyMySQL Documentation](https://pymysql.readthedocs.io/en/latest/) / PyMySQL maintainers | 项目官方 | pymysql, mysql | 网页、参考 / en | latest alias | 200 |
| [SQLModel Tutorial](https://sqlmodel.tiangolo.com/tutorial/) / SQLModel project | 项目官方 | sqlmodel, sqlalchemy, pydantic | 网页、教程 / en | rolling | 200 |
| [redis-py Guide](https://redis.io/docs/latest/develop/clients/redis-py/) / Redis | 项目官方 | redis, redis-py | 网页、参考 / en | latest alias | 200 |
| [SciPy User Guide](https://docs.scipy.org/doc/scipy/tutorial/) / SciPy developers | 项目官方 | scipy | 网页、教程 / en | rolling | 200 |
| [scikit-learn User Guide](https://scikit-learn.org/stable/user_guide.html) / scikit-learn developers | 项目官方 | scikit-learn | 网页、参考 / en | stable alias | 200 |
| [Polars User Guide](https://docs.pola.rs/user-guide/) / Polars developers | 项目官方 | polars | 网页、参考 / en | rolling; resolve library major and runtime compatibility before use | 200 |
| [seaborn Tutorial](https://seaborn.pydata.org/tutorial.html) / seaborn developers | 项目官方 | seaborn | 网页、教程 / en | rolling | 200 |
| [Plotly Python Documentation](https://plotly.com/python/) / Plotly | 项目官方 | plotly | 网页、教程、示例/源码 / en | rolling | 200 |
| [JupyterLab User Guide](https://jupyterlab.readthedocs.io/en/stable/user/) / Project Jupyter | 项目官方 | jupyter, jupyterlab | 网页、参考 / en | stable alias | 200 |
| [PyTorch Tutorials](https://docs.pytorch.org/tutorials/) / PyTorch contributors | 项目官方 | pytorch | 网页、教程、Notebook、视频 / en | tutorial-specific; check CPU/GPU and torch versions | 200 |
| [TensorFlow Tutorials](https://www.tensorflow.org/tutorials) / TensorFlow contributors | 项目官方 | tensorflow | 网页、教程、Notebook / en | tutorial-specific; distinguish TensorFlow and Keras versions | 200 |
| [Keras Developer Guides](https://keras.io/guides/) / Keras team | 项目官方 | keras | 网页、教程 / en | rolling; inspect selected backend | 200 |
| [Transformers Documentation](https://huggingface.co/docs/transformers/index) / Hugging Face | 项目官方 | transformers | 网页、参考 / en | rolling; model downloads and execution are separate | 200 |
| [Datasets Documentation](https://huggingface.co/docs/datasets/index) / Hugging Face | 项目官方 | datasets | 网页、参考 / en | rolling; dataset-specific rights and downloads are separate | 200 |
| [LangChain Python Documentation](https://docs.langchain.com/oss/python/langchain/overview) / LangChain | 项目官方 | langchain | 网页、参考 / en | rolling; major-version-specific APIs | 200 |
| [LlamaIndex Python Documentation](https://docs.llamaindex.ai/en/stable/) / LlamaIndex | 项目官方 | llamaindex | 网页、参考 / en | stable alias | 200 |
| [SymPy Tutorial](https://docs.sympy.org/latest/tutorials/intro-tutorial/index.html) / SymPy developers | 项目官方 | sympy | 网页、教程 / en | latest alias | 200 |
| [NetworkX Tutorial](https://networkx.org/documentation/stable/tutorial.html) / NetworkX developers | 项目官方 | networkx | 网页、教程 / en | stable alias | 200 |
| [Apache Arrow Python Documentation](https://arrow.apache.org/docs/python/) / Apache Arrow | 项目官方 | pyarrow | 网页、参考 / en | rolling; resolve library major and runtime compatibility before use | 200 |
| [Dask Documentation](https://docs.dask.org/en/stable/) / Dask developers | 项目官方 | dask | 网页、参考 / en | stable alias | 200 |
| [PySpark Documentation](https://spark.apache.org/docs/latest/api/python/) / Apache Spark | 项目官方 | pyspark | 网页、参考 / en | latest alias; Java and Spark versions must match | 200 |
| [Apache Airflow Tutorials](https://airflow.apache.org/docs/apache-airflow/stable/tutorial/) / Apache Airflow | 项目官方 | airflow | 网页、教程 / en | stable alias; major-version-specific deployment | 200 |
| [Click Documentation](https://click.palletsprojects.com/en/stable/) / Pallets | 项目官方 | click | 网页、参考 / en | stable alias | 200 |
| [Typer Tutorial](https://typer.tiangolo.com/tutorial/) / Typer project | 项目官方 | typer | 网页、教程 / en | rolling | 200 |
| [Rich Documentation](https://rich.readthedocs.io/en/stable/) / Textualize | 项目官方 | rich | 网页、参考 / en | stable alias | 200 |
| [uv Documentation](https://docs.astral.sh/uv/) / Astral | 项目官方 | uv, packaging | 网页、参考 / en | rolling; resolve library major and runtime compatibility before use | 200 |
| [pip Documentation](https://pip.pypa.io/en/stable/) / Python Packaging Authority | 项目官方 | pip, packaging | 网页、参考 / en | stable alias | 200 |
| [Poetry Documentation](https://python-poetry.org/docs/) / Poetry maintainers | 项目官方 | poetry, packaging | 网页、参考 / en | rolling; resolve library major and runtime compatibility before use | 200 |
| [Ruff Documentation](https://docs.astral.sh/ruff/) / Astral | 项目官方 | ruff | 网页、参考 / en | rolling; resolve library major and runtime compatibility before use | 200 |
| [mypy Documentation](https://mypy.readthedocs.io/en/stable/) / mypy contributors | 项目官方 | mypy | 网页、参考 / en | stable alias | 200 |
| [Black Documentation](https://black.readthedocs.io/en/stable/) / Python Software Foundation / Black maintainers | 项目官方 | black | 网页、参考 / en | stable alias | 200 |
| [tox Documentation](https://tox.wiki/en/stable/) / tox developers | 项目官方 | tox | 网页、参考 / en | stable alias | 200 |
| [Hypothesis Documentation](https://hypothesis.readthedocs.io/en/latest/) / HypothesisWorks | 项目官方 | hypothesis | 网页、参考 / en | latest alias | 200 |
| [Coverage.py Documentation](https://coverage.readthedocs.io/en/latest/) / Ned Batchelder and contributors | 项目官方 | coverage | 网页、参考 / en | latest alias | 200 |
| [Sphinx Documentation](https://www.sphinx-doc.org/en/master/) / Sphinx developers | 项目官方 | sphinx | 网页、参考 / en | master documentation; resolve released version before use | 200 |
| [Beautiful Soup Documentation](https://www.crummy.com/software/BeautifulSoup/bs4/doc/) / Leonard Richardson | 项目官方 | beautifulsoup | 网页、参考 / en | Beautiful Soup 4 | 200 |
| [lxml Tutorial](https://lxml.de/tutorial.html) / lxml developers | 项目官方 | lxml | 网页、教程 / en | rolling | 200 |
| [Scrapy Documentation](https://docs.scrapy.org/en/latest/) / Scrapy maintainers | 项目官方 | scrapy | 网页、参考 / en | latest alias | 200 |
| [Pillow Handbook](https://pillow.readthedocs.io/en/stable/handbook/) / Pillow contributors | 项目官方 | pillow | 网页、参考 / en | stable alias | 200 |
| [OpenCV Python Tutorials](https://docs.opencv.org/4.x/d6/d00/tutorial_py_root.html) / OpenCV contributors | 项目官方 | opencv | 网页、教程 / en | OpenCV 4.x | 403 |
| [Qt for Python Tutorials](https://doc.qt.io/qtforpython-6/tutorials/index.html) / The Qt Company | 项目官方 | pyside6 | 网页、教程、示例/源码 / en | PySide6 / Qt 6; check binding and Qt versions | 200 |
| [PyQt6 Reference Guide](https://www.riverbankcomputing.com/static/Docs/PyQt6/index.html) / Riverbank Computing | 项目官方 | pyqt6 | 网页、参考 / en | PyQt6; check license and Qt version | 200 |
| [Python 3.12 Tkinter Reference](https://docs.python.org/3.12/library/tkinter.html) / Python Software Foundation | 项目官方 | tkinter | 网页、参考 / en | Python 3.12 | 200 |
| [Kivy Documentation](https://kivy.org/doc/stable/) / Kivy contributors | 项目官方 | kivy | 网页、参考 / en | stable alias | 200 |
| [pygame Documentation](https://www.pygame.org/docs/) / pygame contributors | 项目官方 | pygame | 网页、教程、参考 / en | documentation-version-specific | 200 |
| [Streamlit Documentation](https://docs.streamlit.io/) / Streamlit | 项目官方 | streamlit | 网页、参考 / en | rolling; resolve library major and runtime compatibility before use | 200 |
| [Gradio Guides](https://www.gradio.app/guides) / Gradio / Hugging Face | 项目官方 | gradio | 网页、教程 / en | rolling | 200 |
| [Dash Documentation](https://dash.plotly.com/) / Plotly | 项目官方 | dash | 网页、参考 / en | rolling; resolve library major and runtime compatibility before use | 200 |
| [cryptography Documentation](https://cryptography.io/en/latest/) / Python Cryptographic Authority | 项目官方 | cryptography | 网页、参考 / en | latest alias; cryptographic protocol choices require their own review | 200 |
| [gRPC Language Guides](https://grpc.io/docs/) / gRPC contributors | 项目官方 | grpc | 网页、参考 / en | select language and runtime guide; language support differs | 200 |
| [OpenTelemetry Language APIs and SDKs](https://opentelemetry.io/docs/languages/) / OpenTelemetry contributors / CNCF | 项目官方 | opentelemetry | 网页、参考 / en | language and signal stability differ | 200 |
| [Redis Client Libraries](https://redis.io/docs/latest/develop/clients/) / Redis | 项目官方 | redis | 网页、参考 / en | latest alias; distinguish server, client and license versions | 200 |
| [MongoDB Drivers](https://www.mongodb.com/docs/drivers/) / MongoDB | 项目官方 | mongodb | 网页、参考 / en | driver-language and server-version specific | 200 |
| [RabbitMQ Tutorials](https://www.rabbitmq.com/tutorials) / RabbitMQ maintainers | 项目官方 | rabbitmq | 网页、教程、示例/源码 / en | language-specific examples; not all SDKs have every tutorial | 200 |
| [Protocol Buffers Tutorials](https://protobuf.dev/getting-started/) / Protocol Buffers contributors | 项目官方 | protobuf | 网页、教程、示例/源码 / en | language-generator and runtime version specific | 200 |
| [Real Python Web Development Tutorials](https://realpython.com/tutorials/web-dev/) / Real Python authors | 第三方作者 | django, flask, fastapi | 网页、教程 / en | article-specific | 403 |
| [Real Python Testing Tutorials](https://realpython.com/tutorials/testing/) / Real Python authors | 第三方作者 | pytest | 网页、教程 / en | article-specific | 403 |
| [Real Python Development Tools Tutorials](https://realpython.com/tutorials/tools/) / Real Python authors | 第三方作者 | uv, poetry, ruff, mypy | 网页、教程 / en | article-specific | 403 |
| [Architecture Patterns with Python](https://www.cosmicpython.com/book/preface.html) / Harry Percival and Bob Gregory | 第三方作者 | flask, sqlalchemy, pytest | 网页、书籍、示例/源码 / en | 2020 book; historical dependency APIs | 200 |
| [Python Data Science Handbook](https://jakevdp.github.io/PythonDataScienceHandbook/) / Jake VanderPlas | 第三方作者 | numpy, pandas, matplotlib, scikit-learn, jupyter | 网页、书籍、Notebook / en | online edition; inspect notebook dependencies | 200 |
| [Python GUIs Tutorials](https://www.pythonguis.com/tutorials/) / Martin Fitzpatrick and contributors | 第三方作者 | pyside6, pyqt6, tkinter, kivy, streamlit | 网页、教程 / en | toolkit and article-version specific | 200 |
| [Python - 100天从新手到大师](https://github.com/jackfrued/Python-100-Days) / 骆昊 / jackfrued | 第三方作者 | django, flask, numpy, pandas, matplotlib | 仓库、Markdown、Notebook、教程 / zh-CN | chapter-specific; some examples use older packages | 200 |
| [聪明办法学 Python](https://github.com/datawhalechina/learn-python-the-smart-way) / 小雨姑娘与 Datawhale | 第三方作者 | jupyter | 仓库、Notebook、课程 / zh-CN | notebook-specific | 200 |
| [Joyful Pandas](https://github.com/datawhalechina/joyful-pandas) / Datawhale / Joyful Pandas 作者团队 | 第三方作者 | pandas | 仓库、Notebook、书籍、练习 / zh-CN | public web edition uses pandas 1.2; print edition differs | 200 |
| [深入浅出 PyTorch](https://github.com/datawhalechina/thorough-pytorch) / Datawhale 作者团队 | 第三方作者 | pytorch, jupyter | 仓库、Markdown、Notebook、课程、视频 / zh-CN | chapter-specific; ongoing series | 200 |
| [动手学深度学习](https://zh.d2l.ai/) / 阿斯顿·张、李沐、扎卡里·立顿、亚历山大·斯莫拉 | 第三方作者 | pytorch, tensorflow, mxnet | 网页、书籍、Notebook、视频 / zh-CN | book and backend-specific versions | 200 |
| [动手学数据分析](https://github.com/datawhalechina/hands-on-data-analysis) / Datawhale 作者团队 | 第三方作者 | numpy, pandas, matplotlib, seaborn | 仓库、Notebook、课程、练习 / zh-CN | notebook-specific | 200 |
| [Django 博客教程](https://www.zmrenwu.com/tutorials/hellodjango-blog-tutorial/) / 追梦人物 / zmrenwu | 第三方作者 | django | 网页、教程、项目 / zh-CN | Django 2.2 second-edition tutorial; historical APIs | 200 |
| [Flask 入门教程](https://tutorial.helloflask.com/) / 李辉 Grey Li | 第三方作者 | flask | 网页、教程、示例/源码 / zh-CN | tutorial edition; not the complete commercial book | 200 |
| [HelloFlask 示例项目](https://github.com/greyli/helloflask) / 李辉 Grey Li / HelloFlask | 第三方作者 | flask, sqlalchemy, pytest | 仓库、示例/源码、项目 / zh-CN | per-project dependency file; book editions differ | 200 |
| [FastAPI 中文教程](https://fastapi.tiangolo.com/zh/tutorial/) / FastAPI 翻译贡献者 | 项目官方 | fastapi, pydantic | 网页、教程 / zh-CN | rolling; translated pages may lag original | 200 |
| [Django 5.2 中文文档](https://docs.djangoproject.com/zh-hans/5.2/intro/) / Django 文档翻译团队 | 项目官方 | django | 网页、教程、参考 / zh-CN | Django 5.2 | 200 |
| [APIFlask 中文文档](https://zh.apiflask.com/) / APIFlask / 李辉与贡献者 | 项目官方 | apiflask, flask | 网页、参考 / zh-CN | rolling; translated pages may lag original | 200 |
| [TensorFlow 中文教程](https://www.tensorflow.org/tutorials?hl=zh-cn) / TensorFlow 文档团队与翻译贡献者 | 项目官方 | tensorflow | 网页、教程、Notebook / zh-CN | tutorial-specific; some linked pages are English | 200 |
| [Hugging Face 中文 NLP 课程](https://huggingface.co/learn/llm-course/zh-CN/chapter1/1) / Hugging Face 课程团队与中文贡献者 | 项目官方 | transformers, datasets | 网页、课程、Notebook / zh-CN | chapter-specific; original and translated editions may differ | 200 |
| [Python Cookbook 中文版](https://python3-cookbook.readthedocs.io/zh_CN/latest/) / David Beazley、Brian K. Jones；熊能等译 | 社区译文 | 语言/通用 | 网页、书籍 / zh-CN | Python Cookbook 3rd edition / Python 3.3 era | 200 |
| [Playwright for Python](https://playwright.dev/python/docs/intro) / Microsoft / Playwright contributors | 项目官方 | playwright | 网页、教程 / en | browser and Python package version specific | 200 |
| [XGBoost Python Tutorials](https://xgboost.readthedocs.io/en/stable/python/) / XGBoost contributors | 项目官方 | xgboost | 网页、参考 / en | stable alias; CPU/GPU support differs | 200 |
| [JAX Documentation](https://docs.jax.dev/en/latest/) / JAX contributors | 项目官方 | jax | 网页、参考 / en | latest alias; accelerator and runtime version specific | 200 |
| [statsmodels User Guide](https://www.statsmodels.org/stable/user-guide.html) / statsmodels developers | 项目官方 | statsmodels | 网页、参考 / en | stable alias | 200 |
| [openpyxl Tutorial](https://openpyxl.readthedocs.io/en/stable/tutorial.html) / openpyxl developers | 项目官方 | openpyxl | 网页、教程 / en | stable alias | 200 |
| [APScheduler User Guide](https://apscheduler.readthedocs.io/en/3.x/userguide.html) / APScheduler maintainers | 项目官方 | apscheduler | 网页、参考 / en | APScheduler 3.x; not v4 redesign | 200 |
| [Selenium WebDriver Documentation](https://www.selenium.dev/documentation/webdriver/) / Selenium / Software Freedom Conservancy | 项目官方 | selenium | 网页、参考 / en | Selenium 4; select supported language binding | 200 |

## Java

| 资料与发布者 | 来源 | 生态 | 载体 / 正文语言 | 适用版本 | HTTP |
| --- | --- | --- | --- | --- | --- |
| [Java General Tutorials](https://dev.java/learn/) / Dev.java / Oracle Java community | 项目官方 | 语言/通用 | 网页、教程 / en | rolling | 200 |
| [JDK 25 Documentation](https://docs.oracle.com/en/java/javase/25/) / Oracle | 项目官方 | 语言/通用 | 网页、参考 / en | Java 25 | 200 |
| [Java SE 25 API Specification](https://docs.oracle.com/en/java/javase/25/docs/api/) / Oracle | 项目官方 | 语言/通用 | 网页、参考 / en | Java 25 | 200 |
| [Java Language Specification, Java SE 25](https://docs.oracle.com/javase/specs/jls/se25/html/index.html) / Oracle | 项目官方 | 语言/通用 | 网页、规范 / en | Java 25 | 200 |
| [Java SE 21 API Specification](https://docs.oracle.com/en/java/javase/21/docs/api/) / Oracle | 项目官方 | 语言/通用 | 网页、参考 / en | Java 21 | 200 |
| [Maven Getting Started Guide](https://maven.apache.org/guides/getting-started/index.html) / Apache Maven | 项目官方 | maven | 网页、教程 / en | rolling | 200 |
| [Maven Dependency Mechanism](https://maven.apache.org/guides/introduction/introduction-to-dependency-mechanism.html) / Apache Maven | 项目官方 | maven | 网页、参考 / en | rolling | 200 |
| [Building Java and JVM Projects with Gradle](https://docs.gradle.org/current/userguide/building_java_projects.html) / Gradle | 项目官方 | gradle | 网页、教程、参考 / en | current alias | 200 |
| [JUnit User Guide](https://docs.junit.org/current/user-guide/) / JUnit team | 项目官方 | junit | 网页、参考、示例/源码 / en | current alias; not automatically JUnit 5 | 200 |
| [JUnit 5 User Guide](https://docs.junit.org/5.12.2/user-guide/) / JUnit team | 项目官方 | junit | 网页、参考 / en | JUnit 5.12.2 | 200 |
| [Spring Framework Reference](https://docs.spring.io/spring-framework/reference/index.html) / Spring project | 项目官方 | spring | 网页、参考 / en | rolling | 200 |
| [Spring Boot Reference](https://docs.spring.io/spring-boot/index.html) / Spring project | 项目官方 | spring-boot | 网页、参考 / en | rolling | 200 |
| [Spring Getting Started Guides](https://spring.io/guides) / Spring project | 项目官方 | spring, spring-boot | 网页、教程、示例/源码 / en | guide-specific | 200 |
| [Building a RESTful Web Service](https://spring.io/guides/gs/rest-service) / Spring project | 项目官方 | spring-boot | 网页、教程、示例/源码 / en | guide-specific | 200 |
| [Accessing Relational Data Using JDBC with Spring](https://spring.io/guides/gs/relational-data-access) / Spring project | 项目官方 | spring | 网页、教程、示例/源码 / en | guide-specific | 200 |
| [MyBatis 3 Chinese Documentation](https://mybatis.org/mybatis-3/zh_CN/index.html) / MyBatis project | 项目官方 | mybatis | 网页、参考 / zh-CN | MyBatis 3 | 200 |
| [Spring Petclinic Sample Application](https://github.com/spring-projects/spring-petclinic) / Spring project | 项目官方 | spring-boot | 仓库、示例/源码、项目 / en | commit-specific | 200 |
| [University of Helsinki Java Programming](https://java-programming.mooc.fi/) / University of Helsinki | 第三方作者 | 语言/通用 | 网页、课程、练习 / en | legacy course | 200 |
| [Get Started with Java](https://www.baeldung.com/get-started-with-java-series) / Baeldung | 第三方作者 | 语言/通用 | 网页、教程 / en | article-specific | 403 |
| [Spring Boot Tutorials](https://www.baeldung.com/spring-boot) / Baeldung | 第三方作者 | spring-boot | 网页、教程 / en | article-specific | 403 |
| [JavaGuide Java Fundamentals](https://javaguide.cn/java/basis/) / JavaGuide / Snailclimb | 第三方作者 | 语言/通用 | 网页、教程 / zh-CN | article-specific | 200 |
| [Java Tutorial by Liao Xuefeng](https://liaoxuefeng.com/books/java/index.html) / Liao Xuefeng | 第三方作者 | 语言/通用 | 网页、书籍、教程 / zh-CN | publisher advertises Java 22; inspect individual chapters | 200 |
| [Think Java, Second Edition](https://greenteapress.com/wp/think-java-2e/) / Allen B. Downey and Chris Mayfield | 第三方作者 | 语言/通用 | 网页、书籍、PDF、示例/源码 / en | second edition; foundational examples | 200 |
| [Exercism Java Track](https://exercism.org/tracks/java) / Exercism community | 第三方作者 | 语言/通用 | 网页、练习、交互 / en | track-specific | 200 |
| [MySQL Connector/J Developer Guide](https://dev.mysql.com/doc/connector-j/en/) / Oracle MySQL | 项目官方 | jdbc, mysql | 网页、参考 / en | connector and server version specific | 200 |
| [Spring Boot 3.5 Reference](https://docs.spring.io/spring-boot/3.5/index.html) / Spring project | 项目官方 | spring-boot | 网页、参考 / en | Spring Boot 3.5 family | 200 |
| [Spring Security Reference](https://docs.spring.io/spring-security/reference/index.html) / Spring project | 项目官方 | spring-security, spring | 网页、参考 / en | rolling; resolve library major and runtime compatibility before use | 200 |
| [Spring Data JPA Reference](https://docs.spring.io/spring-data/jpa/reference/index.html) / Spring project | 项目官方 | spring-data-jpa, spring, hibernate | 网页、参考 / en | rolling; resolve library major and runtime compatibility before use | 200 |
| [Spring Data Redis Reference](https://docs.spring.io/spring-data/redis/reference/index.html) / Spring project | 项目官方 | spring-data-redis, spring, redis | 网页、参考 / en | rolling; resolve library major and runtime compatibility before use | 200 |
| [Spring Data MongoDB Reference](https://docs.spring.io/spring-data/mongodb/reference/index.html) / Spring project | 项目官方 | spring-data-mongodb, spring, mongodb | 网页、参考 / en | rolling; resolve library major and runtime compatibility before use | 200 |
| [Spring Cloud Projects and Release Trains](https://spring.io/projects/spring-cloud) / Spring project | 项目官方 | spring-cloud, spring | 网页、参考 / en | release-train-specific; resolve matching Spring Boot family | 200 |
| [Spring Cloud Gateway Reference](https://docs.spring.io/spring-cloud-gateway/reference/index.html) / Spring project | 项目官方 | spring-cloud-gateway, spring-cloud | 网页、参考 / en | rolling; resolve library major and runtime compatibility before use | 200 |
| [Spring Cloud OpenFeign Reference](https://docs.spring.io/spring-cloud-openfeign/reference/index.html) / Spring project | 项目官方 | spring-cloud-openfeign, spring-cloud | 网页、参考 / en | version-specific; feature-complete project; compare Spring HTTP Service Clients | 200 |
| [Spring Batch Reference](https://docs.spring.io/spring-batch/reference/index.html) / Spring project | 项目官方 | spring-batch, spring | 网页、参考 / en | rolling; resolve library major and runtime compatibility before use | 200 |
| [Spring for Apache Kafka Reference](https://docs.spring.io/spring-kafka/reference/index.html) / Spring project | 项目官方 | spring-kafka, kafka, spring | 网页、参考 / en | rolling; resolve library major and runtime compatibility before use | 200 |
| [Spring AMQP Reference](https://docs.spring.io/spring-amqp/reference/index.html) / Spring project | 项目官方 | spring-amqp, rabbitmq, spring | 网页、参考 / en | rolling; resolve library major and runtime compatibility before use | 200 |
| [Spring AI Reference](https://docs.spring.io/spring-ai/reference/index.html) / Spring project | 项目官方 | spring-ai, spring | 网页、参考 / en | rolling; resolve library major and runtime compatibility before use | 200 |
| [Reactor Reference Guide](https://projectreactor.io/docs/core/release/reference/) / Project Reactor | 项目官方 | reactor | 网页、参考 / en | release alias; match Spring WebFlux dependency train | 200 |
| [Hibernate ORM Documentation](https://hibernate.org/orm/documentation/) / Hibernate project | 项目官方 | hibernate, jpa | 网页、参考 / en | version selector; distinguish javax and jakarta generations | 200 |
| [Jakarta EE Specifications](https://jakarta.ee/specifications/) / Eclipse Foundation | 项目官方 | jakartaee, jpa, servlet | 网页、规范、参考 / en | specification-release-specific | 200 |
| [Quarkus Guides](https://quarkus.io/guides/) / Quarkus project | 项目官方 | quarkus | 网页、教程、参考 / en | guide-specific | 200 |
| [Micronaut User Guide](https://docs.micronaut.io/latest/guide/) / Micronaut Foundation | 项目官方 | micronaut | 网页、参考 / en | latest alias | 200 |
| [Eclipse Vert.x Documentation](https://vertx.io/docs/) / Eclipse Vert.x | 项目官方 | vertx | 网页、参考 / en | rolling; resolve library major and runtime compatibility before use | 200 |
| [Netty User Guide](https://netty.io/wiki/user-guide-for-4.x.html) / Netty project | 项目官方 | netty | 网页、参考 / en | Netty 4.x | 200 |
| [Jackson Documentation](https://github.com/FasterXML/jackson-docs) / FasterXML | 项目官方 | jackson | 仓库、Markdown、参考 / en | major-specific; Jackson 2 and 3 packages differ | 200 |
| [Gson User Guide](https://google.github.io/gson/UserGuide.html) / Gson maintainers | 项目官方 | gson | 网页、参考 / en | rolling; resolve library major and runtime compatibility before use | 200 |
| [SLF4J Manual](https://www.slf4j.org/manual.html) / QOS.ch / SLF4J | 项目官方 | slf4j | 网页、参考 / en | rolling; resolve library major and runtime compatibility before use | 200 |
| [Logback Manual](https://logback.qos.ch/manual/) / QOS.ch / Logback | 项目官方 | logback | 网页、参考 / en | rolling; resolve library major and runtime compatibility before use | 200 |
| [Apache Log4j 2 Manual](https://logging.apache.org/log4j/2.x/manual/index.html) / Apache Log4j | 项目官方 | log4j | 网页、参考 / en | Log4j 2.x; not Log4j 1 or 3 | 200 |
| [Guava User Guide](https://github.com/google/guava/wiki) / Google / Guava maintainers | 项目官方 | guava | 网页、参考 / en | selected release; JRE and Android flavors differ | 200 |
| [Apache Commons Components](https://commons.apache.org/) / Apache Software Foundation | 项目官方 | apache-commons | 网页、参考 / en | component-specific; choose maintained component docs | 200 |
| [Project Lombok Features](https://projectlombok.org/features/) / Project Lombok | 项目官方 | lombok | 网页、参考 / en | rolling; resolve library major and runtime compatibility before use | 200 |
| [MapStruct Documentation](https://mapstruct.org/documentation/) / MapStruct project | 项目官方 | mapstruct | 网页、参考 / en | version-selector; resolve selected release | 200 |
| [HikariCP Documentation and Configuration](https://github.com/brettwooldridge/HikariCP) / HikariCP maintainers | 项目官方 | hikaricp, jdbc | 仓库、参考、示例/源码 / en | release-specific; match Java version | 200 |
| [Caffeine User Guide](https://github.com/ben-manes/caffeine/wiki) / Ben Manes and contributors | 项目官方 | caffeine | 网页、参考 / en | release-specific; check Java compatibility | 200 |
| [Flyway Documentation](https://documentation.red-gate.com/fd) / Redgate / Flyway | 项目官方 | flyway | 网页、参考 / en | version and edition specific | 200 |
| [Liquibase Documentation](https://docs.liquibase.com/) / Liquibase | 项目官方 | liquibase | 网页、参考 / en | version and edition specific | 200 |
| [jOOQ User Manual](https://www.jooq.org/doc/latest/manual/) / Data Geekery / jOOQ | 项目官方 | jooq | 网页、参考 / en | latest alias; database and edition specific | 200 |
| [Mockito Documentation](https://site.mockito.org/) / Mockito contributors | 项目官方 | mockito | 网页、参考 / en | selected major; use linked versioned Javadoc | 200 |
| [AssertJ Documentation](https://assertj.github.io/doc/) / AssertJ contributors | 项目官方 | assertj | 网页、参考 / en | rolling; resolve library major and runtime compatibility before use | 200 |
| [Testcontainers for Java](https://java.testcontainers.org/) / Testcontainers contributors | 项目官方 | testcontainers, junit | 网页、参考 / en | rolling; resolve library major and runtime compatibility before use | 200 |
| [REST Assured Usage Guide](https://github.com/rest-assured/rest-assured/wiki/Usage) / REST Assured maintainers | 项目官方 | rest-assured | 网页、参考、示例/源码 / en | release-specific | 200 |
| [WireMock Documentation](https://wiremock.org/docs/) / WireMock contributors | 项目官方 | wiremock | 网页、参考 / en | rolling; resolve library major and runtime compatibility before use | 200 |
| [OkHttp Documentation](https://square.github.io/okhttp/) / Square / OkHttp maintainers | 项目官方 | okhttp | 网页、参考 / en | release-specific; Java and Android compatibility differ | 网络错误 |
| [Thymeleaf Tutorials](https://www.thymeleaf.org/documentation.html) / Thymeleaf project | 项目官方 | thymeleaf | 网页、教程、参考 / en | tutorial-version-specific | 200 |
| [Getting Started with JavaFX](https://openjfx.io/openjfx-docs/) / OpenJFX contributors | 项目官方 | javafx | 网页、教程 / en | JavaFX and JDK versions must match | 200 |
| [Android Java API Reference](https://developer.android.com/reference) / Android Open Source Project / Google | 项目官方 | android | 网页、参考 / en | Android API-level-specific; not every guide has Java samples | 200 |
| [Redis Jedis Guide](https://redis.io/docs/latest/develop/clients/jedis/) / Redis | 项目官方 | jedis, redis | 网页、参考 / en | latest alias | 200 |
| [Redis Lettuce Guide](https://redis.io/docs/latest/develop/clients/lettuce/) / Redis | 项目官方 | lettuce, redis | 网页、参考 / en | latest alias | 200 |
| [Micrometer Reference](https://docs.micrometer.io/micrometer/reference/) / Micrometer project | 项目官方 | micrometer | 网页、参考 / en | rolling; resolve library major and runtime compatibility before use | 200 |
| [PostgreSQL JDBC Documentation](https://jdbc.postgresql.org/documentation/) / PostgreSQL JDBC project | 项目官方 | jdbc, postgresql | 网页、参考 / en | driver and server version specific | 200 |
| [gRPC Language Guides](https://grpc.io/docs/) / gRPC contributors | 项目官方 | grpc | 网页、参考 / en | select language and runtime guide; language support differs | 200 |
| [OpenTelemetry Language APIs and SDKs](https://opentelemetry.io/docs/languages/) / OpenTelemetry contributors / CNCF | 项目官方 | opentelemetry | 网页、参考 / en | language and signal stability differ | 200 |
| [Redis Client Libraries](https://redis.io/docs/latest/develop/clients/) / Redis | 项目官方 | redis | 网页、参考 / en | latest alias; distinguish server, client and license versions | 200 |
| [MongoDB Drivers](https://www.mongodb.com/docs/drivers/) / MongoDB | 项目官方 | mongodb | 网页、参考 / en | driver-language and server-version specific | 200 |
| [RabbitMQ Tutorials](https://www.rabbitmq.com/tutorials) / RabbitMQ maintainers | 项目官方 | rabbitmq | 网页、教程、示例/源码 / en | language-specific examples; not all SDKs have every tutorial | 200 |
| [Protocol Buffers Tutorials](https://protobuf.dev/getting-started/) / Protocol Buffers contributors | 项目官方 | protobuf | 网页、教程、示例/源码 / en | language-generator and runtime version specific | 200 |
| [Apache Kafka Documentation](https://kafka.apache.org/documentation/) / Apache Kafka | 项目官方 | kafka | 网页、参考 / en | version-selector; JVM and broker compatibility differ | 200 |
| [Reflectoring Spring Boot Tutorials](https://reflectoring.io/categories/spring-boot/) / Reflectoring authors | 第三方作者 | spring-boot, spring | 网页、教程 / en | article-specific | 200 |
| [Vlad Mihalcea Persistence Tutorials](https://vladmihalcea.com/tutorials/) / Vlad Mihalcea | 第三方作者 | hibernate, jpa, jdbc, jooq, spring | 网页、教程 / en | article and repository-version specific | 200 |
| [Java and Spring Testing Tutorial Projects](https://github.com/rieckpil/blog-tutorials) / Philip Riecks and contributors | 第三方作者 | spring-boot, spring-security, junit, mockito, testcontainers | 仓库、示例/源码、项目 / en | per-project Java and dependency lock | 200 |
| [Jenkov Java Concurrency Tutorials](https://jenkov.com/tutorials/java-concurrency/index.html) / Jakob Jenkov | 第三方作者 | 语言/通用 | 网页、教程 / en | article-specific; includes historical Java APIs | 200 |
| [MyBatis-Plus 指南](https://baomidou.com/introduce/) / 苞米豆 / MyBatis-Plus | 项目官方 | mybatis-plus, mybatis | 网页、指南、参考 / zh-CN | release-specific; Spring Boot starters differ | 200 |
| [Nacos 中文文档](https://nacos.io/docs/latest/overview/) / Nacos 项目 | 项目官方 | nacos | 网页、参考 / zh-CN | latest alias; choose client and server family | 200 |
| [Sentinel 中文指南](https://github.com/alibaba/Sentinel/wiki) / Alibaba / Sentinel 贡献者 | 项目官方 | sentinel | 网页、指南、参考 / zh-CN | wiki revision and adapter-version specific | 200 |
| [Apache Dubbo 中文文档](https://cn.dubbo.apache.org/zh-cn/overview/) / Apache Dubbo | 项目官方 | dubbo | 网页、参考 / zh-CN | version-selector | 200 |
| [Spring Cloud Alibaba 中文文档](https://sca.aliyun.com/docs/) / Spring Cloud Alibaba | 项目官方 | spring-cloud-alibaba, spring-cloud, nacos, sentinel | 网页、参考 / zh-CN | select matching Spring Boot and Spring Cloud train | 200 |
| [Apache Seata 中文文档](https://seata.apache.org/zh-cn/docs/overview/what-is-seata/) / Apache Seata | 项目官方 | seata | 网页、参考 / zh-CN | version-selector | 200 |
| [Apache RocketMQ 中文文档](https://rocketmq.apache.org/zh/docs/) / Apache RocketMQ | 项目官方 | rocketmq | 网页、参考 / zh-CN | version-selector; broker and client versions differ | 200 |
| [Apache ShardingSphere 中文文档](https://shardingsphere.apache.org/document/current/cn/overview/) / Apache ShardingSphere | 项目官方 | shardingsphere | 网页、参考 / zh-CN | current alias; select JDBC or Proxy product | 200 |
| [Hutool 参考文档](https://doc.hutool.cn/) / Hutool / dromara | 项目官方 | hutool | 网页、参考 / zh-CN | major-version-specific | 200 |
| [Druid 数据库连接池文档](https://github.com/alibaba/druid/wiki) / Alibaba / Druid 贡献者 | 项目官方 | druid, jdbc | 网页、指南、参考 / zh-CN | release-specific; not Apache Druid analytics database | 200 |
| [Sa-Token 中文文档](https://sa-token.cc/) / dromara / Sa-Token | 项目官方 | sa-token | 网页、参考 / zh-CN | release and adapter-version specific | 200 |
| [XXL-JOB 官方文档](https://www.xuxueli.com/xxl-job/) / 许雪里 / XXL-JOB | 项目官方 | xxl-job | 网页、参考 / zh-CN | release-specific | 200 |
| [Redisson 中文指南](https://github.com/redisson/redisson/wiki/目录) / Redisson | 项目官方 | redisson, redis | 网页、参考 / zh-CN | edition and version specific; Redisson PRO is separate | 200 |
| [Fastjson2 项目文档](https://github.com/alibaba/fastjson2) / Alibaba / Fastjson2 | 项目官方 | fastjson2 | 仓库、参考、示例/源码 / zh-CN | Fastjson2; not Fastjson 1.x | 200 |
| [JavaGuide Spring 专题](https://javaguide.cn/system-design/framework/spring/) / Guide 哥与 JavaGuide 贡献者 | 第三方作者 | spring, spring-boot, spring-security | 网页、教程、参考 / zh-CN | article-specific | 200 |
| [二哥的 Java 进阶之路](https://javabetter.cn/) / 沉默王二与贡献者 | 第三方作者 | spring, spring-boot, maven, mybatis | 网页、书籍、教程 / zh-CN | chapter-specific | 200 |
| [凤凰架构](https://icyfenix.cn/) / 周志明 | 第三方作者 | spring, spring-boot | 网页、书籍、示例/源码 / zh-CN | chapter-specific; published book and evolving online text | 200 |
| [mall 学习项目](https://github.com/macrozheng/mall) / macrozheng | 第三方作者 | spring-boot, spring-security, mybatis, redis | 仓库、示例/源码、项目 / zh-CN | branch and dependency-file specific | 200 |
| [SpringBoot-Labs 中文实验](https://github.com/yudaocode/SpringBoot-Labs) / 芋道源码 / YunaiV | 第三方作者 | spring-boot, spring-cloud, spring-cloud-alibaba, dubbo | 仓库、示例/源码、教程 / zh-CN | primarily Spring Boot 2.x; many historical Cloud components | 200 |
| [Spring Boot 学习示例](https://github.com/dyc87112/SpringBoot-Learning) / 程序猿 DD / 翟永超 | 第三方作者 | spring-boot, spring | 仓库、示例/源码、教程 / zh-CN | branch-specific; includes Spring Boot 1.x and 2.x | 200 |
| [SpringAll 学习示例](https://github.com/wuyouzhuguli/SpringAll) / MrBird / wuyouzhuguli | 第三方作者 | spring-boot, spring-cloud, spring-security, spring-batch | 仓库、示例/源码、教程 / zh-CN | module-specific; includes historical Spring OAuth/Cloud APIs | 200 |
| [Spring Cloud Config Reference](https://docs.spring.io/spring-cloud-config/reference/index.html) / Spring project | 项目官方 | spring-cloud-config, spring-cloud | 网页、参考 / en | rolling; resolve library major and runtime compatibility before use | 200 |
| [Spring Integration Reference](https://docs.spring.io/spring-integration/reference/index.html) / Spring project | 项目官方 | spring-integration, spring | 网页、参考 / en | rolling; resolve library major and runtime compatibility before use | 200 |
| [Spring for GraphQL Reference](https://docs.spring.io/spring-graphql/reference/index.html) / Spring project | 项目官方 | spring-graphql, graphql, spring | 网页、参考 / en | rolling; resolve library major and runtime compatibility before use | 200 |
| [Resilience4j Documentation](https://resilience4j.readme.io/docs/getting-started) / Resilience4j contributors | 项目官方 | resilience4j | 网页、参考 / en | major-version-specific | 200 |
| [Hibernate Validator Documentation](https://hibernate.org/validator/documentation/) / Hibernate project | 项目官方 | hibernate-validator, jakarta-validation | 网页、参考 / en | javax and jakarta generations differ | 200 |
| [Elasticsearch Java API Client](https://www.elastic.co/docs/reference/elasticsearch/clients/java) / Elastic | 项目官方 | elasticsearch | 网页、参考 / en | client and server major-version specific | 200 |
| [Apache Dubbo Java SDK Documentation](https://dubbo.apache.org/en/overview/mannual/java-sdk/) / Apache Dubbo | 项目官方 | dubbo | 网页、参考 / en | release-specific | 200 |
| [Selenium WebDriver Documentation](https://www.selenium.dev/documentation/webdriver/) / Selenium / Software Freedom Conservancy | 项目官方 | selenium | 网页、参考 / en | Selenium 4; select supported language binding | 200 |

## JavaScript

| 资料与发布者 | 来源 | 生态 | 载体 / 正文语言 | 适用版本 | HTTP |
| --- | --- | --- | --- | --- | --- |
| [MDN JavaScript Guide](https://developer.mozilla.org/en-US/docs/Web/JavaScript/Guide) / MDN contributors | 第三方作者 | 语言/通用 | 网页、教程、参考 / en | rolling; includes new features | 200 |
| [MDN JavaScript Guide in Chinese](https://developer.mozilla.org/zh-CN/docs/Web/JavaScript/Guide) / MDN translation contributors | 社区译文 | 语言/通用 | 网页、教程 / zh-CN | translation; compare original when necessary | 200 |
| [ECMAScript Language Specification](https://tc39.es/ecma262/) / Ecma TC39 | 项目官方 | 语言/通用 | 网页、规范 / en | living specification; not a runtime support guarantee | 200 |
| [Node.js Learn](https://nodejs.org/en/learn/getting-started/introduction-to-nodejs) / Node.js project | 项目官方 | nodejs | 网页、教程 / en | rolling | 200 |
| [Node.js 22 API Documentation](https://nodejs.org/docs/latest-v22.x/api/) / Node.js project | 项目官方 | nodejs | 网页、参考 / en | Node.js 22 family | 200 |
| [npm Documentation](https://docs.npmjs.com/) / npm | 项目官方 | npm | 网页、参考 / en | CLI-version-specific | 200 |
| [React Learn](https://react.dev/learn) / React team | 项目官方 | react | 网页、教程、交互 / en | rolling | 200 |
| [React Learn in Simplified Chinese](https://zh-hans.react.dev/learn) / React documentation translation team | 项目官方 | react | 网页、教程、交互 / zh-CN | localized rolling documentation | 200 |
| [Vue Guide](https://vuejs.org/guide/introduction.html) / Vue team | 项目官方 | vue | 网页、教程 / en | Vue 3; check page | 200 |
| [Vue Guide in Chinese](https://cn.vuejs.org/guide/introduction.html) / Vue team | 项目官方 | vue | 网页、教程 / zh-CN | Vue 3; check page | 200 |
| [Express Getting Started](https://expressjs.com/en/starter/installing.html) / Express project | 项目官方 | express | 网页、教程 / en | page-specific; Express 4 and 5 differ | 200 |
| [Vitest Getting Started](https://vitest.dev/guide/) / Vitest team | 项目官方 | vitest | 网页、教程、参考 / en | rolling | 200 |
| [The Modern JavaScript Tutorial](https://javascript.info/) / Ilya Kantor and contributors | 第三方作者 | 语言/通用 | 网页、书籍、练习 / en | rolling | 200 |
| [The Modern JavaScript Tutorial in Chinese](https://zh.javascript.info/) / javascript.info Chinese contributors | 社区译文 | 语言/通用 | 网页、书籍、练习 / zh-CN | translation; verify synchronization | 200 |
| [Eloquent JavaScript, Fourth Edition](https://eloquentjavascript.net/) / Marijn Haverbeke | 第三方作者 | 语言/通用 | 网页、书籍、练习、示例/源码 / en | fourth edition, 2024 | 200 |
| [You Don't Know JS Yet, Second Edition](https://github.com/getify/You-Dont-Know-JS) / Kyle Simpson | 第三方作者 | 语言/通用 | 仓库、书籍、Markdown / en | second edition; some volumes remain drafts | 200 |
| [Full Stack Open](https://fullstackopen.com/en/) / University of Helsinki and contributors | 第三方作者 | react, nodejs, express | 网页、课程、练习、项目 / en | course-part-specific | 200 |
| [The Odin Project Foundations](https://www.theodinproject.com/paths/foundations/courses/foundations) / The Odin Project community | 第三方作者 | 语言/通用 | 网页、课程、项目 / en | rolling | 200 |
| [WAI Tutorials](https://www.w3.org/WAI/tutorials/) / W3C Web Accessibility Initiative | 项目官方 | 语言/通用 | 网页、教程 / en | tutorial-specific | 200 |
| [freeCodeCamp Curriculum](https://www.freecodecamp.org/learn/) / freeCodeCamp | 第三方作者 | 语言/通用 | 网页、课程、交互、项目 / en | certification edition | 200 |
| [The Odin Project Curriculum Sources](https://github.com/TheOdinProject/curriculum) / The Odin Project community | 第三方作者 | 语言/通用 | 仓库、Markdown、课程、项目 / en | commit-specific | 200 |
| [Next.js Documentation](https://nextjs.org/docs) / Vercel / Next.js contributors | 项目官方 | nextjs, react | 网页、参考 / en | rolling; distinguish App Router and Pages Router | 200 |
| [Angular Tutorials](https://angular.dev/tutorials) / Angular team | 项目官方 | angular | 网页、教程、交互 / en | rolling; not AngularJS | 200 |
| [Svelte Tutorial](https://svelte.dev/tutorial/svelte/welcome-to-svelte) / Svelte contributors | 项目官方 | svelte | 网页、教程、交互 / en | current tutorial; distinguish Svelte 4 and 5 | 200 |
| [SvelteKit Documentation](https://svelte.dev/docs/kit/introduction) / Svelte contributors | 项目官方 | svelte, sveltekit | 网页、参考 / en | rolling; resolve library major and runtime compatibility before use | 200 |
| [Nuxt Documentation](https://nuxt.com/docs) / Nuxt contributors | 项目官方 | nuxt, vue | 网页、参考 / en | version-selector; do not mix Nuxt 2/3/4 examples | 200 |
| [Astro Documentation](https://docs.astro.build/en/getting-started/) / Astro contributors | 项目官方 | astro | 网页、教程 / en | rolling | 200 |
| [NestJS Documentation](https://docs.nestjs.com/) / NestJS contributors | 项目官方 | nestjs | 网页、参考 / en | rolling; resolve library major and runtime compatibility before use | 200 |
| [Fastify Getting Started](https://fastify.dev/docs/latest/Guides/Getting-Started/) / Fastify / OpenJS Foundation | 项目官方 | fastify | 网页、教程 / en | latest alias | 200 |
| [Hono Documentation](https://hono.dev/docs/) / Hono contributors | 项目官方 | hono | 网页、参考 / en | rolling; resolve library major and runtime compatibility before use | 200 |
| [Koa Documentation](https://koajs.com/) / Koa contributors | 项目官方 | koa | 网页、参考 / en | rolling; resolve library major and runtime compatibility before use | 200 |
| [React Router Documentation](https://reactrouter.com/start/declarative/installation) / React Router contributors | 项目官方 | react-router, react | 网页、参考 / en | mode and major-version specific; distinguish Remix-era docs | 200 |
| [Vue Router Guide](https://router.vuejs.org/guide/) / Vue Router contributors | 项目官方 | vue-router, vue | 网页、参考 / en | Vue Router 4 / Vue 3 | 200 |
| [Redux Essentials Tutorial](https://redux.js.org/tutorials/essentials/part-1-overview-concepts) / Redux maintainers | 项目官方 | redux, redux-toolkit, react | 网页、教程 / en | rolling; modern Redux Toolkit approach | 200 |
| [Zustand Introduction](https://zustand.docs.pmnd.rs/learn/getting-started/introduction) / Poimandres / Zustand contributors | 项目官方 | zustand, react | 网页、参考 / en | rolling; resolve library major and runtime compatibility before use | 200 |
| [Pinia Introduction](https://pinia.vuejs.org/introduction.html) / Pinia / Vue contributors | 项目官方 | pinia, vue | 网页、参考 / en | rolling; resolve library major and runtime compatibility before use | 200 |
| [TanStack Query Documentation](https://tanstack.com/query/latest/docs/framework/react/overview) / TanStack contributors | 项目官方 | tanstack-query, react-query | 网页、参考 / en | latest alias; select UI binding before use | 200 |
| [TanStack Router Documentation](https://tanstack.com/router/latest/docs/framework/react/overview) / TanStack contributors | 项目官方 | tanstack-router | 网页、参考 / en | latest alias; select UI binding before use | 200 |
| [Axios Documentation](https://axios-http.com/docs/intro) / Axios maintainers | 项目官方 | axios | 网页、参考 / en | rolling; resolve library major and runtime compatibility before use | 200 |
| [Zod Documentation](https://zod.dev/) / Zod maintainers | 项目官方 | zod | 网页、参考 / en | major-version-specific | 200 |
| [React Hook Form Documentation](https://react-hook-form.com/get-started) / React Hook Form contributors | 项目官方 | react-hook-form, react | 网页、教程 / en | rolling | 200 |
| [tRPC Documentation](https://trpc.io/docs/) / tRPC contributors | 项目官方 | trpc | 网页、参考 / en | version-specific; TypeScript-first client and server | 200 |
| [Prisma ORM Documentation](https://www.prisma.io/docs/orm) / Prisma | 项目官方 | prisma | 网页、参考 / en | major-version and connector specific; local ORM distinct from paid platform | 200 |
| [Drizzle ORM Documentation](https://orm.drizzle.team/docs/overview) / Drizzle team | 项目官方 | drizzle | 网页、参考 / en | version and dialect specific | 200 |
| [TypeORM Documentation](https://typeorm.io/docs/) / TypeORM contributors | 项目官方 | typeorm | 网页、参考 / en | version and driver specific | 200 |
| [Sequelize Documentation](https://sequelize.org/docs/v6/) / Sequelize contributors | 项目官方 | sequelize | 网页、参考 / en | Sequelize 6; not v7 prerelease documentation | 200 |
| [Knex.js Guide](https://knexjs.org/guide/) / Knex contributors | 项目官方 | knex | 网页、参考 / en | version and dialect specific | 200 |
| [node-postgres Documentation](https://node-postgres.com/) / Brian Carlson and contributors | 项目官方 | node-postgres, postgresql | 网页、参考 / en | rolling; resolve library major and runtime compatibility before use | 200 |
| [MySQL2 Documentation](https://sidorares.github.io/node-mysql2/docs) / MySQL2 contributors | 项目官方 | mysql2, mysql | 网页、参考 / en | rolling; resolve library major and runtime compatibility before use | 200 |
| [Mongoose Guide](https://mongoosejs.com/docs/guide.html) / Mongoose contributors | 项目官方 | mongoose, mongodb | 网页、参考 / en | major-version-specific | 200 |
| [Socket.IO Documentation](https://socket.io/docs/v4/) / Socket.IO contributors | 项目官方 | socketio | 网页、参考 / en | Socket.IO 4; not raw WebSocket protocol | 200 |
| [RxJS Guide](https://rxjs.dev/guide/overview) / RxJS contributors | 项目官方 | rxjs | 网页、参考 / en | rolling; resolve library major and runtime compatibility before use | 200 |
| [Lodash Documentation](https://lodash.com/docs/) / Lodash contributors | 项目官方 | lodash | 网页、参考 / en | rolling; resolve library major and runtime compatibility before use | 200 |
| [date-fns Documentation](https://date-fns.org/docs/Getting-Started) / date-fns contributors | 项目官方 | date-fns | 网页、参考 / en | major-version-specific | 200 |
| [Vite Guide](https://vite.dev/guide/) / Vite contributors | 项目官方 | vite | 网页、参考 / en | rolling; major-version-specific | 200 |
| [webpack Guides](https://webpack.js.org/guides/) / webpack contributors | 项目官方 | webpack | 网页、教程 / en | guide-version-specific | 200 |
| [Rollup Tutorial](https://rollupjs.org/tutorial/) / Rollup contributors | 项目官方 | rollup | 网页、教程 / en | rolling | 200 |
| [esbuild Documentation](https://esbuild.github.io/) / Evan Wallace | 项目官方 | esbuild | 网页、参考 / en | selected release | 200 |
| [Babel Documentation](https://babeljs.io/docs/) / Babel contributors | 项目官方 | babel | 网页、参考 / en | major-version-specific | 200 |
| [ESLint Documentation](https://eslint.org/docs/latest/) / ESLint / OpenJS Foundation | 项目官方 | eslint | 网页、参考 / en | latest alias; distinguish flat and legacy config | 200 |
| [Prettier Documentation](https://prettier.io/docs/) / Prettier contributors | 项目官方 | prettier | 网页、参考 / en | rolling; resolve library major and runtime compatibility before use | 200 |
| [pnpm Documentation](https://pnpm.io/) / pnpm contributors | 项目官方 | pnpm | 网页、参考 / en | major-version-specific | 200 |
| [Yarn Documentation](https://yarnpkg.com/getting-started) / Yarn contributors | 项目官方 | yarn | 网页、参考 / en | Yarn modern; not Classic 1.x | 200 |
| [Jest Getting Started](https://jestjs.io/docs/getting-started) / Jest contributors | 项目官方 | jest | 网页、教程 / en | version-selector | 200 |
| [Playwright Documentation](https://playwright.dev/docs/intro) / Microsoft / Playwright contributors | 项目官方 | playwright | 网页、教程 / en | rolling | 200 |
| [Cypress Documentation](https://docs.cypress.io/app/get-started/why-cypress) / Cypress | 项目官方 | cypress | 网页、参考 / en | rolling; resolve library major and runtime compatibility before use | 200 |
| [Testing Library Documentation](https://testing-library.com/docs/) / Testing Library contributors | 项目官方 | testing-library | 网页、参考 / en | rolling; resolve library major and runtime compatibility before use | 200 |
| [Storybook Documentation](https://storybook.js.org/docs) / Storybook contributors | 项目官方 | storybook | 网页、参考 / en | version and UI-framework specific | 200 |
| [React Native Documentation](https://reactnative.dev/docs/getting-started) / Meta / React Native contributors | 项目官方 | react-native, react | 网页、教程、交互 / en | version-selector | 200 |
| [Expo Tutorial](https://docs.expo.dev/tutorial/introduction/) / Expo | 项目官方 | expo, react-native | 网页、教程 / en | SDK-specific; paid services distinct from local framework | 200 |
| [Electron Tutorial](https://www.electronjs.org/docs/latest/tutorial/tutorial-prerequisites) / Electron / OpenJS Foundation | 项目官方 | electron | 网页、教程 / en | latest alias | 200 |
| [D3 Documentation](https://d3js.org/getting-started) / D3 maintainers | 项目官方 | d3 | 网页、参考 / en | major-version-specific | 200 |
| [Apache ECharts Handbook](https://echarts.apache.org/handbook/en/get-started/) / Apache ECharts | 项目官方 | echarts | 网页、教程 / en | major-version-specific | 200 |
| [Chart.js Documentation](https://www.chartjs.org/docs/latest/) / Chart.js contributors | 项目官方 | chartjs | 网页、参考 / en | latest alias | 200 |
| [Three.js Manual](https://threejs.org/manual/) / Three.js contributors | 项目官方 | threejs | 网页、参考 / en | release-specific | 200 |
| [jQuery API Documentation](https://api.jquery.com/) / jQuery / OpenJS Foundation | 项目官方 | jquery | 网页、参考 / en | API-version markers; established-project reference | 200 |
| [Tailwind CSS Documentation](https://tailwindcss.com/docs/installation/using-vite) / Tailwind Labs | 项目官方 | tailwindcss | 网页、参考 / en | current major; keep v3 and v4 instructions separate | 200 |
| [Bootstrap 5.3 Documentation](https://getbootstrap.com/docs/5.3/getting-started/introduction/) / Bootstrap team | 项目官方 | bootstrap | 网页、参考 / en | Bootstrap 5.3; not Bootstrap 6 preview | 200 |
| [Sass Documentation](https://sass-lang.com/documentation/) / Sass contributors | 项目官方 | sass | 网页、参考 / en | rolling; resolve library major and runtime compatibility before use | 200 |
| [Less Documentation](https://lesscss.org/) / Less contributors | 项目官方 | less | 网页、参考 / en | rolling; resolve library major and runtime compatibility before use | 200 |
| [PostCSS Documentation](https://postcss.org/docs/) / PostCSS contributors | 项目官方 | postcss | 网页、参考 / en | rolling; resolve library major and runtime compatibility before use | 200 |
| [Stylelint User Guide](https://stylelint.io/user-guide/get-started) / Stylelint contributors | 项目官方 | stylelint | 网页、参考 / en | rolling; resolve library major and runtime compatibility before use | 200 |
| [Bulma Documentation](https://bulma.io/documentation/) / Jeremy Thomas / Bulma contributors | 项目官方 | bulma | 网页、参考 / en | rolling; resolve library major and runtime compatibility before use | 200 |
| [htmx Documentation](https://htmx.org/docs/) / htmx contributors | 项目官方 | htmx | 网页、参考 / en | version-specific | 200 |
| [Alpine.js Start Here](https://alpinejs.dev/start-here) / Alpine.js contributors | 项目官方 | alpinejs | 网页、教程 / en | rolling | 200 |
| [Material UI Documentation](https://mui.com/material-ui/getting-started/) / MUI | 项目官方 | mui, react | 网页、参考 / en | rolling; resolve library major and runtime compatibility before use | 200 |
| [Ant Design Documentation](https://ant.design/docs/react/introduce) / Ant Design contributors | 项目官方 | ant-design, react | 网页、参考 / en | rolling; resolve library major and runtime compatibility before use | 200 |
| [Element Plus Guide](https://element-plus.org/en-US/guide/design.html) / Element Plus contributors | 项目官方 | element-plus, vue | 网页、参考 / en | Vue 3 / Element Plus; not Vue 2 Element UI | 200 |
| [Vuetify Documentation](https://vuetifyjs.com/en/introduction/why-vuetify/) / Vuetify contributors | 项目官方 | vuetify, vue | 网页、参考 / en | version-specific | 200 |
| [Radix Primitives Documentation](https://www.radix-ui.com/primitives/docs/overview/introduction) / Radix contributors | 项目官方 | radix, react | 网页、参考 / en | rolling; resolve library major and runtime compatibility before use | 200 |
| [shadcn/ui Documentation](https://ui.shadcn.com/docs) / shadcn/ui contributors | 项目官方 | shadcn, react | 网页、参考 / en | source-distribution and dependency versions vary | 200 |
| [VueUse Guide](https://vueuse.org/guide/) / VueUse contributors | 项目官方 | vueuse, vue | 网页、参考 / en | rolling; resolve library major and runtime compatibility before use | 200 |
| [Solid Documentation](https://docs.solidjs.com/) / Solid contributors | 项目官方 | solidjs | 网页、参考 / en | rolling; resolve library major and runtime compatibility before use | 200 |
| [Preact Guide](https://preactjs.com/guide/v10/getting-started) / Preact contributors | 项目官方 | preact | 网页、参考 / en | Preact 10 | 200 |
| [Lit Documentation](https://lit.dev/docs/) / Lit contributors | 项目官方 | lit | 网页、参考 / en | rolling; resolve library major and runtime compatibility before use | 200 |
| [TanStack Start Documentation](https://tanstack.com/start/latest/docs/framework/react/overview) / TanStack contributors | 项目官方 | tanstack-start | 网页、参考 / en | latest alias; select UI binding and runtime | 200 |
| [NgRx Documentation](https://ngrx.io/docs) / NgRx contributors | 项目官方 | ngrx, angular | 网页、参考 / en | rolling; resolve library major and runtime compatibility before use | 200 |
| [MobX Documentation](https://mobx.js.org/README.html) / MobX contributors | 项目官方 | mobx | 网页、参考 / en | rolling; resolve library major and runtime compatibility before use | 200 |
| [Apollo Client Documentation](https://www.apollographql.com/docs/react/) / Apollo GraphQL | 项目官方 | apollo, graphql, react | 网页、参考 / en | rolling; resolve library major and runtime compatibility before use | 200 |
| [Bun Documentation](https://bun.com/docs) / Bun contributors | 项目官方 | bun | 网页、参考 / en | rolling; not the Node.js execution recipe | 200 |
| [Deno Documentation](https://docs.deno.com/runtime/) / Deno contributors | 项目官方 | deno | 网页、参考 / en | rolling; not the Node.js execution recipe | 200 |
| [Biome Documentation](https://biomejs.dev/guides/getting-started/) / Biome contributors | 项目官方 | biome | 网页、教程 / en | rolling | 200 |
| [gRPC Language Guides](https://grpc.io/docs/) / gRPC contributors | 项目官方 | grpc | 网页、参考 / en | select language and runtime guide; language support differs | 200 |
| [OpenTelemetry Language APIs and SDKs](https://opentelemetry.io/docs/languages/) / OpenTelemetry contributors / CNCF | 项目官方 | opentelemetry | 网页、参考 / en | language and signal stability differ | 200 |
| [Redis Client Libraries](https://redis.io/docs/latest/develop/clients/) / Redis | 项目官方 | redis | 网页、参考 / en | latest alias; distinguish server, client and license versions | 200 |
| [MongoDB Drivers](https://www.mongodb.com/docs/drivers/) / MongoDB | 项目官方 | mongodb | 网页、参考 / en | driver-language and server-version specific | 200 |
| [RabbitMQ Tutorials](https://www.rabbitmq.com/tutorials) / RabbitMQ maintainers | 项目官方 | rabbitmq | 网页、教程、示例/源码 / en | language-specific examples; not all SDKs have every tutorial | 200 |
| [Patterns.dev](https://www.patterns.dev/) / Lydia Hallie, Addy Osmani and contributors | 第三方作者 | react, vue, nextjs | 网页、书籍、示例/源码 / en | article-specific | 200 |
| [Full Stack Open Advanced State Management](https://fullstackopen.com/en/part6) / University of Helsinki and contributors | 第三方作者 | redux, redux-toolkit, tanstack-query, react | 网页、课程、练习 / en | course-part-specific | 200 |
| [Full Stack Open Testing React Apps](https://fullstackopen.com/en/part5) / University of Helsinki and contributors | 第三方作者 | react, playwright, testing-library | 网页、课程、练习 / en | course-part-specific | 200 |
| [Vite 官方中文指南](https://cn.vite.dev/guide/) / Vite 中文贡献者 | 项目官方 | vite | 网页、参考 / zh-CN | version-specific; Chinese and original editions may differ | 200 |
| [Pinia 中文指南](https://pinia.vuejs.org/zh/introduction.html) / Pinia / Vue 中文贡献者 | 项目官方 | pinia, vue | 网页、参考 / zh-CN | translation revision visible on site; may lag original | 200 |
| [Vue Router 中文指南](https://router.vuejs.org/zh/guide/) / Vue Router 中文贡献者 | 项目官方 | vue-router, vue | 网页、参考 / zh-CN | Vue Router 4 / Vue 3 | 200 |
| [Ant Design 中文文档](https://ant.design/docs/react/introduce-cn) / Ant Design 团队与贡献者 | 项目官方 | ant-design, react | 网页、参考 / zh-CN | major-version-specific | 200 |
| [Element Plus 中文指南](https://element-plus.org/zh-CN/guide/design.html) / Element Plus 贡献者 | 项目官方 | element-plus, vue | 网页、参考 / zh-CN | Vue 3 / Element Plus | 200 |
| [Apache ECharts 中文手册](https://echarts.apache.org/handbook/zh/index.html) / Apache ECharts | 项目官方 | echarts | 网页、参考 / zh-CN | distinguish ECharts 5/6 migration docs | 200 |
| [Axios 中文文档](https://axios-http.com/zh/docs/intro) / Axios 中文贡献者 | 项目官方 | axios | 网页、参考 / zh-CN | translation-version-specific | 200 |
| [pnpm 中文文档](https://pnpm.io/zh/) / pnpm 中文贡献者 | 项目官方 | pnpm | 网页、参考 / zh-CN | major-version-specific | 200 |
| [Vitest 中文指南](https://cn.vitest.dev/guide/) / Vitest 中文贡献者 | 项目官方 | vitest | 网页、参考 / zh-CN | version-specific | 200 |
| [Nuxt 中文文档](https://nuxt.com.cn/docs/getting-started/introduction) / Nuxt 中文社区 | 社区译文 | nuxt, vue | 网页、参考 / zh-CN | community translation; resolve matching original major | 网络错误 |
| [VueUse 中文指南](https://vueuse.org/zh/guide/) / VueUse 中文贡献者 | 项目官方 | vueuse, vue | 网页、参考 / zh-CN | translation coverage varies | 200 |
| [uni-app 文档](https://uniapp.dcloud.net.cn/) / DCloud / uni-app | 项目官方 | uniapp, vue | 网页、参考 / zh-CN | target and toolchain specific; cloud products are separate | 200 |
| [Taro 中文文档](https://docs.taro.zone/docs/) / Taro 贡献者 | 项目官方 | taro, react | 网页、参考 / zh-CN | target and major-version specific | 网络错误 |
| [Umi 中文文档](https://umijs.org/docs/introduce/introduce) / Umi 贡献者 | 项目官方 | umi, react | 网页、参考 / zh-CN | major-version-specific | 200 |
| [Naive UI 中文文档](https://github.com/tusen-ai/naive-ui/tree/main/demo/pages/docs) / Naive UI 贡献者 | 项目官方 | naiveui, vue | 仓库、Markdown、参考 / zh-CN | Vue 3; entry needs client-side rendering | 200 |
| [Vant 中文文档](https://vant-ui.github.io/vant/#/zh-CN/) / Vant 贡献者 | 项目官方 | vant, vue | 网页、参考 / zh-CN | hash-routed docs; resolve actual selected page when acquiring | 200 |
| [网道 JavaScript 教程](https://wangdoc.com/javascript/) / 阮一峰 / 网道 | 第三方作者 | 语言/通用 | 网页、书籍、教程 / zh-CN | chapter-specific | 200 |
| [ECMAScript 6 入门](https://es6.ruanyifeng.com/) / 阮一峰 | 第三方作者 | 语言/通用 | 网页、书籍、教程 / zh-CN | rolling; proposals and standardized features distinguished | 200 |
| [网道 TypeScript 教程](https://wangdoc.com/typescript/) / 阮一峰 / 网道 | 第三方作者 | 语言/通用 | 网页、书籍、教程 / zh-CN | chapter-specific; distinguishes legacy and new decorators | 200 |
| [TypeScript 入门教程](https://ts.xcatliu.com/) / xcatliu | 第三方作者 | 语言/通用 | 网页、书籍、教程 / zh-CN | chapter-specific | 200 |
| [冴羽 JavaScript 与 TypeScript 深入系列](https://github.com/mqyqingfeng/Blog) / 冴羽 / mqyqingfeng | 第三方作者 | react, nextjs, svelte | 仓库、网页、教程 / zh-CN | article-specific; historical series and modern articles coexist | 200 |
| [mini-vue 源码学习项目](https://github.com/cuixiaorui/mini-vue) / 崔学锐与贡献者 | 第三方作者 | vue | 仓库、示例/源码、视频、项目 / zh-CN | educational implementation; not full Vue compatibility | 200 |
| [Vue.js 技术揭秘](https://ustbhuangyi.github.io/vue-analysis/) / 黄轶 | 第三方作者 | vue | 网页、书籍、教程 / zh-CN | Vue 2 source; not Vue 3 reactivity | 200 |
| [深入浅出 Webpack](https://github.com/gwuhaolin/dive-into-webpack) / 吴浩麟 | 第三方作者 | webpack | 仓库、Markdown、书籍 / zh-CN | 2017-era webpack; historical configuration | 404 |
| [Node.js 包教不包会](https://github.com/alsotang/node-lessons) / alsotang | 第三方作者 | nodejs, express | 仓库、教程、示例/源码 / zh-CN | historical Node/Express lessons; inspect individual dependencies | 200 |
| [深入理解 TypeScript 中文版](https://jkchao.github.io/typescript-book-chinese/) / Basarat Ali Syed；jkchao 等译 | 社区译文 | 语言/通用 | 网页、书籍 / zh-CN | community translation; original book version may differ | 200 |
| [Day.js Documentation](https://day.js.org/docs/en/installation/installation) / Day.js contributors | 项目官方 | dayjs | 网页、参考 / en | rolling; resolve library major and runtime compatibility before use | 200 |
| [i18next Documentation](https://www.i18next.com/overview/getting-started) / i18next contributors | 项目官方 | i18next | 网页、参考 / en | rolling; resolve library major and runtime compatibility before use | 200 |
| [GraphQL.js Documentation](https://www.graphql-js.org/docs/) / GraphQL Foundation | 项目官方 | graphql | 网页、参考 / en | rolling; resolve library major and runtime compatibility before use | 200 |
| [Mock Service Worker Documentation](https://mswjs.io/docs/) / MSW contributors | 项目官方 | msw | 网页、参考 / en | rolling; resolve library major and runtime compatibility before use | 200 |
| [Turborepo Documentation](https://turborepo.com/docs) / Vercel / Turborepo contributors | 项目官方 | turborepo | 网页、参考 / en | rolling; resolve library major and runtime compatibility before use | 200 |
| [Nx Documentation](https://nx.dev/docs) / Nx contributors | 项目官方 | nx | 网页、参考 / en | rolling; resolve library major and runtime compatibility before use | 200 |
| [Selenium WebDriver Documentation](https://www.selenium.dev/documentation/webdriver/) / Selenium / Software Freedom Conservancy | 项目官方 | selenium | 网页、参考 / en | Selenium 4; select supported language binding | 200 |

## TypeScript

| 资料与发布者 | 来源 | 生态 | 载体 / 正文语言 | 适用版本 | HTTP |
| --- | --- | --- | --- | --- | --- |
| [Node.js Learn](https://nodejs.org/en/learn/getting-started/introduction-to-nodejs) / Node.js project | 项目官方 | nodejs | 网页、教程 / en | rolling | 200 |
| [Node.js 22 API Documentation](https://nodejs.org/docs/latest-v22.x/api/) / Node.js project | 项目官方 | nodejs | 网页、参考 / en | Node.js 22 family | 200 |
| [npm Documentation](https://docs.npmjs.com/) / npm | 项目官方 | npm | 网页、参考 / en | CLI-version-specific | 200 |
| [React Learn](https://react.dev/learn) / React team | 项目官方 | react | 网页、教程、交互 / en | rolling | 200 |
| [React Learn in Simplified Chinese](https://zh-hans.react.dev/learn) / React documentation translation team | 项目官方 | react | 网页、教程、交互 / zh-CN | localized rolling documentation | 200 |
| [Vue Guide](https://vuejs.org/guide/introduction.html) / Vue team | 项目官方 | vue | 网页、教程 / en | Vue 3; check page | 200 |
| [Vue Guide in Chinese](https://cn.vuejs.org/guide/introduction.html) / Vue team | 项目官方 | vue | 网页、教程 / zh-CN | Vue 3; check page | 200 |
| [Express Getting Started](https://expressjs.com/en/starter/installing.html) / Express project | 项目官方 | express | 网页、教程 / en | page-specific; Express 4 and 5 differ | 200 |
| [Vitest Getting Started](https://vitest.dev/guide/) / Vitest team | 项目官方 | vitest | 网页、教程、参考 / en | rolling | 200 |
| [Full Stack Open](https://fullstackopen.com/en/) / University of Helsinki and contributors | 第三方作者 | react, nodejs, express | 网页、课程、练习、项目 / en | course-part-specific | 200 |
| [TypeScript Handbook](https://www.typescriptlang.org/docs/handbook/intro.html) / Microsoft TypeScript team | 项目官方 | 语言/通用 | 网页、参考、教程 / en | rolling | 200 |
| [TypeScript Documentation in Chinese](https://www.typescriptlang.org/zh/docs/) / TypeScript documentation team | 项目官方 | 语言/通用 | 网页、参考、教程 / zh-CN | localized rolling documentation | 200 |
| [TSConfig Reference](https://www.typescriptlang.org/tsconfig/) / Microsoft TypeScript team | 项目官方 | 语言/通用 | 网页、参考 / en | rolling | 200 |
| [TypeScript Release Notes](https://www.typescriptlang.org/docs/handbook/release-notes/overview.html) / Microsoft TypeScript team | 项目官方 | 语言/通用 | 网页、参考 / en | release-specific | 200 |
| [Using TypeScript with React](https://react.dev/learn/typescript) / React team | 项目官方 | react | 网页、教程 / en | rolling | 200 |
| [TypeScript Deep Dive](https://basarat.gitbook.io/typescript) / Basarat Ali Syed | 第三方作者 | 语言/通用 | 网页、书籍、示例/源码 / en | chapter-specific; some historical guidance | 200 |
| [Total TypeScript Essentials](https://www.totaltypescript.com/books/total-typescript-essentials) / Matt Pocock and Taylor Bell | 第三方作者 | 语言/通用 | 网页、书籍、练习 / en | online book edition | 200 |
| [Exploring TypeScript](https://exploringjs.com/ts/book/index.html) / Axel Rauschmayer | 第三方作者 | 语言/通用 | 网页、书籍 / en | book edition; inspect feature versions | 404 |
| [React TypeScript Cheatsheets](https://react-typescript-cheatsheet.netlify.app/docs/basic/setup/) / React TypeScript Cheatsheets community | 第三方作者 | react | 网页、参考、示例/源码 / en | rolling | 200 |
| [Type Challenges](https://github.com/type-challenges/type-challenges) / Type Challenges contributors | 第三方作者 | 语言/通用 | 仓库、练习、示例/源码 / en, zh-CN | challenge and compiler specific | 200 |
| [freeCodeCamp Curriculum](https://www.freecodecamp.org/learn/) / freeCodeCamp | 第三方作者 | 语言/通用 | 网页、课程、交互、项目 / en | certification edition | 200 |
| [TypeScript 5.9 Release Notes](https://www.typescriptlang.org/docs/handbook/release-notes/typescript-5-9.html) / Microsoft TypeScript team | 项目官方 | 语言/通用 | 网页、参考 / en | TypeScript 5.9 | 200 |
| [Next.js Documentation](https://nextjs.org/docs) / Vercel / Next.js contributors | 项目官方 | nextjs, react | 网页、参考 / en | rolling; distinguish App Router and Pages Router | 200 |
| [Angular Tutorials](https://angular.dev/tutorials) / Angular team | 项目官方 | angular | 网页、教程、交互 / en | rolling; not AngularJS | 200 |
| [Svelte Tutorial](https://svelte.dev/tutorial/svelte/welcome-to-svelte) / Svelte contributors | 项目官方 | svelte | 网页、教程、交互 / en | current tutorial; distinguish Svelte 4 and 5 | 200 |
| [SvelteKit Documentation](https://svelte.dev/docs/kit/introduction) / Svelte contributors | 项目官方 | svelte, sveltekit | 网页、参考 / en | rolling; resolve library major and runtime compatibility before use | 200 |
| [Nuxt Documentation](https://nuxt.com/docs) / Nuxt contributors | 项目官方 | nuxt, vue | 网页、参考 / en | version-selector; do not mix Nuxt 2/3/4 examples | 200 |
| [Astro Documentation](https://docs.astro.build/en/getting-started/) / Astro contributors | 项目官方 | astro | 网页、教程 / en | rolling | 200 |
| [NestJS Documentation](https://docs.nestjs.com/) / NestJS contributors | 项目官方 | nestjs | 网页、参考 / en | rolling; resolve library major and runtime compatibility before use | 200 |
| [Fastify Getting Started](https://fastify.dev/docs/latest/Guides/Getting-Started/) / Fastify / OpenJS Foundation | 项目官方 | fastify | 网页、教程 / en | latest alias | 200 |
| [Hono Documentation](https://hono.dev/docs/) / Hono contributors | 项目官方 | hono | 网页、参考 / en | rolling; resolve library major and runtime compatibility before use | 200 |
| [Koa Documentation](https://koajs.com/) / Koa contributors | 项目官方 | koa | 网页、参考 / en | rolling; resolve library major and runtime compatibility before use | 200 |
| [React Router Documentation](https://reactrouter.com/start/declarative/installation) / React Router contributors | 项目官方 | react-router, react | 网页、参考 / en | mode and major-version specific; distinguish Remix-era docs | 200 |
| [Vue Router Guide](https://router.vuejs.org/guide/) / Vue Router contributors | 项目官方 | vue-router, vue | 网页、参考 / en | Vue Router 4 / Vue 3 | 200 |
| [Redux Essentials Tutorial](https://redux.js.org/tutorials/essentials/part-1-overview-concepts) / Redux maintainers | 项目官方 | redux, redux-toolkit, react | 网页、教程 / en | rolling; modern Redux Toolkit approach | 200 |
| [Zustand Introduction](https://zustand.docs.pmnd.rs/learn/getting-started/introduction) / Poimandres / Zustand contributors | 项目官方 | zustand, react | 网页、参考 / en | rolling; resolve library major and runtime compatibility before use | 200 |
| [Pinia Introduction](https://pinia.vuejs.org/introduction.html) / Pinia / Vue contributors | 项目官方 | pinia, vue | 网页、参考 / en | rolling; resolve library major and runtime compatibility before use | 200 |
| [TanStack Query Documentation](https://tanstack.com/query/latest/docs/framework/react/overview) / TanStack contributors | 项目官方 | tanstack-query, react-query | 网页、参考 / en | latest alias; select UI binding before use | 200 |
| [TanStack Router Documentation](https://tanstack.com/router/latest/docs/framework/react/overview) / TanStack contributors | 项目官方 | tanstack-router | 网页、参考 / en | latest alias; select UI binding before use | 200 |
| [Axios Documentation](https://axios-http.com/docs/intro) / Axios maintainers | 项目官方 | axios | 网页、参考 / en | rolling; resolve library major and runtime compatibility before use | 200 |
| [Zod Documentation](https://zod.dev/) / Zod maintainers | 项目官方 | zod | 网页、参考 / en | major-version-specific | 200 |
| [React Hook Form Documentation](https://react-hook-form.com/get-started) / React Hook Form contributors | 项目官方 | react-hook-form, react | 网页、教程 / en | rolling | 200 |
| [tRPC Documentation](https://trpc.io/docs/) / tRPC contributors | 项目官方 | trpc | 网页、参考 / en | version-specific; TypeScript-first client and server | 200 |
| [Prisma ORM Documentation](https://www.prisma.io/docs/orm) / Prisma | 项目官方 | prisma | 网页、参考 / en | major-version and connector specific; local ORM distinct from paid platform | 200 |
| [Drizzle ORM Documentation](https://orm.drizzle.team/docs/overview) / Drizzle team | 项目官方 | drizzle | 网页、参考 / en | version and dialect specific | 200 |
| [TypeORM Documentation](https://typeorm.io/docs/) / TypeORM contributors | 项目官方 | typeorm | 网页、参考 / en | version and driver specific | 200 |
| [Sequelize Documentation](https://sequelize.org/docs/v6/) / Sequelize contributors | 项目官方 | sequelize | 网页、参考 / en | Sequelize 6; not v7 prerelease documentation | 200 |
| [Knex.js Guide](https://knexjs.org/guide/) / Knex contributors | 项目官方 | knex | 网页、参考 / en | version and dialect specific | 200 |
| [node-postgres Documentation](https://node-postgres.com/) / Brian Carlson and contributors | 项目官方 | node-postgres, postgresql | 网页、参考 / en | rolling; resolve library major and runtime compatibility before use | 200 |
| [MySQL2 Documentation](https://sidorares.github.io/node-mysql2/docs) / MySQL2 contributors | 项目官方 | mysql2, mysql | 网页、参考 / en | rolling; resolve library major and runtime compatibility before use | 200 |
| [Mongoose Guide](https://mongoosejs.com/docs/guide.html) / Mongoose contributors | 项目官方 | mongoose, mongodb | 网页、参考 / en | major-version-specific | 200 |
| [Socket.IO Documentation](https://socket.io/docs/v4/) / Socket.IO contributors | 项目官方 | socketio | 网页、参考 / en | Socket.IO 4; not raw WebSocket protocol | 200 |
| [RxJS Guide](https://rxjs.dev/guide/overview) / RxJS contributors | 项目官方 | rxjs | 网页、参考 / en | rolling; resolve library major and runtime compatibility before use | 200 |
| [Lodash Documentation](https://lodash.com/docs/) / Lodash contributors | 项目官方 | lodash | 网页、参考 / en | rolling; resolve library major and runtime compatibility before use | 200 |
| [date-fns Documentation](https://date-fns.org/docs/Getting-Started) / date-fns contributors | 项目官方 | date-fns | 网页、参考 / en | major-version-specific | 200 |
| [Vite Guide](https://vite.dev/guide/) / Vite contributors | 项目官方 | vite | 网页、参考 / en | rolling; major-version-specific | 200 |
| [webpack Guides](https://webpack.js.org/guides/) / webpack contributors | 项目官方 | webpack | 网页、教程 / en | guide-version-specific | 200 |
| [Rollup Tutorial](https://rollupjs.org/tutorial/) / Rollup contributors | 项目官方 | rollup | 网页、教程 / en | rolling | 200 |
| [esbuild Documentation](https://esbuild.github.io/) / Evan Wallace | 项目官方 | esbuild | 网页、参考 / en | selected release | 200 |
| [Babel Documentation](https://babeljs.io/docs/) / Babel contributors | 项目官方 | babel | 网页、参考 / en | major-version-specific | 200 |
| [ESLint Documentation](https://eslint.org/docs/latest/) / ESLint / OpenJS Foundation | 项目官方 | eslint | 网页、参考 / en | latest alias; distinguish flat and legacy config | 200 |
| [Prettier Documentation](https://prettier.io/docs/) / Prettier contributors | 项目官方 | prettier | 网页、参考 / en | rolling; resolve library major and runtime compatibility before use | 200 |
| [pnpm Documentation](https://pnpm.io/) / pnpm contributors | 项目官方 | pnpm | 网页、参考 / en | major-version-specific | 200 |
| [Yarn Documentation](https://yarnpkg.com/getting-started) / Yarn contributors | 项目官方 | yarn | 网页、参考 / en | Yarn modern; not Classic 1.x | 200 |
| [Jest Getting Started](https://jestjs.io/docs/getting-started) / Jest contributors | 项目官方 | jest | 网页、教程 / en | version-selector | 200 |
| [Playwright Documentation](https://playwright.dev/docs/intro) / Microsoft / Playwright contributors | 项目官方 | playwright | 网页、教程 / en | rolling | 200 |
| [Cypress Documentation](https://docs.cypress.io/app/get-started/why-cypress) / Cypress | 项目官方 | cypress | 网页、参考 / en | rolling; resolve library major and runtime compatibility before use | 200 |
| [Testing Library Documentation](https://testing-library.com/docs/) / Testing Library contributors | 项目官方 | testing-library | 网页、参考 / en | rolling; resolve library major and runtime compatibility before use | 200 |
| [Storybook Documentation](https://storybook.js.org/docs) / Storybook contributors | 项目官方 | storybook | 网页、参考 / en | version and UI-framework specific | 200 |
| [React Native Documentation](https://reactnative.dev/docs/getting-started) / Meta / React Native contributors | 项目官方 | react-native, react | 网页、教程、交互 / en | version-selector | 200 |
| [Expo Tutorial](https://docs.expo.dev/tutorial/introduction/) / Expo | 项目官方 | expo, react-native | 网页、教程 / en | SDK-specific; paid services distinct from local framework | 200 |
| [Electron Tutorial](https://www.electronjs.org/docs/latest/tutorial/tutorial-prerequisites) / Electron / OpenJS Foundation | 项目官方 | electron | 网页、教程 / en | latest alias | 200 |
| [D3 Documentation](https://d3js.org/getting-started) / D3 maintainers | 项目官方 | d3 | 网页、参考 / en | major-version-specific | 200 |
| [Apache ECharts Handbook](https://echarts.apache.org/handbook/en/get-started/) / Apache ECharts | 项目官方 | echarts | 网页、教程 / en | major-version-specific | 200 |
| [Chart.js Documentation](https://www.chartjs.org/docs/latest/) / Chart.js contributors | 项目官方 | chartjs | 网页、参考 / en | latest alias | 200 |
| [Three.js Manual](https://threejs.org/manual/) / Three.js contributors | 项目官方 | threejs | 网页、参考 / en | release-specific | 200 |
| [jQuery API Documentation](https://api.jquery.com/) / jQuery / OpenJS Foundation | 项目官方 | jquery | 网页、参考 / en | API-version markers; established-project reference | 200 |
| [Tailwind CSS Documentation](https://tailwindcss.com/docs/installation/using-vite) / Tailwind Labs | 项目官方 | tailwindcss | 网页、参考 / en | current major; keep v3 and v4 instructions separate | 200 |
| [Bootstrap 5.3 Documentation](https://getbootstrap.com/docs/5.3/getting-started/introduction/) / Bootstrap team | 项目官方 | bootstrap | 网页、参考 / en | Bootstrap 5.3; not Bootstrap 6 preview | 200 |
| [Sass Documentation](https://sass-lang.com/documentation/) / Sass contributors | 项目官方 | sass | 网页、参考 / en | rolling; resolve library major and runtime compatibility before use | 200 |
| [Less Documentation](https://lesscss.org/) / Less contributors | 项目官方 | less | 网页、参考 / en | rolling; resolve library major and runtime compatibility before use | 200 |
| [PostCSS Documentation](https://postcss.org/docs/) / PostCSS contributors | 项目官方 | postcss | 网页、参考 / en | rolling; resolve library major and runtime compatibility before use | 200 |
| [Stylelint User Guide](https://stylelint.io/user-guide/get-started) / Stylelint contributors | 项目官方 | stylelint | 网页、参考 / en | rolling; resolve library major and runtime compatibility before use | 200 |
| [Bulma Documentation](https://bulma.io/documentation/) / Jeremy Thomas / Bulma contributors | 项目官方 | bulma | 网页、参考 / en | rolling; resolve library major and runtime compatibility before use | 200 |
| [htmx Documentation](https://htmx.org/docs/) / htmx contributors | 项目官方 | htmx | 网页、参考 / en | version-specific | 200 |
| [Alpine.js Start Here](https://alpinejs.dev/start-here) / Alpine.js contributors | 项目官方 | alpinejs | 网页、教程 / en | rolling | 200 |
| [Material UI Documentation](https://mui.com/material-ui/getting-started/) / MUI | 项目官方 | mui, react | 网页、参考 / en | rolling; resolve library major and runtime compatibility before use | 200 |
| [Ant Design Documentation](https://ant.design/docs/react/introduce) / Ant Design contributors | 项目官方 | ant-design, react | 网页、参考 / en | rolling; resolve library major and runtime compatibility before use | 200 |
| [Element Plus Guide](https://element-plus.org/en-US/guide/design.html) / Element Plus contributors | 项目官方 | element-plus, vue | 网页、参考 / en | Vue 3 / Element Plus; not Vue 2 Element UI | 200 |
| [Vuetify Documentation](https://vuetifyjs.com/en/introduction/why-vuetify/) / Vuetify contributors | 项目官方 | vuetify, vue | 网页、参考 / en | version-specific | 200 |
| [Radix Primitives Documentation](https://www.radix-ui.com/primitives/docs/overview/introduction) / Radix contributors | 项目官方 | radix, react | 网页、参考 / en | rolling; resolve library major and runtime compatibility before use | 200 |
| [shadcn/ui Documentation](https://ui.shadcn.com/docs) / shadcn/ui contributors | 项目官方 | shadcn, react | 网页、参考 / en | source-distribution and dependency versions vary | 200 |
| [VueUse Guide](https://vueuse.org/guide/) / VueUse contributors | 项目官方 | vueuse, vue | 网页、参考 / en | rolling; resolve library major and runtime compatibility before use | 200 |
| [Solid Documentation](https://docs.solidjs.com/) / Solid contributors | 项目官方 | solidjs | 网页、参考 / en | rolling; resolve library major and runtime compatibility before use | 200 |
| [Preact Guide](https://preactjs.com/guide/v10/getting-started) / Preact contributors | 项目官方 | preact | 网页、参考 / en | Preact 10 | 200 |
| [Lit Documentation](https://lit.dev/docs/) / Lit contributors | 项目官方 | lit | 网页、参考 / en | rolling; resolve library major and runtime compatibility before use | 200 |
| [TanStack Start Documentation](https://tanstack.com/start/latest/docs/framework/react/overview) / TanStack contributors | 项目官方 | tanstack-start | 网页、参考 / en | latest alias; select UI binding and runtime | 200 |
| [NgRx Documentation](https://ngrx.io/docs) / NgRx contributors | 项目官方 | ngrx, angular | 网页、参考 / en | rolling; resolve library major and runtime compatibility before use | 200 |
| [MobX Documentation](https://mobx.js.org/README.html) / MobX contributors | 项目官方 | mobx | 网页、参考 / en | rolling; resolve library major and runtime compatibility before use | 200 |
| [Apollo Client Documentation](https://www.apollographql.com/docs/react/) / Apollo GraphQL | 项目官方 | apollo, graphql, react | 网页、参考 / en | rolling; resolve library major and runtime compatibility before use | 200 |
| [Bun Documentation](https://bun.com/docs) / Bun contributors | 项目官方 | bun | 网页、参考 / en | rolling; not the Node.js execution recipe | 200 |
| [Deno Documentation](https://docs.deno.com/runtime/) / Deno contributors | 项目官方 | deno | 网页、参考 / en | rolling; not the Node.js execution recipe | 200 |
| [Biome Documentation](https://biomejs.dev/guides/getting-started/) / Biome contributors | 项目官方 | biome | 网页、教程 / en | rolling | 200 |
| [gRPC Language Guides](https://grpc.io/docs/) / gRPC contributors | 项目官方 | grpc | 网页、参考 / en | select language and runtime guide; language support differs | 200 |
| [OpenTelemetry Language APIs and SDKs](https://opentelemetry.io/docs/languages/) / OpenTelemetry contributors / CNCF | 项目官方 | opentelemetry | 网页、参考 / en | language and signal stability differ | 200 |
| [Redis Client Libraries](https://redis.io/docs/latest/develop/clients/) / Redis | 项目官方 | redis | 网页、参考 / en | latest alias; distinguish server, client and license versions | 200 |
| [MongoDB Drivers](https://www.mongodb.com/docs/drivers/) / MongoDB | 项目官方 | mongodb | 网页、参考 / en | driver-language and server-version specific | 200 |
| [RabbitMQ Tutorials](https://www.rabbitmq.com/tutorials) / RabbitMQ maintainers | 项目官方 | rabbitmq | 网页、教程、示例/源码 / en | language-specific examples; not all SDKs have every tutorial | 200 |
| [Patterns.dev](https://www.patterns.dev/) / Lydia Hallie, Addy Osmani and contributors | 第三方作者 | react, vue, nextjs | 网页、书籍、示例/源码 / en | article-specific | 200 |
| [Full Stack Open Advanced State Management](https://fullstackopen.com/en/part6) / University of Helsinki and contributors | 第三方作者 | redux, redux-toolkit, tanstack-query, react | 网页、课程、练习 / en | course-part-specific | 200 |
| [Full Stack Open Testing React Apps](https://fullstackopen.com/en/part5) / University of Helsinki and contributors | 第三方作者 | react, playwright, testing-library | 网页、课程、练习 / en | course-part-specific | 200 |
| [Vite 官方中文指南](https://cn.vite.dev/guide/) / Vite 中文贡献者 | 项目官方 | vite | 网页、参考 / zh-CN | version-specific; Chinese and original editions may differ | 200 |
| [Pinia 中文指南](https://pinia.vuejs.org/zh/introduction.html) / Pinia / Vue 中文贡献者 | 项目官方 | pinia, vue | 网页、参考 / zh-CN | translation revision visible on site; may lag original | 200 |
| [Vue Router 中文指南](https://router.vuejs.org/zh/guide/) / Vue Router 中文贡献者 | 项目官方 | vue-router, vue | 网页、参考 / zh-CN | Vue Router 4 / Vue 3 | 200 |
| [Ant Design 中文文档](https://ant.design/docs/react/introduce-cn) / Ant Design 团队与贡献者 | 项目官方 | ant-design, react | 网页、参考 / zh-CN | major-version-specific | 200 |
| [Element Plus 中文指南](https://element-plus.org/zh-CN/guide/design.html) / Element Plus 贡献者 | 项目官方 | element-plus, vue | 网页、参考 / zh-CN | Vue 3 / Element Plus | 200 |
| [Apache ECharts 中文手册](https://echarts.apache.org/handbook/zh/index.html) / Apache ECharts | 项目官方 | echarts | 网页、参考 / zh-CN | distinguish ECharts 5/6 migration docs | 200 |
| [Axios 中文文档](https://axios-http.com/zh/docs/intro) / Axios 中文贡献者 | 项目官方 | axios | 网页、参考 / zh-CN | translation-version-specific | 200 |
| [pnpm 中文文档](https://pnpm.io/zh/) / pnpm 中文贡献者 | 项目官方 | pnpm | 网页、参考 / zh-CN | major-version-specific | 200 |
| [Vitest 中文指南](https://cn.vitest.dev/guide/) / Vitest 中文贡献者 | 项目官方 | vitest | 网页、参考 / zh-CN | version-specific | 200 |
| [Nuxt 中文文档](https://nuxt.com.cn/docs/getting-started/introduction) / Nuxt 中文社区 | 社区译文 | nuxt, vue | 网页、参考 / zh-CN | community translation; resolve matching original major | 网络错误 |
| [VueUse 中文指南](https://vueuse.org/zh/guide/) / VueUse 中文贡献者 | 项目官方 | vueuse, vue | 网页、参考 / zh-CN | translation coverage varies | 200 |
| [uni-app 文档](https://uniapp.dcloud.net.cn/) / DCloud / uni-app | 项目官方 | uniapp, vue | 网页、参考 / zh-CN | target and toolchain specific; cloud products are separate | 200 |
| [Taro 中文文档](https://docs.taro.zone/docs/) / Taro 贡献者 | 项目官方 | taro, react | 网页、参考 / zh-CN | target and major-version specific | 网络错误 |
| [Umi 中文文档](https://umijs.org/docs/introduce/introduce) / Umi 贡献者 | 项目官方 | umi, react | 网页、参考 / zh-CN | major-version-specific | 200 |
| [Naive UI 中文文档](https://github.com/tusen-ai/naive-ui/tree/main/demo/pages/docs) / Naive UI 贡献者 | 项目官方 | naiveui, vue | 仓库、Markdown、参考 / zh-CN | Vue 3; entry needs client-side rendering | 200 |
| [Vant 中文文档](https://vant-ui.github.io/vant/#/zh-CN/) / Vant 贡献者 | 项目官方 | vant, vue | 网页、参考 / zh-CN | hash-routed docs; resolve actual selected page when acquiring | 200 |
| [网道 JavaScript 教程](https://wangdoc.com/javascript/) / 阮一峰 / 网道 | 第三方作者 | 语言/通用 | 网页、书籍、教程 / zh-CN | chapter-specific | 200 |
| [ECMAScript 6 入门](https://es6.ruanyifeng.com/) / 阮一峰 | 第三方作者 | 语言/通用 | 网页、书籍、教程 / zh-CN | rolling; proposals and standardized features distinguished | 200 |
| [网道 TypeScript 教程](https://wangdoc.com/typescript/) / 阮一峰 / 网道 | 第三方作者 | 语言/通用 | 网页、书籍、教程 / zh-CN | chapter-specific; distinguishes legacy and new decorators | 200 |
| [TypeScript 入门教程](https://ts.xcatliu.com/) / xcatliu | 第三方作者 | 语言/通用 | 网页、书籍、教程 / zh-CN | chapter-specific | 200 |
| [冴羽 JavaScript 与 TypeScript 深入系列](https://github.com/mqyqingfeng/Blog) / 冴羽 / mqyqingfeng | 第三方作者 | react, nextjs, svelte | 仓库、网页、教程 / zh-CN | article-specific; historical series and modern articles coexist | 200 |
| [mini-vue 源码学习项目](https://github.com/cuixiaorui/mini-vue) / 崔学锐与贡献者 | 第三方作者 | vue | 仓库、示例/源码、视频、项目 / zh-CN | educational implementation; not full Vue compatibility | 200 |
| [Vue.js 技术揭秘](https://ustbhuangyi.github.io/vue-analysis/) / 黄轶 | 第三方作者 | vue | 网页、书籍、教程 / zh-CN | Vue 2 source; not Vue 3 reactivity | 200 |
| [深入浅出 Webpack](https://github.com/gwuhaolin/dive-into-webpack) / 吴浩麟 | 第三方作者 | webpack | 仓库、Markdown、书籍 / zh-CN | 2017-era webpack; historical configuration | 404 |
| [Node.js 包教不包会](https://github.com/alsotang/node-lessons) / alsotang | 第三方作者 | nodejs, express | 仓库、教程、示例/源码 / zh-CN | historical Node/Express lessons; inspect individual dependencies | 200 |
| [深入理解 TypeScript 中文版](https://jkchao.github.io/typescript-book-chinese/) / Basarat Ali Syed；jkchao 等译 | 社区译文 | 语言/通用 | 网页、书籍 / zh-CN | community translation; original book version may differ | 200 |
| [Day.js Documentation](https://day.js.org/docs/en/installation/installation) / Day.js contributors | 项目官方 | dayjs | 网页、参考 / en | rolling; resolve library major and runtime compatibility before use | 200 |
| [i18next Documentation](https://www.i18next.com/overview/getting-started) / i18next contributors | 项目官方 | i18next | 网页、参考 / en | rolling; resolve library major and runtime compatibility before use | 200 |
| [GraphQL.js Documentation](https://www.graphql-js.org/docs/) / GraphQL Foundation | 项目官方 | graphql | 网页、参考 / en | rolling; resolve library major and runtime compatibility before use | 200 |
| [Mock Service Worker Documentation](https://mswjs.io/docs/) / MSW contributors | 项目官方 | msw | 网页、参考 / en | rolling; resolve library major and runtime compatibility before use | 200 |
| [Turborepo Documentation](https://turborepo.com/docs) / Vercel / Turborepo contributors | 项目官方 | turborepo | 网页、参考 / en | rolling; resolve library major and runtime compatibility before use | 200 |
| [Nx Documentation](https://nx.dev/docs) / Nx contributors | 项目官方 | nx | 网页、参考 / en | rolling; resolve library major and runtime compatibility before use | 200 |
| [Selenium WebDriver Documentation](https://www.selenium.dev/documentation/webdriver/) / Selenium / Software Freedom Conservancy | 项目官方 | selenium | 网页、参考 / en | Selenium 4; select supported language binding | 200 |

## Go

| 资料与发布者 | 来源 | 生态 | 载体 / 正文语言 | 适用版本 | HTTP |
| --- | --- | --- | --- | --- | --- |
| [Getting Started with Go](https://go.dev/doc/tutorial/getting-started) / Go team | 项目官方 | 语言/通用 | 网页、教程 / en | rolling | 200 |
| [A Tour of Go](https://go.dev/tour/) / Go team | 项目官方 | 语言/通用 | 网页、教程、交互、练习 / en | rolling | 200 |
| [The Go Programming Language Specification](https://go.dev/ref/spec) / Go team | 项目官方 | 语言/通用 | 网页、规范 / en | living specification; feature version markers | 200 |
| [Go Standard Library](https://pkg.go.dev/std) / Go team | 项目官方 | 语言/通用 | 网页、参考、示例/源码 / en | selected toolchain version | 200 |
| [Go Modules Reference](https://go.dev/ref/mod) / Go team | 项目官方 | 语言/通用 | 网页、参考 / en | rolling | 200 |
| [Effective Go](https://go.dev/doc/effective_go) / Go team | 项目官方 | 语言/通用 | 网页、指南 / en | historical guide | 200 |
| [Gin Documentation](https://gin-gonic.com/en/docs/) / Gin project | 项目官方 | gin | 网页、教程、参考 / en | rolling | 200 |
| [GORM Guides](https://gorm.io/docs/index.html) / GORM project | 项目官方 | gorm | 网页、参考、教程 / en | rolling; distinguish generics and traditional APIs | 200 |
| [GORM Chinese Guides](https://gorm.io/zh_CN/docs/index.html) / GORM project | 项目官方 | gorm | 网页、参考 / zh-CN | rolling | 200 |
| [Go by Example](https://gobyexample.com/) / Go by Example contributors | 第三方作者 | 语言/通用 | 网页、示例/源码、教程 / en | examples target recent major Go releases | 200 |
| [Go by Example Chinese Translation](https://gobyexample-cn.github.io/) / gobyexample-cn contributors | 社区译文 | 语言/通用 | 网页、示例/源码、教程 / zh-CN | translation; verify upstream synchronization | 200 |
| [Learn Go with Tests](https://quii.gitbook.io/learn-go-with-tests) / Chris James and contributors | 第三方作者 | 语言/通用 | 网页、书籍、练习、示例/源码 / en | chapter-specific | 200 |
| [Go 101](https://go101.org/) / Tapir Liu and contributors | 第三方作者 | 语言/通用 | 网页、书籍 / en | book-specific | 200 |
| [Gophercises](https://gophercises.com/) / Jon Calhoun | 第三方作者 | 语言/通用 | 网页、视频、练习、项目、示例/源码 / en | exercise-specific | 200 |
| [Exercism Go Track](https://exercism.org/tracks/go) / Exercism community | 第三方作者 | 语言/通用 | 网页、练习、交互 / en | track-specific | 200 |
| [A Tour of Go in Chinese](https://tour.go-zh.org/) / Go Chinese translation contributors | 社区译文 | 语言/通用 | 网页、教程、交互、练习 / zh-CN | translation; verify upstream synchronization | 200 |
| [Go 1.26 Release Notes](https://go.dev/doc/go1.26) / Go team | 项目官方 | 语言/通用 | 网页、参考 / en | Go 1.26 | 200 |
| [Echo Documentation](https://echo.labstack.com/docs) / LabStack / Echo | 项目官方 | echo | 网页、参考 / en | rolling; resolve library major and runtime compatibility before use | 200 |
| [Fiber Documentation](https://docs.gofiber.io/) / Fiber contributors | 项目官方 | fiber | 网页、参考 / en | version-selector; v2 and v3 APIs and Go requirements differ | 200 |
| [chi Documentation](https://go-chi.io/) / chi contributors | 项目官方 | chi | 网页、参考 / en | version-specific | 200 |
| [Ent Getting Started](https://entgo.io/docs/getting-started/) / Ent / Atlas contributors | 项目官方 | ent | 网页、教程 / en | rolling | 200 |
| [sqlc Documentation](https://docs.sqlc.dev/en/latest/) / sqlc maintainers | 项目官方 | sqlc | 网页、参考 / en | latest alias | 200 |
| [sqlx Illustrated Guide](https://jmoiron.github.io/sqlx/) / Jason Moiron | 项目官方 | sqlx | 网页、参考 / en | rolling; resolve library major and runtime compatibility before use | 200 |
| [pgx PostgreSQL Driver Reference](https://pkg.go.dev/github.com/jackc/pgx/v5) / Jack Christensen and contributors | 项目官方 | pgx, postgresql | 网页、参考 / en | pgx v5 | 200 |
| [go-redis Guide](https://redis.io/docs/latest/develop/clients/go/) / Redis | 项目官方 | go-redis, redis | 网页、参考 / en | latest alias | 200 |
| [Cobra Documentation](https://cobra.dev/docs/) / Steve Francia / Cobra contributors | 项目官方 | cobra | 网页、参考 / en | rolling; resolve library major and runtime compatibility before use | 200 |
| [Viper Documentation](https://github.com/spf13/viper) / Steve Francia / Viper contributors | 项目官方 | viper | 仓库、参考、示例/源码 / en | release-specific | 200 |
| [Zap Reference](https://pkg.go.dev/go.uber.org/zap) / Uber / Zap contributors | 项目官方 | zap | 网页、参考 / en | selected module version | 200 |
| [Zerolog Reference](https://pkg.go.dev/github.com/rs/zerolog) / Olivier Poitrey and contributors | 项目官方 | zerolog | 网页、参考 / en | selected module version | 200 |
| [Testify Documentation](https://github.com/stretchr/testify) / Stretchr / Testify contributors | 项目官方 | testify | 仓库、参考、示例/源码 / en | Testify v1 | 200 |
| [GoMock Maintained Implementation](https://github.com/uber-go/mock) / Uber / GoMock contributors | 项目官方 | gomock | 仓库、参考、示例/源码 / en | go.uber.org/mock; not archived golang/mock | 200 |
| [mockery Documentation](https://vektra.github.io/mockery/latest/) / mockery contributors | 项目官方 | mockery | 网页、参考 / en | latest alias | 200 |
| [Ginkgo Documentation](https://onsi.github.io/ginkgo/) / Ginkgo contributors | 项目官方 | ginkgo | 网页、参考 / en | Ginkgo v2 | 200 |
| [Gomega Documentation](https://onsi.github.io/gomega/) / Gomega contributors | 项目官方 | gomega | 网页、参考 / en | rolling; resolve library major and runtime compatibility before use | 200 |
| [Testcontainers for Go](https://golang.testcontainers.org/) / Testcontainers contributors | 项目官方 | testcontainers | 网页、参考 / en | rolling; resolve library major and runtime compatibility before use | 200 |
| [Fx Documentation](https://uber-go.github.io/fx/) / Uber / Fx contributors | 项目官方 | fx | 网页、参考 / en | rolling; resolve library major and runtime compatibility before use | 200 |
| [golangci-lint Documentation](https://golangci-lint.run/) / golangci-lint contributors | 项目官方 | golangci-lint | 网页、参考 / en | major-version-specific | 200 |
| [Staticcheck Documentation](https://staticcheck.dev/docs/) / Dominik Honnef | 项目官方 | staticcheck | 网页、参考 / en | rolling; resolve library major and runtime compatibility before use | 200 |
| [validator Reference](https://pkg.go.dev/github.com/go-playground/validator/v10) / go-playground contributors | 项目官方 | validator | 网页、参考 / en | validator v10 | 200 |
| [golang-migrate Documentation](https://github.com/golang-migrate/migrate) / golang-migrate contributors | 项目官方 | golang-migrate | 仓库、参考、示例/源码 / en | module and driver version specific | 200 |
| [gqlgen Getting Started](https://gqlgen.com/getting-started/) / gqlgen contributors | 项目官方 | gqlgen, graphql | 网页、教程 / en | rolling | 200 |
| [Fyne Developer Documentation](https://docs.fyne.io/) / Fyne contributors | 项目官方 | fyne | 网页、参考 / en | rolling; resolve library major and runtime compatibility before use | 200 |
| [Ebitengine Documentation](https://ebitengine.org/en/documents/) / Hajime Hoshi / Ebitengine contributors | 项目官方 | ebitengine | 网页、参考 / en | rolling; resolve library major and runtime compatibility before use | 200 |
| [Hugo Documentation](https://gohugo.io/documentation/) / Hugo contributors | 项目官方 | hugo | 网页、参考 / en | rolling; distinguishes site authoring from Go extension development | 200 |
| [gRPC Language Guides](https://grpc.io/docs/) / gRPC contributors | 项目官方 | grpc | 网页、参考 / en | select language and runtime guide; language support differs | 200 |
| [OpenTelemetry Language APIs and SDKs](https://opentelemetry.io/docs/languages/) / OpenTelemetry contributors / CNCF | 项目官方 | opentelemetry | 网页、参考 / en | language and signal stability differ | 200 |
| [Redis Client Libraries](https://redis.io/docs/latest/develop/clients/) / Redis | 项目官方 | redis | 网页、参考 / en | latest alias; distinguish server, client and license versions | 200 |
| [MongoDB Drivers](https://www.mongodb.com/docs/drivers/) / MongoDB | 项目官方 | mongodb | 网页、参考 / en | driver-language and server-version specific | 200 |
| [RabbitMQ Tutorials](https://www.rabbitmq.com/tutorials) / RabbitMQ maintainers | 项目官方 | rabbitmq | 网页、教程、示例/源码 / en | language-specific examples; not all SDKs have every tutorial | 200 |
| [Protocol Buffers Tutorials](https://protobuf.dev/getting-started/) / Protocol Buffers contributors | 项目官方 | protobuf | 网页、教程、示例/源码 / en | language-generator and runtime version specific | 200 |
| [Go Web Examples](https://gowebexamples.com/) / Go Web Examples authors | 第三方作者 | 语言/通用 | 网页、教程、示例/源码 / en | example-specific; inspect imports and Go version | 200 |
| [Wild Workouts Go DDD Example](https://github.com/ThreeDotsLabs/wild-workouts-go-ddd-example) / Three Dots Labs | 第三方作者 | chi, grpc | 仓库、示例/源码、项目 / en | selected project revision | 200 |
| [Alex Edwards Go Tutorials](https://www.alexedwards.net/blog) / Alex Edwards | 第三方作者 | 语言/通用 | 网页、教程 / en | article-specific | 200 |
| [Gin 中文文档](https://gin-gonic.com/zh-cn/docs/) / Gin 文档贡献者 | 项目官方 | gin | 网页、参考 / zh-CN | version and translation specific | 200 |
| [GoFrame 中文文档](https://goframe.org/docs) / GoFrame 贡献者 | 项目官方 | goframe | 网页、参考 / zh-CN | version-selector | 403 |
| [go-zero 中文指南](https://go-zero.dev/zh-cn/guides/) / go-zero 贡献者 | 项目官方 | go-zero | 网页、参考 / zh-CN | rolling; generator and runtime versions must match | 200 |
| [Kratos 中文文档](https://go-kratos.dev/zh-cn/docs/) / Kratos 贡献者 | 项目官方 | kratos | 网页、参考 / zh-CN | Kratos v3; do not mix v2 module paths | 200 |
| [Kitex 中文文档](https://www.cloudwego.io/zh/docs/kitex/) / CloudWeGo / 字节跳动贡献者 | 项目官方 | kitex | 网页、参考 / zh-CN | release-specific | 200 |
| [Hertz 中文文档](https://www.cloudwego.io/zh/docs/hertz/) / CloudWeGo / 字节跳动贡献者 | 项目官方 | hertz | 网页、参考 / zh-CN | release-specific | 200 |
| [李文周 Go 原创教程](https://liwenzhou.com/) / 李文周 / Q1mi | 第三方作者 | gin, zap, viper | 网页、教程 / zh-CN | article-specific; public blog and course overview differ | 200 |
| [Go 语言高级编程](https://chai2010.cn/advanced-go-programming-book/) / 柴树杉、曹春晖 | 第三方作者 | grpc, protobuf | 网页、书籍、示例/源码 / zh-CN | online edition; distinguish commercial second edition | 200 |
| [七天用 Go 从零实现系列](https://geektutu.com/books/7days-golang/) / 极客兔兔 | 第三方作者 | 语言/通用 | 网页、书籍、教程、示例/源码 / zh-CN | 2019-era educational implementations | 200 |
| [Go 语言设计与实现](https://draven.co/golang/) / Draveness | 第三方作者 | 语言/通用 | 网页、书籍 / zh-CN | source-analysis chapter-specific Go revision | 200 |
| [煎鱼的 Go 文章](https://eddycjy.com/) / 煎鱼 / 脑子进煎鱼了 | 第三方作者 | gin, grpc | 网页、教程 / zh-CN | article-specific | 网络错误 |
| [Tony Bai Go 原创文章](https://tonybai.com/) / Tony Bai | 第三方作者 | 语言/通用 | 网页、教程 / zh-CN | article-specific | 200 |
| [Go 语言圣经中文版](https://gopl-zh.github.io/) / Alan A. A. Donovan、Brian W. Kernighan；柴树杉等译 | 社区译文 | 语言/通用 | 网页、书籍 / zh-CN | The Go Programming Language 2015 edition; predates generics | 200 |
| [通过测试学习 Go 中文版](https://studygolang.gitbook.io/learn-go-with-tests/) / Chris James；Go 中文社区译者 | 社区译文 | 语言/通用 | 网页、书籍 / zh-CN | community translation; original revision may differ | 200 |
| [Prometheus Go Client Guide](https://prometheus.io/docs/guides/go-application/) / Prometheus contributors / CNCF | 项目官方 | prometheus | 网页、教程 / en | client-module-specific | 200 |
| [Resty Documentation](https://resty.dev/) / Resty contributors | 项目官方 | resty | 网页、参考 / en | major-version-specific | 200 |
| [Beego Documentation](https://beegodoc.com/en-US/) / Beego contributors | 项目官方 | beego | 网页、参考 / en | version-selector | 200 |

## C#

| 资料与发布者 | 来源 | 生态 | 载体 / 正文语言 | 适用版本 | HTTP |
| --- | --- | --- | --- | --- | --- |
| [C# Language Documentation](https://learn.microsoft.com/en-us/dotnet/csharp/) / Microsoft | 项目官方 | 语言/通用 | 网页、教程、参考 / en | rolling; inspect compatibility tables | 200 |
| [C# Language Documentation in Chinese](https://learn.microsoft.com/zh-cn/dotnet/csharp/) / Microsoft | 项目官方 | 语言/通用 | 网页、教程、参考 / zh-CN | localized rolling documentation | 200 |
| [C# Language Reference](https://learn.microsoft.com/en-us/dotnet/csharp/language-reference/) / Microsoft | 项目官方 | 语言/通用 | 网页、参考 / en | feature-version-specific | 200 |
| [.NET Getting Started Tutorials](https://learn.microsoft.com/en-us/dotnet/standard/get-started) / Microsoft | 项目官方 | dotnet | 网页、教程 / en | tutorial-specific | 200 |
| [.NET API Browser](https://learn.microsoft.com/en-us/dotnet/api/) / Microsoft | 项目官方 | dotnet | 网页、参考 / en | API view and target-framework specific | 200 |
| [ASP.NET Core Documentation](https://learn.microsoft.com/en-us/aspnet/core/) / Microsoft | 项目官方 | aspnetcore | 网页、教程、参考 / en | selected documentation view | 200 |
| [Entity Framework Core Documentation](https://learn.microsoft.com/en-us/ef/core/) / Microsoft | 项目官方 | efcore | 网页、教程、参考 / en | EF Core version and provider specific | 200 |
| [C# for Beginners Video Series](https://learn.microsoft.com/en-us/shows/csharp-for-beginners/) / Microsoft | 项目官方 | 语言/通用 | 网页、视频、课程 / en | series edition | 200 |
| [Entity Framework Core 101](https://learn.microsoft.com/en-us/shows/entity-framework-core-101/) / Microsoft | 项目官方 | efcore | 网页、视频、课程 / en | historical introductory series; verify current APIs | 200 |
| [.NET Samples](https://github.com/dotnet/samples) / Microsoft / .NET contributors | 项目官方 | dotnet | 仓库、示例/源码、项目 / en | sample and target-framework specific | 200 |
| [C# Yellow Book, Cheese Edition](https://www.robmiles.com/c-yellow-book) / Rob Miles | 第三方作者 | 语言/通用 | 网页、书籍、PDF、幻灯片、练习、示例/源码 / en | 2019 edition; foundational material | 200 |
| [The C# Academy](https://thecsharpacademy.com/) / The C# Academy | 第三方作者 | dotnet | 网页、课程、项目 / en | project-specific | 200 |
| [Exercism C# Track](https://exercism.org/tracks/csharp) / Exercism community | 第三方作者 | 语言/通用 | 网页、练习、交互 / en | track-specific | 200 |
| [Exercism C# Exercise Sources](https://github.com/exercism/csharp) / Exercism community | 第三方作者 | 语言/通用 | 仓库、练习、示例/源码 / en | commit-specific | 200 |
| [C# 14 Language Changes](https://learn.microsoft.com/en-us/dotnet/csharp/whats-new/csharp-14) / Microsoft | 项目官方 | 语言/通用 | 网页、参考 / en | C# 14 / .NET 10 | 200 |
| [.NET 10 Overview](https://learn.microsoft.com/en-us/dotnet/core/whats-new/dotnet-10/overview) / Microsoft | 项目官方 | dotnet | 网页、参考 / en | .NET 10 | 200 |
| [Dapper Documentation](https://github.com/DapperLib/Dapper) / Dapper contributors | 项目官方 | dapper | 仓库、参考、示例/源码 / en | release-specific | 200 |
| [Json.NET Documentation](https://www.newtonsoft.com/json/help/html/Introduction.htm) / James Newton-King / Newtonsoft | 项目官方 | newtonsoft-json | 网页、参考 / en | rolling; resolve library major and runtime compatibility before use | 200 |
| [Serilog Getting Started](https://github.com/serilog/serilog/wiki/Getting-Started) / Serilog contributors | 项目官方 | serilog | 网页、参考 / en | rolling; resolve library major and runtime compatibility before use | 200 |
| [NLog Documentation](https://nlog-project.org/documentation/) / NLog contributors | 项目官方 | nlog | 网页、参考 / en | rolling; resolve library major and runtime compatibility before use | 200 |
| [FluentValidation Documentation](https://docs.fluentvalidation.net/en/latest/) / Jeremy Skinner and contributors | 项目官方 | fluentvalidation | 网页、参考 / en | latest alias | 200 |
| [AutoMapper Documentation](https://docs.automapper.io/en/stable/) / AutoMapper maintainers | 项目官方 | automapper | 网页、参考 / en | stable alias; check selected-major license requirements | 200 |
| [Mapster Documentation](https://github.com/MapsterMapper/Mapster/wiki) / Mapster contributors | 项目官方 | mapster | 网页、参考 / en | rolling; resolve library major and runtime compatibility before use | 200 |
| [MediatR Documentation](https://github.com/jbogard/MediatR/wiki) / MediatR maintainers | 项目官方 | mediatr | 网页、参考 / en | major-version-specific; check license requirements | 200 |
| [Polly Documentation](https://www.pollydocs.org/) / Polly contributors | 项目官方 | polly | 网页、参考 / en | Polly v8 documentation; v7 API differs | 200 |
| [Refit Documentation](https://github.com/reactiveui/refit) / Refit contributors | 项目官方 | refit | 仓库、参考、示例/源码 / en | release-specific | 200 |
| [MassTransit Documentation](https://masstransit.io/documentation/) / MassTransit maintainers | 项目官方 | masstransit | 网页、参考 / en | version and edition specific; check licensing before use | 200 |
| [Hangfire Documentation](https://docs.hangfire.io/en/latest/) / Hangfire maintainers | 项目官方 | hangfire | 网页、参考 / en | latest alias; core and paid extensions differ | 200 |
| [Quartz.NET Documentation](https://www.quartz-scheduler.net/documentation/) / Quartz.NET contributors | 项目官方 | quartznet | 网页、参考 / en | rolling; resolve library major and runtime compatibility before use | 200 |
| [xUnit.net Documentation](https://xunit.net/) / xUnit.net contributors | 项目官方 | xunit | 网页、参考 / en | distinguish v2 and v3 | 200 |
| [NUnit Documentation](https://docs.nunit.org/) / NUnit contributors | 项目官方 | nunit | 网页、参考 / en | rolling; resolve library major and runtime compatibility before use | 200 |
| [MSTest Overview](https://learn.microsoft.com/en-us/dotnet/core/testing/unit-testing-mstest-intro) / Microsoft | 项目官方 | mstest | 网页、参考 / en | selected .NET documentation view | 200 |
| [Moq Quickstart](https://github.com/devlooped/moq/wiki/Quickstart) / Moq maintainers | 项目官方 | moq | 网页、参考 / en | release-specific | 200 |
| [NSubstitute Help](https://nsubstitute.github.io/help/getting-started/) / NSubstitute contributors | 项目官方 | nsubstitute | 网页、教程 / en | rolling | 200 |
| [Shouldly Documentation](https://docs.shouldly.org/) / Shouldly contributors | 项目官方 | shouldly | 网页、参考 / en | rolling; resolve library major and runtime compatibility before use | 200 |
| [Fluent Assertions Documentation](https://fluentassertions.com/introduction) / Fluent Assertions maintainers | 项目官方 | fluentassertions | 网页、参考 / en | major-version-specific; check license requirements | 200 |
| [Testcontainers for .NET](https://dotnet.testcontainers.org/) / Testcontainers contributors | 项目官方 | testcontainers | 网页、参考 / en | rolling; resolve library major and runtime compatibility before use | 200 |
| [Npgsql Documentation](https://www.npgsql.org/doc/index.html) / Npgsql contributors | 项目官方 | npgsql, postgresql | 网页、参考 / en | driver and PostgreSQL version specific | 200 |
| [MySqlConnector Documentation](https://mysqlconnector.net/) / MySqlConnector contributors | 项目官方 | mysqlconnector, mysql | 网页、参考 / en | rolling; resolve library major and runtime compatibility before use | 200 |
| [StackExchange.Redis Documentation](https://github.com/StackExchange/StackExchange.Redis/blob/master/docs/index.md) / Stack Exchange / contributors | 项目官方 | stackexchange-redis, redis | 仓库、Markdown、参考 / en | rolling; resolve library major and runtime compatibility before use | 200 |
| [ASP.NET Core Blazor Documentation](https://learn.microsoft.com/en-us/aspnet/core/blazor/) / Microsoft | 项目官方 | blazor, aspnetcore | 网页、参考 / en | select exact ASP.NET Core documentation view | 200 |
| [ASP.NET Core SignalR Documentation](https://learn.microsoft.com/en-us/aspnet/core/signalr/introduction) / Microsoft | 项目官方 | signalr, aspnetcore | 网页、参考 / en | select exact ASP.NET Core documentation view | 200 |
| [ASP.NET Core Identity Documentation](https://learn.microsoft.com/en-us/aspnet/core/security/authentication/identity) / Microsoft | 项目官方 | identity, aspnetcore | 网页、参考 / en | select exact ASP.NET Core documentation view | 200 |
| [.NET Dependency Injection Documentation](https://learn.microsoft.com/en-us/dotnet/core/extensions/dependency-injection) / Microsoft | 项目官方 | dotnet-extensions, dotnet | 网页、参考 / en | select target .NET version | 200 |
| [.NET MAUI Documentation](https://learn.microsoft.com/en-us/dotnet/maui/) / Microsoft | 项目官方 | maui, dotnet | 网页、参考 / en | target and platform SDK specific | 200 |
| [WPF Documentation](https://learn.microsoft.com/en-us/dotnet/desktop/wpf/) / Microsoft | 项目官方 | wpf | 网页、参考 / en | Windows and target-framework specific | 200 |
| [Windows Forms Documentation](https://learn.microsoft.com/en-us/dotnet/desktop/winforms/) / Microsoft | 项目官方 | winforms | 网页、参考 / en | Windows and target-framework specific | 200 |
| [Avalonia Getting Started](https://docs.avaloniaui.net/docs/get-started/) / Avalonia contributors | 项目官方 | avalonia | 网页、教程 / en | platform and release specific | 200 |
| [Unity C# Scripting Manual](https://docs.unity3d.com/6/Documentation/Manual/intro-to-scripting.html) / Unity Technologies | 项目官方 | unity | 网页、参考 / en | Unity 6; .NET profile differs from general SDK | 200 |
| [Godot C# Basics](https://docs.godotengine.org/en/stable/tutorials/scripting/c_sharp/c_sharp_basics.html) / Godot contributors | 项目官方 | godot | 网页、教程 / en | stable alias; select .NET-enabled Godot and supported export target | 200 |
| [MonoGame Documentation](https://docs.monogame.net/) / MonoGame contributors | 项目官方 | monogame | 网页、参考 / en | rolling; resolve library major and runtime compatibility before use | 200 |
| [ML.NET Documentation](https://learn.microsoft.com/en-us/dotnet/machine-learning/) / Microsoft | 项目官方 | mlnet | 网页、参考 / en | target-framework and package specific | 200 |
| [Aspire Documentation](https://aspire.dev/) / Aspire contributors | 项目官方 | aspire | 网页、参考 / en | version-specific; remote services not required by catalogue | 200 |
| [Swashbuckle.AspNetCore Documentation](https://github.com/domaindrivendev/Swashbuckle.AspNetCore) / Swashbuckle contributors | 项目官方 | swashbuckle | 仓库、参考、示例/源码 / en | selected release; compare built-in ASP.NET Core OpenAPI | 200 |
| [gRPC Language Guides](https://grpc.io/docs/) / gRPC contributors | 项目官方 | grpc | 网页、参考 / en | select language and runtime guide; language support differs | 200 |
| [OpenTelemetry Language APIs and SDKs](https://opentelemetry.io/docs/languages/) / OpenTelemetry contributors / CNCF | 项目官方 | opentelemetry | 网页、参考 / en | language and signal stability differ | 200 |
| [Redis Client Libraries](https://redis.io/docs/latest/develop/clients/) / Redis | 项目官方 | redis | 网页、参考 / en | latest alias; distinguish server, client and license versions | 200 |
| [MongoDB Drivers](https://www.mongodb.com/docs/drivers/) / MongoDB | 项目官方 | mongodb | 网页、参考 / en | driver-language and server-version specific | 200 |
| [RabbitMQ Tutorials](https://www.rabbitmq.com/tutorials) / RabbitMQ maintainers | 项目官方 | rabbitmq | 网页、教程、示例/源码 / en | language-specific examples; not all SDKs have every tutorial | 200 |
| [Protocol Buffers Tutorials](https://protobuf.dev/getting-started/) / Protocol Buffers contributors | 项目官方 | protobuf | 网页、教程、示例/源码 / en | language-generator and runtime version specific | 200 |
| [Code Maze ASP.NET Core Tutorials](https://code-maze.com/net-core-series/) / Code Maze authors | 第三方作者 | aspnetcore | 网页、教程 / en | article-specific | 200 |
| [Code Maze EF Core and Data Access](https://code-maze.com/entity-framework-core-series/) / Code Maze authors | 第三方作者 | efcore, dapper | 网页、教程 / en | article-specific | 200 |
| [Andrew Lock .NET Articles](https://andrewlock.net/) / Andrew Lock | 第三方作者 | aspnetcore | 网页、教程 / en | article-specific | 200 |
| [FreeSql 中文指南](https://freesql.net/guide/) / FreeSql / .NET Core Community | 项目官方 | freesql | 网页、参考 / zh-CN | provider and release specific | 200 |
| [SqlSugar 中文文档](https://www.donet5.com/Home/Doc) / SqlSugar / dotnetnext | 项目官方 | sqlsugar | 网页、参考 / zh-CN | package and provider version specific | 200 |
| [Furion 中文文档](https://furion.net/docs/) / Furion / 百小僧 | 项目官方 | furion | 网页、参考 / zh-CN | release-specific; public documentation and paid support differ | 200 |
| [MASA Framework 中文项目说明](https://github.com/masastack/MASA.Framework) / MASA Stack | 项目官方 | masa, aspnetcore | 仓库、Markdown、示例/源码 / zh-CN | selected release; documentation website may require client rendering | 200 |
| [ABP Framework Documentation](https://abp.io/docs/latest/) / ABP 文档团队与中文贡献者 | 项目官方 | abp, aspnetcore, efcore | 网页、参考 / en | released-version selector; dev branch documentation may differ | 200 |
| [ASP.NET Core 中文文档](https://learn.microsoft.com/zh-cn/aspnet/core/) / Microsoft 文档团队 | 项目官方 | aspnetcore | 网页、参考 / zh-CN | select exact ASP.NET Core documentation view | 200 |
| [EF Core 中文文档](https://learn.microsoft.com/zh-cn/ef/core/) / Microsoft 文档团队 | 项目官方 | efcore | 网页、参考 / zh-CN | target EF and provider version specific | 200 |
| [Blazor 中文文档](https://learn.microsoft.com/zh-cn/aspnet/core/blazor/) / Microsoft 文档团队 | 项目官方 | blazor, aspnetcore | 网页、参考 / zh-CN | select exact ASP.NET Core documentation view | 200 |
| [Blog.Core 中文实战项目](https://github.com/anjoy8/Blog.Core) / 老张的哲学与贡献者 | 第三方作者 | aspnetcore, sqlsugar, serilog, automapper | 仓库、Markdown、示例/源码、项目 / zh-CN | branch-specific; repository description and README target versions differ | 200 |
| [.NET Core 中文示例项目](https://github.com/luoyunchong/dotnetcore-examples) / iGeekFan / luoyunchong | 第三方作者 | aspnetcore, freesql, automapper | 仓库、示例/源码、项目 / zh-CN | historical examples; per-project target framework | 200 |
| [.NET 中文实战教程示例](https://github.com/Meowv/Blog) / Meowv | 第三方作者 | aspnetcore, abp | 仓库、示例/源码、教程 / zh-CN | .NET 5 / ABP vNext historical tutorial; inspect selected branch | 200 |
| [Autofac Documentation](https://docs.autofac.org/en/latest/) / Autofac contributors | 项目官方 | autofac | 网页、参考 / en | latest alias | 200 |
| [BenchmarkDotNet Overview](https://benchmarkdotnet.org/articles/overview.html) / .NET Foundation / BenchmarkDotNet contributors | 项目官方 | benchmarkdotnet | 网页、参考 / en | rolling; resolve library major and runtime compatibility before use | 200 |
| [Humanizer Documentation](https://github.com/Humanizr/Humanizer) / Humanizer contributors | 项目官方 | humanizer | 仓库、参考、示例/源码 / en | release-specific | 200 |
| [Flurl Documentation](https://flurl.dev/docs/fluent-http/) / Todd Menier and contributors | 项目官方 | flurl | 网页、参考 / en | major-version-specific | 200 |
| [CAP 中文文档](https://cap.dotnetcore.xyz/user-guide/zh/getting-started/quick-start/) / .NET Core Community / CAP | 项目官方 | cap | 网页、教程 / zh-CN | release and transport specific | 200 |
| [Selenium WebDriver Documentation](https://www.selenium.dev/documentation/webdriver/) / Selenium / Software Freedom Conservancy | 项目官方 | selenium | 网页、参考 / en | Selenium 4; select supported language binding | 200 |

## HTML

| 资料与发布者 | 来源 | 生态 | 载体 / 正文语言 | 适用版本 | HTTP |
| --- | --- | --- | --- | --- | --- |
| [The Odin Project Foundations](https://www.theodinproject.com/paths/foundations/courses/foundations) / The Odin Project community | 第三方作者 | 语言/通用 | 网页、课程、项目 / en | rolling | 200 |
| [MDN Semantic HTML Learning Module](https://developer.mozilla.org/en-US/docs/Learn_web_development/Core/Structuring_content) / MDN contributors | 第三方作者 | 语言/通用 | 网页、教程、练习 / en | rolling | 200 |
| [MDN HTML Reference in Chinese](https://developer.mozilla.org/zh-CN/docs/Web/HTML) / MDN translation contributors | 社区译文 | 语言/通用 | 网页、参考 / zh-CN | translation; feature support varies | 200 |
| [HTML Living Standard](https://html.spec.whatwg.org/multipage/) / WHATWG | 项目官方 | 语言/通用 | 网页、规范 / en | living standard; not a browser compatibility guarantee | 200 |
| [Learn HTML](https://web.dev/learn/html) / Google Chrome team and authors | 第三方作者 | 语言/通用 | 网页、课程、练习 / en | rolling | 200 |
| [WAI Tutorials](https://www.w3.org/WAI/tutorials/) / W3C Web Accessibility Initiative | 项目官方 | 语言/通用 | 网页、教程 / en | tutorial-specific | 200 |
| [Learn Responsive Design](https://web.dev/learn/design) / Google Chrome team and authors | 第三方作者 | 语言/通用 | 网页、课程、交互 / en | rolling | 200 |
| [freeCodeCamp Curriculum](https://www.freecodecamp.org/learn/) / freeCodeCamp | 第三方作者 | 语言/通用 | 网页、课程、交互、项目 / en | certification edition | 200 |
| [The Odin Project Curriculum Sources](https://github.com/TheOdinProject/curriculum) / The Odin Project community | 第三方作者 | 语言/通用 | 仓库、Markdown、课程、项目 / en | commit-specific | 200 |
| [Tailwind CSS Documentation](https://tailwindcss.com/docs/installation/using-vite) / Tailwind Labs | 项目官方 | tailwindcss | 网页、参考 / en | current major; keep v3 and v4 instructions separate | 200 |
| [Bootstrap 5.3 Documentation](https://getbootstrap.com/docs/5.3/getting-started/introduction/) / Bootstrap team | 项目官方 | bootstrap | 网页、参考 / en | Bootstrap 5.3; not Bootstrap 6 preview | 200 |
| [Sass Documentation](https://sass-lang.com/documentation/) / Sass contributors | 项目官方 | sass | 网页、参考 / en | rolling; resolve library major and runtime compatibility before use | 200 |
| [Less Documentation](https://lesscss.org/) / Less contributors | 项目官方 | less | 网页、参考 / en | rolling; resolve library major and runtime compatibility before use | 200 |
| [PostCSS Documentation](https://postcss.org/docs/) / PostCSS contributors | 项目官方 | postcss | 网页、参考 / en | rolling; resolve library major and runtime compatibility before use | 200 |
| [Stylelint User Guide](https://stylelint.io/user-guide/get-started) / Stylelint contributors | 项目官方 | stylelint | 网页、参考 / en | rolling; resolve library major and runtime compatibility before use | 200 |
| [Bulma Documentation](https://bulma.io/documentation/) / Jeremy Thomas / Bulma contributors | 项目官方 | bulma | 网页、参考 / en | rolling; resolve library major and runtime compatibility before use | 200 |
| [htmx Documentation](https://htmx.org/docs/) / htmx contributors | 项目官方 | htmx | 网页、参考 / en | version-specific | 200 |
| [Alpine.js Start Here](https://alpinejs.dev/start-here) / Alpine.js contributors | 项目官方 | alpinejs | 网页、教程 / en | rolling | 200 |
| [网道 HTML 教程](https://wangdoc.com/html/) / 阮一峰 / 网道 | 第三方作者 | 语言/通用 | 网页、书籍、教程 / zh-CN | chapter-specific | 200 |
| [张鑫旭 CSS 与 Web 原创文章](https://www.zhangxinxu.com/wordpress/category/css/) / 张鑫旭 | 第三方作者 | 语言/通用 | 网页、教程 / zh-CN | article and browser-support specific | 200 |
| [iCSS CSS 奇思妙想](https://github.com/chokcoco/iCSS) / ChokCoco / 国服第一切图仔 | 第三方作者 | 语言/通用 | 仓库、网页、示例/源码、教程 / zh-CN | example and browser-support specific | 200 |
| [CSS Inspiration](https://github.com/chokcoco/CSS-Inspiration) / ChokCoco | 第三方作者 | 语言/通用 | 仓库、示例/源码、交互 / zh-CN | example and browser-support specific | 200 |

## CSS

| 资料与发布者 | 来源 | 生态 | 载体 / 正文语言 | 适用版本 | HTTP |
| --- | --- | --- | --- | --- | --- |
| [The Odin Project Foundations](https://www.theodinproject.com/paths/foundations/courses/foundations) / The Odin Project community | 第三方作者 | 语言/通用 | 网页、课程、项目 / en | rolling | 200 |
| [MDN CSS Fundamentals](https://developer.mozilla.org/en-US/docs/Learn_web_development/Core/Styling_basics) / MDN contributors | 第三方作者 | 语言/通用 | 网页、教程、练习 / en | rolling | 200 |
| [MDN CSS Reference in Chinese](https://developer.mozilla.org/zh-CN/docs/Web/CSS) / MDN translation contributors | 社区译文 | 语言/通用 | 网页、参考 / zh-CN | translation; feature support varies | 200 |
| [W3C CSS Specifications](https://www.w3.org/Style/CSS/specs.en.html) / W3C CSS Working Group | 项目官方 | 语言/通用 | 网页、规范 / en | module and publication-status specific | 200 |
| [Learn CSS](https://web.dev/learn/css) / Google Chrome team and authors | 第三方作者 | 语言/通用 | 网页、课程、交互、音频 / en | rolling | 200 |
| [WAI Tutorials](https://www.w3.org/WAI/tutorials/) / W3C Web Accessibility Initiative | 项目官方 | 语言/通用 | 网页、教程 / en | tutorial-specific | 200 |
| [Learn Responsive Design](https://web.dev/learn/design) / Google Chrome team and authors | 第三方作者 | 语言/通用 | 网页、课程、交互 / en | rolling | 200 |
| [CSS Diner](https://flukeout.github.io/) / Luke Pacholski / CSS Diner contributors | 第三方作者 | 语言/通用 | 网页、交互、练习 / en | exercise-specific | 200 |
| [Flexbox Froggy](https://flexboxfroggy.com/) / Codepip | 第三方作者 | 语言/通用 | 网页、交互、练习 / en, zh-CN | exercise-specific | 200 |
| [Grid Garden](https://cssgridgarden.com/) / Codepip | 第三方作者 | 语言/通用 | 网页、交互、练习 / en, zh-CN | exercise-specific | 200 |
| [freeCodeCamp Curriculum](https://www.freecodecamp.org/learn/) / freeCodeCamp | 第三方作者 | 语言/通用 | 网页、课程、交互、项目 / en | certification edition | 200 |
| [The Odin Project Curriculum Sources](https://github.com/TheOdinProject/curriculum) / The Odin Project community | 第三方作者 | 语言/通用 | 仓库、Markdown、课程、项目 / en | commit-specific | 200 |
| [Tailwind CSS Documentation](https://tailwindcss.com/docs/installation/using-vite) / Tailwind Labs | 项目官方 | tailwindcss | 网页、参考 / en | current major; keep v3 and v4 instructions separate | 200 |
| [Bootstrap 5.3 Documentation](https://getbootstrap.com/docs/5.3/getting-started/introduction/) / Bootstrap team | 项目官方 | bootstrap | 网页、参考 / en | Bootstrap 5.3; not Bootstrap 6 preview | 200 |
| [Sass Documentation](https://sass-lang.com/documentation/) / Sass contributors | 项目官方 | sass | 网页、参考 / en | rolling; resolve library major and runtime compatibility before use | 200 |
| [Less Documentation](https://lesscss.org/) / Less contributors | 项目官方 | less | 网页、参考 / en | rolling; resolve library major and runtime compatibility before use | 200 |
| [PostCSS Documentation](https://postcss.org/docs/) / PostCSS contributors | 项目官方 | postcss | 网页、参考 / en | rolling; resolve library major and runtime compatibility before use | 200 |
| [Stylelint User Guide](https://stylelint.io/user-guide/get-started) / Stylelint contributors | 项目官方 | stylelint | 网页、参考 / en | rolling; resolve library major and runtime compatibility before use | 200 |
| [Bulma Documentation](https://bulma.io/documentation/) / Jeremy Thomas / Bulma contributors | 项目官方 | bulma | 网页、参考 / en | rolling; resolve library major and runtime compatibility before use | 200 |
| [htmx Documentation](https://htmx.org/docs/) / htmx contributors | 项目官方 | htmx | 网页、参考 / en | version-specific | 200 |
| [Alpine.js Start Here](https://alpinejs.dev/start-here) / Alpine.js contributors | 项目官方 | alpinejs | 网页、教程 / en | rolling | 200 |
| [CSS-Tricks Flexbox Layout Guide](https://css-tricks.com/snippets/css/a-guide-to-flexbox/) / Chris Coyier / CSS-Tricks | 第三方作者 | 语言/通用 | 网页、教程 / en | article-specific | 200 |
| [CSS-Tricks Grid Layout Guide](https://css-tricks.com/snippets/css/complete-guide-grid/) / Chris House / CSS-Tricks | 第三方作者 | 语言/通用 | 网页、教程 / en | article-specific | 200 |
| [An Interactive Guide to Flexbox](https://www.joshwcomeau.com/css/interactive-guide-to-flexbox/) / Josh W. Comeau | 第三方作者 | 语言/通用 | 网页、教程、交互 / en | article-specific | 200 |
| [网道 HTML 教程](https://wangdoc.com/html/) / 阮一峰 / 网道 | 第三方作者 | 语言/通用 | 网页、书籍、教程 / zh-CN | chapter-specific | 200 |
| [张鑫旭 CSS 与 Web 原创文章](https://www.zhangxinxu.com/wordpress/category/css/) / 张鑫旭 | 第三方作者 | 语言/通用 | 网页、教程 / zh-CN | article and browser-support specific | 200 |
| [iCSS CSS 奇思妙想](https://github.com/chokcoco/iCSS) / ChokCoco / 国服第一切图仔 | 第三方作者 | 语言/通用 | 仓库、网页、示例/源码、教程 / zh-CN | example and browser-support specific | 200 |
| [CSS Inspiration](https://github.com/chokcoco/CSS-Inspiration) / ChokCoco | 第三方作者 | 语言/通用 | 仓库、示例/源码、交互 / zh-CN | example and browser-support specific | 200 |

## SQL

| 资料与发布者 | 来源 | 生态 | 载体 / 正文语言 | 适用版本 | HTTP |
| --- | --- | --- | --- | --- | --- |
| [freeCodeCamp Curriculum](https://www.freecodecamp.org/learn/) / freeCodeCamp | 第三方作者 | 语言/通用 | 网页、课程、交互、项目 / en | certification edition | 200 |
| [SQLite SQL Language Reference](https://www.sqlite.org/lang.html) / SQLite developers | 项目官方 | sqlite | 网页、参考 / en | rolling SQLite documentation | 200 |
| [SQLite Quirks](https://www.sqlite.org/quirks.html) / SQLite developers | 项目官方 | sqlite | 网页、指南 / en | page-specific | 200 |
| [SQLite Window Functions](https://www.sqlite.org/windowfunctions.html) / SQLite developers | 项目官方 | sqlite | 网页、参考 / en | check minimum SQLite versions | 200 |
| [SQLite Command Line Shell](https://www.sqlite.org/cli.html) / SQLite developers | 项目官方 | sqlite | 网页、参考 / en | CLI-version-specific | 200 |
| [PostgreSQL 15 Documentation](https://www.postgresql.org/docs/15/index.html) / PostgreSQL Global Development Group | 项目官方 | postgresql | 网页、参考 / en | PostgreSQL 15 | 200 |
| [PostgreSQL 15 Tutorial](https://www.postgresql.org/docs/15/tutorial.html) / PostgreSQL Global Development Group | 项目官方 | postgresql | 网页、教程 / en | PostgreSQL 15 | 200 |
| [PostgreSQL 15 Documentation PDF](https://www.postgresql.org/files/documentation/pdf/15/postgresql-15-US.pdf) / PostgreSQL Global Development Group | 项目官方 | postgresql | PDF、参考、书籍 / en | PostgreSQL 15; minor edition may change | 200 |
| [PostgreSQL Current SQL Language Guide](https://www.postgresql.org/docs/current/sql.html) / PostgreSQL Global Development Group | 项目官方 | postgresql | 网页、参考 / en | current alias; not PostgreSQL 15 | 200 |
| [MySQL 8.0 Reference Manual](https://dev.mysql.com/doc/refman/8.0/en/) / Oracle MySQL | 项目官方 | mysql | 网页、参考 / en | MySQL 8.0 | 200 |
| [MySQL 8.0 Tutorial](https://dev.mysql.com/doc/refman/8.0/en/tutorial.html) / Oracle MySQL | 项目官方 | mysql | 网页、教程 / en | MySQL 8.0 | 200 |
| [MySQL 8.4 Reference Manual](https://dev.mysql.com/doc/refman/8.4/en/) / Oracle MySQL | 项目官方 | mysql | 网页、参考 / en | MySQL 8.4; not the installed 8.0 recipe | 200 |
| [MySQL Connector/J Developer Guide](https://dev.mysql.com/doc/connector-j/en/) / Oracle MySQL | 项目官方 | jdbc, mysql | 网页、参考 / en | connector and server version specific | 200 |
| [CS50 Introduction to Databases with SQL](https://cs50.harvard.edu/sql/) / Harvard CS50 | 第三方作者 | sqlite, postgresql, mysql | 网页、课程、视频、练习 / en | course edition; separates its dialect examples | 200 |
| [SQLBolt](https://sqlbolt.com/) / SQLBolt | 第三方作者 | 语言/通用 | 网页、教程、交互、练习 / en | common SQL concepts; verify target dialect | 200 |
| [SQLZoo Tutorial](https://sqlzoo.net/wiki/SQL_Tutorial) / SQLZoo | 第三方作者 | 语言/通用 | 网页、教程、交互、练习 / en | selected exercise database dialect | 200 |
| [PostgreSQL Exercises](https://pgexercises.com/) / Alisdair Owens | 第三方作者 | postgresql | 网页、交互、练习 / en | PostgreSQL exercise schema; inspect function support | 200 |
| [Use The Index, Luke](https://use-the-index-luke.com/) / Markus Winand | 第三方作者 | mysql, postgresql | 网页、书籍 / en | database-specific notes and tested versions | 200 |
| [SQLite Tutorial](https://www.sqlitetutorial.net/) / SQLite Tutorial authors | 第三方作者 | sqlite | 网页、教程 / en | article-specific; not the SQLite project | 200 |
| [MySQL Tutorial](https://www.mysqltutorial.org/) / MySQL Tutorial authors | 第三方作者 | mysql | 网页、教程 / en | article-specific; not Oracle MySQL | 200 |
| [SQL Tutorial by Liao Xuefeng](https://liaoxuefeng.com/books/sql/introduction/index.html) / Liao Xuefeng | 第三方作者 | mysql | 网页、教程、交互 / zh-CN | chapter-specific; older MySQL examples | 200 |
| [dbt Documentation](https://docs.getdbt.com/docs/introduction) / dbt Labs | 项目官方 | dbt | 网页、参考 / en | engine and adapter specific; local Core distinct from paid platform | 200 |
| [SQLFluff Documentation](https://docs.sqlfluff.com/en/stable/) / SQLFluff contributors | 项目官方 | sqlfluff | 网页、参考 / en | stable alias; select dialect and templater | 200 |
| [SQLMesh Documentation](https://sqlmesh.readthedocs.io/en/stable/) / Tobiko / SQLMesh contributors | 项目官方 | sqlmesh | 网页、参考 / en | stable alias; select execution engine | 200 |
| [DuckDB Documentation](https://duckdb.org/docs/stable/) / DuckDB contributors | 项目官方 | duckdb | 网页、参考 / en | stable alias; supplementary material, not a new execution recipe | 200 |
| [PostgreSQL 15 EXPLAIN Guide](https://www.postgresql.org/docs/15/using-explain.html) / PostgreSQL Global Development Group | 项目官方 | postgresql | 网页、参考 / en | PostgreSQL 15 | 200 |
| [MySQL 8.0 Optimization Guide](https://dev.mysql.com/doc/refman/8.0/en/optimization.html) / Oracle MySQL | 项目官方 | mysql | 网页、参考 / en | MySQL 8.0 | 200 |
| [SQLite EXPLAIN QUERY PLAN](https://www.sqlite.org/eqp.html) / SQLite developers | 项目官方 | sqlite | 网页、参考 / en | rolling SQLite documentation | 200 |
| [Wonderful SQL](https://github.com/datawhalechina/wonderful-sql) / Datawhale 作者团队 | 第三方作者 | mysql | 仓库、Markdown、课程、练习 / zh-CN | MySQL 8.0 course; selected exercise dialect matters | 200 |
| [图解 MySQL](https://www.xiaolincoding.com/mysql/) / 小林 coding | 第三方作者 | mysql | 网页、书籍、教程 / zh-CN | article-specific MySQL version | 200 |
| [PostgreSQL 中文手册翻译项目](https://github.com/postgres-cn/pgdoc-cn) / 彭煜玮与 PostgreSQL 中国用户会翻译组 | 社区译文 | postgresql | 仓库、参考、示例/源码 / zh-CN | version-specific SGML sources and release downloads; 15.x and later separated by major | 200 |


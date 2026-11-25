// Public, source-authored UI examples. These are not published business artifacts.
export const presentations = [
  'knowledge_check', 'code_workspace', 'execution_result', 'code_review',
  'sql_workspace', 'demo', 'restricted_preview', 'source_locator',
];
export const brokenCode = 'def total(values):\n    result = 0\n    for value in values:\n        result = value\n    return result';
export const fixedCode = 'def total(values):\n    result = 0\n    for value in values:\n        result += value\n    return result';
export const sampleSql = 'SELECT category, SUM(amount) AS total\nFROM orders\nGROUP BY category\nHAVING SUM(amount) > 100;';
/** @type {Record<string, string>} */
export const projectFiles = {
  'app.py': 'from flask import Flask\n\napp = Flask(__name__)\n\n@app.get("/health")\ndef health():\n    return {"status": "ok"}\n',
  'test_app.py': 'from app import app\n\ndef test_health():\n    response = app.test_client().get("/health")\n    assert response.json == {"status": "ok"}\n',
  'requirements.lock': '# 演示用锁定依赖，不会安装\nFlask==3.1.2\n',
};
export const sampleHtml = '<main class="lesson">\n  <h1>我的第一张学习卡片</h1>\n  <p>内容与样式各司其职。</p>\n  <button type="button">继续学习</button>\n</main>';
export const sampleCss = 'body { margin: 0; padding: 24px; font-family: sans-serif; color: #173d37; background: #f2f7f5; }\n.lesson { max-width: 480px; margin: auto; }\nh1 { font-size: 26px; }\nbutton { border: 0; border-radius: 8px; padding: 10px 18px; color: white; background: #236456; }';

export const checks = [
  { id: 'choice', subtype: 'single', title: '单选：函数返回值', prompt: '函数中没有 return，调用结果是什么？', options: ['0', 'None', '最后打印的内容'], answer: 'None', explanation: '打印不等于返回。没有 return 时，函数返回 None。' },
  { id: 'multiple', subtype: 'multiple', title: '多选：边界条件', prompt: '测试 total(values) 时，哪些输入值得覆盖？', options: ['空列表', '包含负数', '只有一个元素'], answer: ['空列表', '包含负数', '只有一个元素'], explanation: '这三类输入分别覆盖初始化、符号和最小非空规模。' },
  { id: 'prediction', subtype: 'prediction', title: '预测：代码输出', prompt: '下面的代码将打印什么？', code: 'def double(x):\n    print(x * 2)\n\nanswer = double(3)\nprint(answer)', answer: '6\nNone', explanation: '先打印 6；double 没有 return，因此 answer 为 None。' },
  { id: 'ordering', subtype: 'ordering', title: '排序：查询执行顺序', prompt: '将这些查询阶段按学习模型中的先后顺序排列。', options: ['HAVING', 'WHERE', 'GROUP BY'], answer: ['WHERE', 'GROUP BY', 'HAVING'], explanation: '先筛选行，再分组，最后筛选聚合结果。' },
  { id: 'range', subtype: 'range', title: '代码审查：找到累加错误', prompt: '点击有问题的代码行，填写并保存批注，最后统一提交审查。', lines: brokenCode.split('\n'), answer: [4], explanation: '第 4 行应当累加，而不是用当前元素覆盖已有结果。' },
  { id: 'short', subtype: 'short', title: '简答：解释 return', prompt: '用一句话解释 return 和 print 的区别。', answer: '', explanation: '参考：return 把结果交给调用者；print 只负责显示。简答演示仅展示参考讲评，不自动判定你的回答正确。' },
];

function item(id, type, title, conversationId, extra = {}) {
  return { id, revision: 1, state: 'ready', presentation: { type }, title, conversationId, ...extra };
}
export const artifacts = [
  ...checks.map((check) => item(check.id, 'knowledge_check', check.title, 'demo-knowledge-checks', { check })),
  item('sql-check', 'knowledge_check', '分组前还是分组后？', 'demo-sql-review', {
    check: { id: 'sql-check', subtype: 'single', prompt: '筛选总金额超过 100 的分类，应使用什么？', options: ['WHERE SUM(amount) > 100', 'HAVING SUM(amount) > 100'], answer: 'HAVING SUM(amount) > 100', explanation: '聚合值在分组后产生，因此使用 HAVING。' },
  }),
  item('code', 'code_workspace', '计算整数列表的和', 'demo-python-practice'),
  item('result', 'execution_result', '公开样例检查结果', 'demo-python-practice'),
  item('review', 'code_review', '代码评审与修订', 'demo-python-practice'),
  item('sql', 'sql_workspace', '按分类统计订单', 'demo-sql-review'),
  item('animation', 'demo', '观察循环如何累加', 'demo-web-interaction'),
  item('preview', 'restricted_preview', 'HTML / CSS 受限预览', 'demo-web-interaction'),
  item('source', 'source_locator', '来源入口（组件样例）', 'demo-python-learning', {
    previewOnly: true, citation: { documentId: 'demo-python-functions', block: 1 },
  }),
  item('project', 'code_workspace', '受控 Flask 多文件练习', 'demo-project-practice', { project: true }),
];
export const artifactById = new Map(artifacts.map((artifact) => [artifact.id, artifact]));
/** @type {Record<string, string[]>} */
export const messageWidgets = {
  'demo-python-learning-message-2': ['route'],
  'demo-python-learning-message-4': ['update'],
  'demo-python-practice-message-2': ['code'],
  'demo-python-practice-message-4': ['result', 'review'],
  'demo-sql-review-message-2': ['sql-check'],
  'demo-sql-review-message-4': ['sql'],
  'demo-web-interaction-message-2': ['animation'],
  'demo-web-interaction-message-4': ['preview'],
  'demo-project-practice-message-2': ['project'],
  'demo-exam-review-message-2': ['exam'],
  'demo-exam-review-message-4': ['reviewActivity'],
  ...Object.fromEntries(checks.map((check, index) => [`demo-knowledge-checks-message-${index + 2}`, [check.id]])),
};
// Citations accompany message prose, not standalone interaction frames.
/** @type {Record<string, string[]>} */
export const messageReferences = {
  'demo-python-learning-message-4': ['source'],
};
const checkIntroductions = {
  single: '读函数时，要区分屏幕上显示的内容和调用者拿到的值。',
  multiple: '测试不只看常见输入，也要考虑边界情况。',
  prediction: '先自己跟踪一次执行过程，再对照提交后的反馈。',
  ordering: '理解查询过程，有助于判断每个条件应放在哪个阶段。',
  range: '审查代码不仅要指出位置，也要说明为什么有问题。',
  short: '尝试用自己的话解释概念，而不是复述术语。',
};
export const extraConversations = [
  {
    id: 'demo-knowledge-checks', title: '知识检查：六种作答方式', minute: 30,
    entries: [
      ['user', '我想试试不同形式的知识检查。'],
      ...checks.map((check) => ['tutor', checkIntroductions[check.subtype]]),
    ],
  },
  {
    id: 'demo-web-interaction', title: '网页交互：演示与受限预览', minute: 40,
    entries: [
      ['user', '先演示循环的变化，再让我试着修改网页样式。'],
      ['tutor', '### 观察每一步发生了什么\n\n可以逐步观察，也可以播放。完成观看不会记为独立掌握。'],
      ['user', '网页的内容和样式也能在这里修改吗？'],
      ['tutor', '### 在对话里修改 HTML 和 CSS\n\n预览是无脚本、无网络的隔离内容，不是正式运行或评分。'],
    ],
  },
  {
    id: 'demo-project-practice', title: '框架练习：多文件与环境授权', minute: 45,
    entries: [
      ['user', '我想做一个有测试的 Flask 小项目。'],
      ['tutor', '### 一个受控的健康检查接口\n\n允许修改 app.py，测试与依赖清单只读。先查看环境范围，再决定是否准备。'],
      ['user', '卡住时，我想看看提示、答案和答疑是什么样子。'],
      ['tutor', '### 辅助不隐藏，主线不丢失\n\n在上方工作台的“提示答疑”标签页查看提示、答案和答疑；辅助记录会留在当前演示里。'],
    ],
  },
  {
    id: 'demo-exam-review', title: '学习收尾：考试、复习与记录', minute: 50,
    entries: [
      ['user', '我准备做一次正式考试，再看看复习安排。'],
      ['tutor', '### 明确开考，再整组提交\n\n这里演示开考确认和一次提交，不提供考试内试跑或提示。'],
      ['user', '复习和我的学习记录在哪里？'],
      ['tutor', '### 从当前学习继续\n\n复习、自评与独立评测是不同记录。也可从顶部学习菜单直接查看。'],
    ],
  },
];

/** @type {Record<string, {title: string, version: number, section: string, blocks: string[]}>} */
export const readingDocuments = {
  'demo-python-functions': {
    title: 'Python 函数与边界条件', version: 1, section: '§2 返回值与累加',
    blocks: [
      '本文是本地编写的公开演示材料，不是实际导入或审核结果。',
      'return 将结果交给调用者；print 将内容显示到输出。',
      '累加必须保留之前的结果。result += value 等价于 result = result + value。',
      '空列表的和为 0，因此累加器从 0 开始。',
    ],
  },
  'demo-sql-grouping': {
    title: 'SQL 分组与聚合', version: 1, section: '§1 分组后的筛选',
    blocks: [
      '本文是公开演示材料，不连接任何数据库。',
      'WHERE 在分组前筛选行；HAVING 在分组后筛选聚合结果。',
      '按 category 分组后，可以使用 HAVING SUM(amount) > 100 筛选组。',
    ],
  },
};

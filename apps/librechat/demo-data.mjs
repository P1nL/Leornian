import { extraConversations, messageWidgets } from './learning-demo-data.mjs';
// Static display data only. No Leornian identities, Attempts, or model receipts.
const noParent = '00000000-0000-0000-0000-000000000000';
const owner = 'librechat-ui-preview';
const at = (minute) => `2026-11-03T02:${String(minute).padStart(2, '0')}:00.000Z`;
const demonstration = '> 只读演示数据：交互只影响当前标签页，未调用模型、运行代码或写入学习记录。\n\n';

const materials = [
  {
    id: 'demo-python-functions',
    filename: 'Python 函数与边界条件 · 演示.md',
    text: [
      '# Python 函数与边界条件',
      '',
      '> 本文为本地编写的演示材料，不是实际导入、解析或审核结果。',
      '',
      '函数把输入转换为输出。先明确参数和返回值，再考虑边界情况。',
      '',
      '```python',
      'def total(values):',
      '    result = 0',
      '    for value in values:',
      '        result += value',
      '    return result',
      '```',
      '',
      '检查空列表、单个元素以及包含负数的列表。空列表的和为 0。',
    ].join('\n'),
  },
  {
    id: 'demo-sql-grouping',
    filename: 'SQL 分组与聚合 · 演示.md',
    text: [
      '# SQL 分组与聚合',
      '',
      '> 本文为本地编写的演示材料，不连接任何数据库。',
      '',
      '`WHERE` 在分组前筛选行，`HAVING` 在分组后筛选聚合结果。',
      '',
      '```sql',
      'SELECT category, SUM(amount) AS total',
      'FROM orders',
      'GROUP BY category',
      'HAVING SUM(amount) > 100;',
      '```',
    ].join('\n'),
  },
];

export const demoMaterials = new Map(materials.map((material) => [material.id, material]));
export const demoFiles = materials.map(({ id, filename, text }) => ({
  user: owner,
  file_id: id,
  bytes: Buffer.byteLength(text, 'utf8'),
  embedded: false,
  filename,
  filepath: `/__preview/materials/${id}`,
  object: 'file',
  type: 'text/markdown',
  usage: 0,
  context: 'message_attachment',
  source: 'local',
  text,
  textFormat: 'text',
  createdAt: at(0),
  updatedAt: at(0),
}));

function transcript(id, title, entries, minute) {
  const intros = {
    'demo-python-learning-message-2': '## 从一个能用的小工具开始\n\n先确认路线，再开始函数与返回值。下面可以展开版本、提出修改要求并体验确认。',
    'demo-python-practice-message-2': '## 在对话里编辑和检查\n\n下面保留错误版和修正版两份公开样例。自定义代码可编辑，但本演示不会运行它。',
    'demo-python-practice-message-4': '## 结果与代码评审\n\n结果会跟随上方样例操作变化。对照代码行旁的评审反馈，可将修订示例放回编辑器。',
    'demo-sql-review-message-2': '## 先判断筛选发生在哪个阶段\n\n请在消息内选择并明确提交这次演示回答。',
    'demo-sql-review-message-4': '## 在同一处编辑 SQL、看 Schema 和结果\n\n下面展示三个独立方言的选择，结果仅来自固定公开样例。',
  };
  const messages = entries.map(([role, text, fileIds = []], index) => ({
    conversationId: id,
    messageId: `${id}-message-${index + 1}`,
    parentMessageId: index === 0 ? noParent : `${id}-message-${index}`,
    sender: role === 'user' ? '学习者（演示）' : 'Tutor · 演示',
    isCreatedByUser: role === 'user',
    endpoint: 'openAI',
    model: 'readonly-demo',
    text: role === 'user' ? text : demonstration + (intros[`${id}-message-${index + 1}`] ?? text),
    error: false,
    unfinished: false,
    finish_reason: 'stop',
    createdAt: at(minute + index),
    updatedAt: at(minute + index),
    ...(fileIds.length ? { files: demoFiles.filter((file) => fileIds.includes(file.file_id)) } : {}),
  }));
  return {
    conversation: {
      conversationId: id,
      title: `演示 · ${title}`,
      user: owner,
      endpoint: 'openAI',
      model: 'readonly-demo',
      modelLabel: 'Tutor · 只读演示',
      messages: messages.map(({ messageId }) => messageId),
      isArchived: false,
      pinned: false,
      createdAt: messages[0].createdAt,
      updatedAt: messages.at(-1).updatedAt,
    },
    messages,
  };
}

const examples = [
  transcript('demo-python-learning', 'Python 入门：路线与第一课', [
    ['user', '我想用 Python 自动整理文件，有一点编程基础，每天可以学半小时。先从函数开始。'],
    ['tutor', [
      '## 从一个能用的小工具开始',
      '',
      '先把基础知识串成一条短路线，再用“文件分类器”练习。这里展示的是路线在对话中的样子，不需要另开学习管理页。',
      '',
      '| 学习步骤 | 学完能做什么 |',
      '| --- | --- |',
      '| 函数与返回值 | 把一个小任务封装成函数 |',
      '| 列表与循环 | 批量处理一组数据 |',
      '| 路径与文件 | 读取路径、按扩展名分类 |',
      '| 综合练习 | 完成一个受控的文件分类任务 |',
      '',
      '**当前学习：函数与返回值。** 正式接入后，路线确认按钮会出现在这段内容附近；本演示不执行确认。',
    ].join('\n')],
    ['user', '可以。这里有一份材料，先解释 return 和 print 的区别。', ['demo-python-functions']],
    ['tutor', [
      '## `return` 把结果交给调用者',
      '',
      '`print` 负责显示；`return` 负责让后续代码拿到结果。',
      '',
      '```python',
      'def double(value):',
      '    return value * 2',
      '',
      'answer = double(3)',
      'print(answer)  # 6',
      '```',
      '',
      '这里 `double(3)` 的结果被保存在 `answer` 中。如果函数只打印 `6` 而没有返回值，调用者拿到的会是 `None`。',
      '',
      '**想一想：** 如果删掉 `return`，只保留 `print(value * 2)`，`answer` 会是什么？',
    ].join('\n')],
  ], 0),
  transcript('demo-python-practice', 'Python 练习：代码与反馈', [
    ['user', '给我一道列表与函数的小练习，我想看看练习和结果放在聊天里是什么样子。'],
    ['tutor', [
      '## 练习：计算列表中所有整数的和',
      '',
      '编写 `total(values)`，返回列表的和。空列表应返回 `0`。',
      '',
      '```python',
      'def total(values):',
      '    result = 0',
      '    for value in values:',
      '        result += value',
      '    return result',
      '```',
      '',
      '正式接入时，这里会使用对话内的编辑器和“运行并检查”；当前只是只读代码展示。',
    ].join('\n')],
    ['user', '如果我提交这份代码，反馈会怎样展示？'],
    ['tutor', [
      '## 检查反馈的展示样例',
      '',
      '**这是结果排版，不是实际执行或评分回执。**',
      '',
      '| 公开检查样例 | 输入 | 预期结果 |',
      '| --- | --- | --- |',
      '| 普通列表 | `[1, 2, 3]` | `6` |',
      '| 空列表 | `[]` | `0` |',
      '| 含负数 | `[-2, 5]` | `3` |',
      '',
      '### 接下来怎么学',
      '',
      '可以先解释为什么 `result` 从 `0` 开始，再尝试改写为“只累加正数”。实际通过与否、是否使用提示，都由正式评分链记录，不从这段演示文字推算。',
      '',
      '你会在同一个对话里看到题目、代码、结果和讲评，不必在多个页面之间切换。',
    ].join('\n')],
  ], 10),
  transcript('demo-sql-review', 'SQL 复习：材料与知识检查', [
    ['user', '帮我回顾 WHERE 和 HAVING 的区别。', ['demo-sql-grouping']],
    ['tutor', [
      '## 一个问题回顾分组顺序',
      '',
      '假设要找出“总金额超过 100 的分类”，应使用哪一个条件？',
      '',
      '**A.** `WHERE SUM(amount) > 100`  ',
      '**B.** `HAVING SUM(amount) > 100`',
      '',
      '这是知识检查的只读题面。正式接入后，选项和“提交回答”会直接出现在对话内。',
    ].join('\n')],
    ['user', '我选 B，因为要先分组求和，再筛选各组。'],
    ['tutor', [
      '## 把筛选放在正确的阶段',
      '',
      '这段示例回答对应分组后的筛选：',
      '',
      '```sql',
      'SELECT category, SUM(amount) AS total',
      'FROM orders',
      'GROUP BY category',
      'HAVING SUM(amount) > 100;',
      '```',
      '',
      '- `WHERE`：先筛选输入行，再参与分组。',
      '- `HAVING`：计算各组的聚合值后，再筛选组。',
      '',
      '复习安排、真实作答证据和后续提醒均未在本演示中创建。材料 **SQL 分组与聚合 · 演示.md** 可在“我的文件”中查看。',
    ].join('\n')],
  ], 20),
  ...extraConversations.map((example) => transcript(example.id, example.title, example.entries, example.minute)),
];

export const demoConversations = examples.map(({ conversation }) => conversation);
export const demoTranscripts = new Map(examples.map((example) => [
  example.conversation.conversationId, example,
]));

export function listDemoConversations(params) {
  let conversations = [...demoConversations];
  if (params.get('isArchived') === 'true' || params.has('cursor')) conversations = [];
  if (params.get('pinned') === 'true') conversations = conversations.filter((item) => item.pinned);
  const project = params.get('projectId');
  if (project && project !== 'unassigned') conversations = [];
  const search = params.get('search')?.trim().toLocaleLowerCase();
  if (search) conversations = conversations.filter((item) =>
    `${item.title}\n${demoTranscripts.get(item.conversationId).messages.map((message) => message.text).join('\n')}`.toLocaleLowerCase().includes(search));
  conversations.sort((a, b) => b.updatedAt.localeCompare(a.updatedAt));
  return { conversations, nextCursor: null };
}

for (const messageId of Object.keys(messageWidgets)) {
  if (!examples.some((example) => example.messages.some((message) => message.messageId === messageId))) {
    throw new Error(`Demo widget has no corresponding message: ${messageId}`);
  }
}

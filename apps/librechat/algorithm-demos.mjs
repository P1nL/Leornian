// Deterministic teaching traces, not an evaluator for learner-supplied code.
function recorder() {
  const steps = [];
  return { steps, add: (line, note, variables, scene) => steps.push(structuredClone({ line, note, variables, scene })) };
}

export function binarySearchDemo(target = 11, values = [2, 5, 8, 11, 14, 17, 20]) {
  const trace = recorder();
  let left = 0, right = values.length - 1;
  const scene = (mid = null, found = false) => ({
    items: values.map((value, i) => ({ id: String(i), value, tone: i < left || i > right ? 'muted' : i === mid ? found ? 'done' : 'active' : 'idle' })),
    pointers: [{ label: 'left', index: left }, { label: 'right', index: right }, ...(mid === null ? [] : [{ label: 'mid', index: mid }])],
  });
  trace.add(1, `在有序数组中查找 ${target}。`, { target, left, right }, scene());
  while (left <= right) {
    const mid = Math.floor((left + right) / 2);
    trace.add(3, `检查下标 ${mid}，当前值为 ${values[mid]}。`, { target, left, mid, right }, scene(mid));
    if (values[mid] === target) {
      trace.add(4, `找到 ${target}，返回下标 ${mid}。`, { target, index: mid }, scene(mid, true));
      return { title: '二分查找', code: binaryCode, steps: trace.steps };
    }
    if (values[mid] < target) {
      left = mid + 1;
      trace.add(5, `${values[mid]} 小于目标，排除左半区间。`, { target, left, right }, scene());
    } else {
      right = mid - 1;
      trace.add(6, `${values[mid]} 大于目标，排除右半区间。`, { target, left, right }, scene());
    }
  }
  trace.add(7, '搜索区间为空，返回 -1。', { target, index: -1 }, { ...scene(), pointers: [] });
  return { title: '二分查找', code: binaryCode, steps: trace.steps };
}
const binaryCode = [
  'left, right = 0, len(a) - 1',
  'while left <= right:',
  '    mid = (left + right) // 2',
  '    if a[mid] == target: return mid',
  '    if a[mid] < target: left = mid + 1',
  '    else: right = mid - 1',
  'return -1',
];

export function bracketDemo(text = '([])') {
  const trace = recorder();
  const stack = [];
  const pairs = { ')': '(', ']': '[', '}': '{' };
  const scene = (cursor, invalid = false) => ({
    input: [...text].map((value, i) => ({ id: `input-${i}`, value, tone: i === cursor ? invalid ? 'rejected' : 'active' : i < cursor ? 'done' : 'idle' })),
    items: stack.map((item, i) => ({ ...item, tone: i === stack.length - 1 ? 'active' : 'idle' })),
    mode: 'stack',
  });
  const code = [
    'stack = []', 'for ch in text:',
    '    if ch in "([{": stack.append(ch)',
    '    elif not stack or stack[-1] != pairs[ch]:',
    '        return False',
    '    else: stack.pop()', 'return not stack',
  ];
  trace.add(1, '从左到右扫描，左括号入栈。', { input: text, size: 0 }, scene(-1));
  for (let i = 0; i < text.length; i++) {
    const ch = text[i];
    trace.add(2, `读取 ${ch}。`, { ch, size: stack.length }, scene(i));
    if ('([{'.includes(ch)) {
      stack.push({ id: `bracket-${i}`, value: ch });
      trace.add(3, `${ch} 入栈，成为新的栈顶。`, { ch, size: stack.length }, scene(i));
    } else if (!stack.length || stack.at(-1).value !== pairs[ch]) {
      trace.add(5, `${ch} 与栈顶不匹配，提前结束。`, { valid: 'False', size: stack.length }, scene(i, true));
      return { title: '栈 · 括号匹配', code, steps: trace.steps };
    } else {
      stack.pop();
      trace.add(6, '匹配成功，弹出栈顶的左括号。', { ch, size: stack.length }, scene(i));
    }
  }
  trace.add(7, stack.length ? '扫描结束，仍有未闭合的括号。' : '扫描结束，栈为空，所有括号匹配。',
    { valid: stack.length ? 'False' : 'True', size: stack.length }, scene(text.length));
  return { title: '栈 · 括号匹配', code, steps: trace.steps };
}

export function breadthFirstDemo(input) {
  const trace = recorder();
  const nodes = input ? input.nodes.map((id, index) => ({
    id, x: 240 + Math.cos(2 * Math.PI * index / input.nodes.length - Math.PI / 2) * 180,
    y: 140 + Math.sin(2 * Math.PI * index / input.nodes.length - Math.PI / 2) * 105,
  })) : [
    { id: 'A', x: 65, y: 140 }, { id: 'B', x: 230, y: 65 }, { id: 'C', x: 230, y: 215 },
    { id: 'D', x: 410, y: 65 }, { id: 'E', x: 410, y: 215 },
  ];
  const edges = input ? input.edges.map(({ source, target }) => [source, target])
    : [['A', 'B'], ['A', 'C'], ['B', 'D'], ['C', 'D'], ['C', 'E']];
  const start = input?.start ?? 'A';
  const queue = [start], discovered = new Set(queue), visited = [];
  const scene = (current = '', edge = '') => ({
    nodes: nodes.map((node) => ({ ...node, label: node.id, tone: current === node.id ? 'active' : visited.includes(node.id) ? 'done' : discovered.has(node.id) ? 'queued' : 'idle' })),
    edges: edges.map(([from, to]) => ({ from, to, tone: `${from}-${to}` === edge ? 'active' : 'idle' })),
    queue: queue.map((value) => ({ id: value, value, tone: 'queued' })),
  });
  trace.add(1, `将 ${start} 加入队列，并立即标记为已发现。`, { queue: start, visited: '空' }, scene());
  while (queue.length) {
    const current = queue.shift();
    visited.push(current);
    trace.add(3, `${current} 从队首出队。`, { current, visited: visited.join(' → ') }, scene(current));
    for (const [, next] of edges.filter(([from]) => from === current)) {
      if (discovered.has(next)) {
        trace.add(5, `${next} 已被发现，不重复入队。`, { current, neighbor: next }, scene(current, `${current}-${next}`));
      } else {
        discovered.add(next); queue.push(next);
        trace.add(6, `发现 ${next}，加入队尾。`, { current, neighbor: next }, scene(current, `${current}-${next}`));
      }
    }
  }
  trace.add(7, '队列为空，遍历结束。', { order: visited.join(' → ') }, scene());
  return { title: '图 · 广度优先遍历', steps: trace.steps, code: [
    'queue, seen, visit_order = [start], {start}, []', 'while queue:', '    node = queue.pop(0); visit_order.append(node)',
    '    for next in neighbors[node]:', '        if next in seen: continue',
    '        seen.add(next); queue.append(next)', 'return visit_order',
  ] };
}

export function gridPathsDemo(input) {
  const trace = recorder();
  const rows = input?.rows ?? 3, columns = input?.columns ?? 4;
  const blocked = new Set(input ? input.blocked.map(({ row, column }) => `${row}-${column}`) : ['1-1']);
  const dp = Array.from({ length: rows }, () => Array(columns).fill(null));
  const scene = (r = -1, c = -1) => ({
    columnLabels: Array.from({ length: columns }, (_, i) => String(i)),
    rowLabels: Array.from({ length: rows }, (_, i) => String(i)),
    cells: dp.map((row, y) => row.map((value, x) => ({
      id: `${y}-${x}`, value: blocked.has(`${y}-${x}`) ? '×' : value ?? '·',
      tone: blocked.has(`${y}-${x}`) ? 'rejected' : y === r && x === c ? 'active'
        : (y === r - 1 && x === c) || (y === r && x === c - 1) ? 'queued' : value !== null ? 'done' : 'idle',
    }))),
  });
  trace.add(1, '从左上角到右下角，只能向右或向下；× 为障碍。', { rows, columns }, scene());
  for (let r = 0; r < rows; r++) for (let c = 0; c < columns; c++) {
    if (blocked.has(`${r}-${c}`)) dp[r][c] = 0;
    else if (r === 0 && c === 0) dp[r][c] = 1;
    else dp[r][c] = (r > 0 ? dp[r - 1][c] : 0) + (c > 0 ? dp[r][c - 1] : 0);
    const obstacle = blocked.has(`${r}-${c}`);
    trace.add(obstacle ? 3 : r === 0 && c === 0 ? 4 : 5,
      obstacle ? '障碍格的路径数为 0。' : r === 0 && c === 0 ? '起点有 1 种到达方式。' : '当前格的路径数 = 上方路径数 + 左侧路径数。',
      { row: r, col: c, paths: dp[r][c] }, scene(r, c));
  }
  trace.add(6, `终点共有 ${dp[rows - 1][columns - 1]} 条路径。`, { paths: dp[rows - 1][columns - 1] }, scene());
  return { title: '网格 · 动态规划路径计数', steps: trace.steps, code: [
    'dp = zeros(rows, cols)', 'for r, c in row_major_order:',
    '    if blocked[r][c]: dp[r][c] = 0', '    elif r == c == 0: dp[r][c] = 1',
    '    else: dp[r][c] = up(r, c) + left(r, c)', 'return dp[-1][-1]',
  ] };
}

export function backtrackingDemo(input) {
  const trace = recorder(), calls = [], stack = [], solutions = [];
  const values = input?.values ?? [1, 2, 3], target = input?.target ?? 4;
  const scene = () => ({ calls, stack: [...stack] });
  const visit = (start, path, sum) => {
    const call = { id: `call-${calls.length}`, label: `[${path.join(', ')}] = ${sum}`, depth: path.length, tone: 'active' };
    calls.push(call); stack.push(call.label);
    trace.add(1, `进入分支 [${path.join(', ')}]。`, { sum, target, solutions: solutions.length }, scene());
    if (sum === target) {
      solutions.push([...path]); call.tone = 'done';
      trace.add(2, '达到目标，记录答案，返回上一层。', { solution: path.join(' + '), sum }, scene());
    } else if (sum > target) {
      call.tone = 'rejected';
      trace.add(3, '总和超过目标；所有候选数都为正，剪去这个分支。', { sum, target }, scene());
    } else {
      for (let i = start; i < values.length; i++) {
        call.tone = 'queued';
        visit(i + 1, [...path, values[i]], sum + values[i]);
        call.tone = 'active';
        trace.add(6, `撤回 ${values[i]}，回到 [${path.join(', ')}]。`, { sum, next: i + 1 }, scene());
      }
      call.tone = 'muted';
    }
    stack.pop();
  };
  visit(0, [], 0);
  trace.add(7, `搜索完成，找到 ${solutions.length} 个按输入位置选择的组合。`,
    { solutions: solutions.length, combinations: JSON.stringify(solutions) }, scene());
  return { title: '回溯 · 组合求和', steps: trace.steps, code: [
    'search(start, path, total):', '    if total == target: save(path); return',
    '    if total > target: return', '    for i in range(start, len(a)):',
    '        search(i + 1, path + [a[i]], total + a[i])',
    '        # return to the current path', 'search(0, [], 0)',
  ] };
}

export function intervalDemo(input) {
  const trace = recorder();
  const intervals = (input?.intervals ?? [
    { id: 'A', start: 1, end: 3 }, { id: 'B', start: 2, end: 5 },
    { id: 'C', start: 4, end: 6 }, { id: 'D', start: 6, end: 8 }, { id: 'E', start: 7, end: 9 },
  ]).map((item) => ({ ...item, tone: 'idle' })).sort((a, b) => a.end - b.end || a.start - b.start);
  let end = -Infinity;
  const selected = [];
  const minimum = Math.min(0, ...intervals.map((item) => item.start));
  const max = Math.max(1, ...intervals.map((item) => item.end), input ? 1 : 10);
  const scene = () => ({ intervals, cursor: Number.isFinite(end) ? end : minimum, max, minimum });
  trace.add(1, '按结束时间排序。端点相接允许连续参加。', { end: '−∞', selected: '空' }, scene());
  for (const item of intervals) {
    item.tone = 'active';
    trace.add(2, `检查活动 ${item.id}：${item.start}–${item.end}。`,
      { start: item.start, lastEnd: Number.isFinite(end) ? end : '−∞' }, scene());
    if (item.start >= end) {
      item.tone = 'done'; selected.push(item.id); end = item.end;
      trace.add(4, `选择 ${item.id}，更新已选活动的结束时间。`, { end, selected: selected.join(', ') }, scene());
    } else {
      item.tone = 'rejected';
      trace.add(5, `${item.id} 与已选活动冲突，跳过。`, { end, selected: selected.join(', ') }, scene());
    }
  }
  trace.add(6, `可以参加 ${selected.length} 个互不冲突的活动。`, { count: selected.length, selected: selected.join(', ') }, scene());
  return { title: '区间 · 贪心活动选择', steps: trace.steps, code: [
    'activities.sort(key=lambda a: a.end)', 'for activity in activities:',
    '    if activity.start >= last_end:', '        choose(activity); last_end = activity.end',
    '    else: skip(activity)', 'return chosen',
  ] };
}

export function bitwiseDemo({ left, right, operation, width }) {
  const trace = recorder();
  const symbol = { and: '&', or: '|', xor: '^' }[operation];
  const result = operation === 'and' ? left & right : operation === 'or' ? left | right : left ^ right;
  const rows = [{ label: 'left', value: left }, { label: 'right', value: right }];
  const code = [`result = left ${symbol} right`, 'return result'];
  trace.add(1, `对齐 ${width} 位的两个操作数。`, { left, right, operation },
    { rows, width });
  trace.add(1, `逐位执行 ${symbol}，互不借位或进位。`, { left, right, result },
    { rows: [...rows, { label: `left ${symbol} right`, value: result }], width });
  trace.add(2, `结果为 ${result}。`, { result },
    { rows: [{ label: 'result', value: result }], width });
  return { title: '位运算', code, steps: trace.steps };
}

export function orientationDemo({ points }) {
  const trace = recorder();
  const [a, b, c] = points;
  const cross = (b.x - a.x) * (c.y - a.y) - (b.y - a.y) * (c.x - a.x);
  const minimum = Math.min(0, ...points.flatMap((p) => [p.x, p.y]));
  const extent = Math.max(1, ...points.flatMap((p) => [p.x, p.y]));
  const links = [{ from: a.id, to: b.id }, { from: a.id, to: c.id }];
  const scene = (edges) => ({ points, links: edges, minimum, extent });
  trace.add(1, `比较 ${a.id}→${b.id} 与 ${a.id}→${c.id} 的方向。`, {},
    scene([]));
  trace.add(2, '从同一起点构造两个向量。',
    { ux: b.x - a.x, uy: b.y - a.y, vx: c.x - a.x, vy: c.y - a.y }, scene(links));
  trace.add(3, `叉积为 ${cross}：${cross > 0 ? '逆时针' : cross < 0 ? '顺时针' : '共线'}。`,
    { cross, orientation: cross > 0 ? 'counterclockwise' : cross < 0 ? 'clockwise' : 'collinear' }, scene(links));
  return { title: '几何 · 三点方向', code: [
    'a, b, c = points',
    'u, v = b - a, c - a',
    'cross = u.x * v.y - u.y * v.x',
  ], steps: trace.steps };
}

export function compositionAlgorithm(input, values) {
  switch (input.type) {
    case 'binary_search': return binarySearchDemo(values[input.target_state], input.values);
    case 'brackets': return bracketDemo(input.text);
    case 'bfs': return breadthFirstDemo(input);
    case 'grid_paths': return gridPathsDemo(input);
    case 'combination_sum': return backtrackingDemo(input);
    case 'interval_scan': return intervalDemo(input);
    case 'bitwise': return bitwiseDemo(input);
    case 'geometry': return orientationDemo(input);
    default: throw new Error('Unsupported algorithm input.');
  }
}

export function bitCountDemo() {
  const trace = recorder();
  let n = 13, count = 0;
  const scene = (previous = n, minus = null, result = null) => ({
    width: 8, rows: [
      { label: 'n', value: previous },
      ...(minus === null ? [] : [{ label: 'n - 1', value: minus }, { label: 'n & (n - 1)', value: result }]),
    ],
  });
  trace.add(1, '统计 13 的二进制表示中有多少个 1。', { n, count }, scene());
  while (n) {
    const previous = n;
    n &= n - 1;
    trace.add(3, '与 n - 1 按位与，清除最低位的 1。', { before: previous, after: n, count }, scene(previous, previous - 1, n));
    count++;
    trace.add(4, '清除了一个 1，计数加一。', { n, count }, scene());
  }
  trace.add(5, `n 已归零，共有 ${count} 个 1。`, { n, count }, scene());
  return { title: '位运算 · 统计置位数', steps: trace.steps, code: [
    'count = 0', 'while n:', '    n = n & (n - 1)', '    count += 1', 'return count',
  ] };
}

export function closestPairDemo() {
  const trace = recorder();
  const points = [
    { id: 'A', x: 1, y: 1 }, { id: 'B', x: 3, y: 4 }, { id: 'C', x: 4, y: 4 }, { id: 'D', x: 7, y: 2 },
  ];
  let best = Infinity, pair = [];
  const scene = (candidate = []) => ({
    points, extent: 8,
    links: [
      ...(pair.length ? [{ from: pair[0], to: pair[1], tone: 'done' }] : []),
      ...(candidate.length ? [{ from: candidate[0], to: candidate[1], tone: 'active' }] : []),
    ],
  });
  trace.add(1, '逐对比较欧氏距离，保留目前最近的一对点。', { best: '∞' }, scene());
  for (let i = 0; i < points.length; i++) for (let j = i + 1; j < points.length; j++) {
    const a = points[i], b = points[j];
    const distance = Math.hypot(a.x - b.x, a.y - b.y);
    trace.add(3, `测量 ${a.id} 与 ${b.id} 的距离。`, { pair: `${a.id}–${b.id}`, distance: distance.toFixed(2), best: Number.isFinite(best) ? best.toFixed(2) : '∞' }, scene([a.id, b.id]));
    if (distance < best) {
      best = distance; pair = [a.id, b.id];
      trace.add(4, '发现更近的一对，更新最短距离。', { pair: pair.join('–'), best: best.toFixed(2) }, scene());
    }
  }
  trace.add(5, `最近点对为 ${pair.join('、')}，距离为 ${best}。`, { pair: pair.join('–'), distance: best }, scene());
  return { title: '几何 · 最近点对（穷举）', steps: trace.steps, code: [
    'best = infinity', 'for a, b in all_pairs(points):',
    '    d = hypot(a.x - b.x, a.y - b.y)',
    '    if d < best: best, pair = d, (a, b)', 'return pair, best',
  ] };
}

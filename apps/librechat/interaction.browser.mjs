// Repeatable UI acceptance; pass a fresh Playwright page from a runner with workspace access.
import { checks, fixedCode } from './learning-demo-data.mjs';
import { demoStorageKey } from './demo-state.mjs';

export async function verifyInteractionDemo(page, group = 'learning') {
  page.setDefaultTimeout(10000);
  const origin = 'http://127.0.0.1:5180';
  const results = [];
  const errors = [];
  const requests = [];
  page.on('pageerror', (error) => errors.push(error.message));
  page.on('console', (message) => { if (message.type() === 'error') errors.push(message.text()); });
  page.on('request', (request) => {
    if (/^https?:/.test(request.url()) &&
      (!request.url().startsWith(`${origin}/`) || !['GET', 'HEAD'].includes(request.method()) && !request.url().endsWith('/api/auth/refresh'))) {
      requests.push(`${request.method()} ${request.url()}`);
    }
  });
  const check = (value, message) => { if (!value) throw new Error(message); };
  const state = () => page.evaluate((key) => JSON.parse(sessionStorage.getItem(key) ?? '{}'), demoStorageKey);
  const waitState = (path, value) => page.waitForFunction(({ key, path, value }) => {
    const stored = JSON.parse(sessionStorage.getItem(key) ?? '{}');
    return path.split('.').reduce((result, part) => result?.[part], stored) === value;
  }, { key: demoStorageKey, path, value });
  const go = async (id) => {
    await page.goto(`${origin}/c/${id}`, { waitUntil: 'domcontentloaded' });
    await page.getByRole('textbox', { name: '学习目标或问题（演示）', exact: true }).waitFor();
  };
  const top = () => page.locator('main').evaluate((root) => {
    root.querySelectorAll('*').forEach((element) => {
      if (element.scrollHeight > element.clientHeight && ['auto', 'scroll'].includes(getComputedStyle(element).overflowY)) element.scrollTop = 0;
    });
  });
  const perform = async (name, operation) => {
    try { await operation(); results.push({ name, passed: true }); }
    catch (error) { results.push({ name, passed: false, error: error.message.split('\n').slice(0, 4).join(' ') }); }
  };
  const settings = async (tab) => {
    await page.getByTestId('nav-user').click();
    await page.getByTestId('nav-settings').click();
    await page.getByRole('tab', { name: tab, exact: true }).click();
  };
  await page.setViewportSize({ width: 1440, height: 1000 });

  if (group === 'learning') {
    await perform('new-chat goal intake and route confirmation', async () => {
      await go('new');
      const composer = page.getByRole('textbox', { name: '学习目标或问题（演示）', exact: true });
      await composer.fill('我想用 Python 整理文件');
      await page.getByRole('button', { name: '发送演示输入' }).click();
      await composer.fill('有一点编程基础');
      await page.getByRole('button', { name: '发送演示输入' }).click();
      await page.getByRole('button', { name: '打开 Python 示范路线', exact: true }).click();
      const route = page.locator('[data-artifact-id="route"]');
      await route.getByRole('textbox', { name: '路线修改要求' }).fill('先讲边界条件');
      await route.getByRole('button', { name: '保存修改要求（演示）' }).click();
      await route.getByRole('button', { name: '确认这份路线（演示）' }).click();
      check((await state()).route.confirmed, 'route did not confirm');
      await page.getByRole('button', { name: '阅读并定位引用' }).click();
      await page.getByRole('complementary', { name: '教材阅读面板' }).waitFor();
      check(await page.locator('mark').innerText() !== '', 'precise block not highlighted');
      await page.screenshot({ path: 'D:/works/Leornian/.local/librechat-interactions-desktop.png' });
      await page.getByRole('button', { name: '关闭教材阅读' }).click();
    });
    for (const definition of checks) {
      await perform(`knowledge check: ${definition.subtype}`, async () => {
        await go('demo-knowledge-checks');
        await top();
        const artifact = page.locator(`[data-artifact-id="${definition.id}"]`);
        await artifact.waitFor();
        if (definition.subtype === 'single') await artifact.getByRole('radio', { name: 'None', exact: true }).check();
        if (definition.subtype === 'multiple') for (const label of definition.options) await artifact.getByRole('checkbox', { name: label, exact: true }).check();
        if (definition.subtype === 'prediction') await artifact.getByRole('textbox').fill('6\nNone');
        if (definition.subtype === 'short') await artifact.getByRole('textbox').fill('return 返回结果，print 显示内容。');
        if (definition.subtype === 'range') {
          await artifact.getByRole('button', { name: /^第 4 行：/ }).click();
          await artifact.getByRole('textbox', { name: '第 4 行的理由' }).fill('赋值覆盖了之前的累加结果，应当使用 +=。');
          await artifact.getByRole('button', { name: '保存第 4 行批注' }).click();
        }
        if (definition.subtype === 'ordering') {
          await artifact.getByRole('button', { name: 'WHERE上移', exact: true }).click();
          await artifact.getByRole('button', { name: 'GROUP BY上移', exact: true }).click();
        }
        await artifact.getByRole('button', { name: definition.subtype === 'range' ? '提交审查' : '提交演示回答' }).click();
        check((await state()).artifacts[definition.id].submitted, 'response not retained');
      });
    }
    await perform('code edit, result, assistance, review and refresh', async () => {
      await go('demo-python-practice');
      await top();
      const artifact = page.locator('[data-artifact-id="code"]');
      await artifact.getByRole('button', { name: '运行并检查（演示）' }).click();
      await waitState('artifacts.code.state', 'active');
      await artifact.getByRole('button', { name: '载入修正版' }).click();
      await artifact.getByRole('button', { name: '运行并检查（演示）' }).click();
      await waitState('artifacts.code.state', 'completed');
      await artifact.getByRole('tab', { name: '提示答疑', exact: true }).click();
      await artifact.getByRole('button', { name: '查看 H1 提示' }).click();
      await artifact.getByRole('button', { name: '查看 H2 提示' }).click();
      await artifact.getByRole('textbox', { name: '练习答疑问题' }).fill('为什么初始值是零？');
      await artifact.getByRole('button', { name: '查看答疑样例' }).click();
      await artifact.getByRole('button', { name: '回到练习并折叠答疑' }).click();
      await artifact.getByRole('textbox', { name: 'Python 代码', exact: true }).fill(`${fixedCode}\n# demo draft`);
      await go('demo-python-practice');
      await top();
      check((await artifact.getByRole('textbox', { name: 'Python 代码', exact: true }).innerText()).includes('# demo draft'), 'draft lost');
      const saved = (await state()).artifacts.code;
      check(saved.attempts.length === 2 && saved.hints === 2 && saved.branch.length === 1 && saved.folded, 'result/assistance history lost');
      await page.locator('[data-artifact-id="review"]').getByText('参考评审', { exact: true }).waitFor();
      await page.locator('[data-artifact-id="review"]').getByRole('button', { name: '将修订示例放入编辑器' }).click();
      await page.locator('[data-artifact-id="review"]').getByRole('button', { name: '完成评审交互' }).click();
      check((await state()).artifacts.review.state === 'completed', 'review not completed');
    });
    await perform('SQL workspace and narrow-screen layout', async () => {
      await go('demo-sql-review');
      const artifact = page.locator('[data-artifact-id="sql"]');
      await artifact.getByRole('combobox', { name: 'SQL 方言' }).selectOption('PostgreSQL');
      const before = await artifact.getByRole('textbox', { name: 'SQL 查询', exact: true }).inputValue();
      await artifact.getByRole('tab', { name: '表结构', exact: true }).click();
      await artifact.getByRole('button', { name: '复制表名' }).click();
      check(await artifact.getByRole('textbox', { name: 'SQL 查询', exact: true }).inputValue() === before, 'copy inserted SQL');
      await artifact.getByRole('button', { name: '运行查询（演示）' }).click();
      await waitState('artifacts.sql.state', 'completed');
      await page.setViewportSize({ width: 390, height: 844 });
      await artifact.scrollIntoViewIfNeeded();
      const widths = await page.evaluate(() => ({ view: innerWidth, document: document.documentElement.scrollWidth }));
      check(widths.document <= widths.view, `mobile overflow: ${JSON.stringify(widths)}`);
      await page.screenshot({ path: 'D:/works/Leornian/.local/librechat-interactions-mobile.png' });
      await page.setViewportSize({ width: 1440, height: 1000 });
    });
    await perform('event demo and sandboxed editable HTML/CSS preview', async () => {
      await go('demo-web-interaction');
      await top();
      const animation = page.locator('[data-artifact-id="animation"]');
      for (let step = 0; step < 3; step++) await animation.getByRole('button', { name: '观察下一步' }).click();
      await animation.getByRole('button', { name: '确认看完演示' }).click();
      const preview = page.locator('[data-artifact-id="preview"]');
      await preview.getByRole('tab', { name: 'HTML', exact: true }).click();
      await preview.getByRole('textbox', { name: 'HTML 内容', exact: true }).fill('<main><h1>安全预览样例</h1><script>parent.__demoEscape=true</script><iframe src=\"/__preview_forbidden_probe\"></iframe></main>');
      await preview.getByRole('button', { name: '更新受限预览' }).click();
      check(await preview.locator('iframe').getAttribute('sandbox') === '', 'sandbox privileges present');
      check(await preview.frameLocator('iframe').getByRole('heading', { name: '安全预览样例' }).isVisible(), 'safe content not rendered');
      check(await preview.frameLocator('iframe').locator('script, iframe').count() === 0, 'active content survived sanitizing');
      check(await page.evaluate(() => window.__demoEscape) === undefined, 'preview escaped');
    });
  } else {
    await perform('model settings save without automatic test and explicit simulated test', async () => {
      await go('demo-python-learning');
      await settings('模型配置');
      const panel = page.getByRole('region', { name: '模型配置演示' });
      check(await panel.getByLabel('API Key', { exact: true }).isDisabled(), 'real key input enabled');
      await panel.getByRole('button', { name: '使用示例凭据占位' }).click();
      await panel.getByRole('button', { name: '保存演示配置' }).click();
      check((await state()).models.state === 'saved', 'save silently triggered test');
      await panel.getByRole('button', { name: '模拟连接测试' }).click();
      const dialog = page.getByRole('dialog', { name: '显式连接测试的确认样例', exact: true });
      await dialog.getByRole('checkbox').check();
      await dialog.getByRole('button', { name: '确认并模拟测试' }).click();
      await waitState('models.state', 'available');
      await page.getByRole('button', { name: '关闭设置', exact: true }).click();
    });
    await perform('engine onboarding, project consent and readonly multi-file boundaries', async () => {
      await go('demo-project-practice');
      await settings('本机执行');
      await page.getByRole('button', { name: '查看首次准备引导' }).click();
      await page.getByRole('button', { name: '体验准备过程（不实际安装）' }).click();
      await waitState('environment.engine', 'ready');
      await page.getByRole('button', { name: '关闭设置', exact: true }).click();
      await top();
      const project = page.locator('[data-artifact-id="project"]');
      check(await project.getByRole('button', { name: '运行并检查（演示）' }).isDisabled(), 'project ran without consent');
      await project.getByRole('tab', { name: '环境配置', exact: true }).click();
      await project.getByRole('button', { name: '查看环境与安装范围' }).click();
      await page.getByRole('button', { name: '同意范围并模拟准备' }).click();
      await waitState('environment.course', 'ready');
      await project.getByRole('button', { name: 'test_app.py', exact: true }).click();
      check(await project.getByRole('textbox', { name: 'test_app.py', exact: true }).getAttribute('readonly') !== null, 'tests editable');
      await project.getByRole('button', { name: 'app.py', exact: true }).click();
      await project.getByRole('button', { name: '运行并检查（演示）' }).click();
      await waitState('artifacts.project.state', 'completed');
    });
    await perform('exam is explicit and one-shot; review self-rating remains separate', async () => {
      await go('demo-exam-review');
      await top();
      const exam = page.locator('[data-artifact-id="exam"]');
      check(await exam.getByRole('button', { name: '明确开考（演示）' }).isDisabled(), 'exam silently started');
      await exam.getByRole('checkbox').check();
      await exam.getByRole('button', { name: '明确开考（演示）' }).click();
      await exam.getByRole('radio', { name: 'None', exact: true }).check();
      await exam.getByRole('textbox', { name: '题二：编写 total(values)', exact: true }).fill(fixedCode);
      await exam.getByRole('button', { name: '整组提交一次（演示）' }).click();
      check(await exam.getByRole('button', { name: '整组提交一次（演示）' }).isDisabled(), 'exam replay enabled');
      const review = page.locator('[data-artifact-id="review-activity"]');
      await review.getByRole('button', { name: '开始复习（演示）' }).click();
      await review.getByRole('textbox', { name: '复习回答' }).fill('return 返回给调用者，print 只显示。');
      await review.getByRole('button', { name: '一般', exact: true }).click();
      check((await state()).review.rating === '一般', 'self rating missing');
    });
    await perform('native file details, consent, source reading, permission revoke and update decision', async () => {
      await go('demo-python-learning');
      await page.getByTestId('nav-user').click();
      await page.getByTestId('nav-files').click();
      await page.getByRole('button', { name: 'Python 函数与边界条件 · 详情', exact: true }).click();
      await page.getByRole('button', { name: '演示撤销使用权限' }).click();
      check(await page.getByRole('button', { name: '阅读固定版本原文' }).isDisabled(), 'revoked material still readable');
      await page.getByRole('button', { name: '恢复样例使用权限' }).click();
      await page.getByRole('button', { name: '阅读固定版本原文' }).click();
      await page.getByRole('complementary', { name: '教材阅读面板' }).waitFor();
      await page.getByRole('button', { name: '关闭教材阅读' }).click();
      await page.getByRole('button', { name: '添加材料（演示）' }).click();
      const attach = page.getByRole('dialog', { name: '添加学习材料', exact: true });
      await attach.getByRole('checkbox').check();
      await attach.getByRole('button', { name: '确认用途并体验准备过程' }).click();
      await waitState('material.state', 'ready');
      await page.getByRole('button', { name: '查看差异与更新选择' }).click();
      await page.getByRole('button', { name: '本轮保留旧版', exact: true }).click();
      check((await state()).material.decision === 'keep', 'update choice missing');
    });
    await perform('native learning menu, records, preferences and task history', async () => {
      await go('demo-python-learning');
      await page.getByRole('button', { name: '当前学习菜单', exact: true }).click();
      await page.getByRole('menuitem', { name: '学习记录', exact: true }).click();
      await page.getByRole('dialog', { name: '学习记录', exact: true }).waitFor();
      await page.getByRole('button', { name: 'Close', exact: true }).click();
      await page.getByRole('button', { name: '后台任务（演示）', exact: true }).click();
      const tasks = page.getByRole('dialog', { name: '后台任务', exact: true });
      await tasks.waitFor();
      check((await tasks.innerText()).includes('结果未知'), 'unknown history missing');
    });
  }
  return { group, results, errors, unexpectedRequests: requests };
}

const invoke = window.__TAURI_INTERNALS__?.invoke;
const message = document.querySelector('#message');
let busy = false;
function display(status) {
  document.querySelector('#application').textContent = status.application === 'ready'
    ? '专用 API 与本应用服务进程已启动。' : '专用后台尚未就绪，检查隔离引擎或重新启动。';
  document.querySelector('#engine').textContent = status.engine.detail;
  if (status.application === 'ready') location.replace(status.frontend_url);
}
async function refresh() {
  if (!invoke) { message.textContent = '请从完整本机应用打开；浏览器不能代替应用管理本机服务。'; return; }
  try { display(await invoke('local_services', { action: 'status' })); }
  catch (error) { message.textContent = String(error); }
}
for (const button of document.querySelectorAll('[data-action]')) {
  button.addEventListener('click', async () => {
    if (!invoke || busy) return;
    busy = true;
    for (const control of document.querySelectorAll('button')) control.disabled = true;
    message.textContent = '正在处理本机服务，请保留此窗口。';
    try {
      const status = await invoke('local_services', { action: button.dataset.action });
      if (status.application) display(status);
      message.textContent = status.opened ? '请按照官方安装器完成系统权限与重启确认。'
        : '操作已返回，正在重新读取实际状态。';
      await refresh();
    } catch (error) { message.textContent = String(error); }
    finally {
      busy = false;
      for (const control of document.querySelectorAll('button')) control.disabled = false;
    }
  });
}
void refresh();
setInterval(() => { if (!busy) void refresh(); }, 3000);

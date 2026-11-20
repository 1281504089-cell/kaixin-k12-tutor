const title = document.getElementById('title');
const detail = document.getElementById('detail');
const progress = document.getElementById('progress');
const cancel = document.getElementById('cancel');
const mb = bytes => `${(bytes / 1024 / 1024).toFixed(1)} MB`;
let lastBytes = 0, lastTime = 0, speed = 0;
window.kaixinUpdate.onStatus(status => {
  const now = performance.now();
  if (status.received < lastBytes) { lastBytes = 0; lastTime = now; speed = 0; }
  if (now - lastTime >= 500) { speed = (status.received - lastBytes) * 1000 / (now - lastTime); lastBytes = status.received; lastTime = now; }
  title.textContent = ({ checking: '正在检查更新', downloading: '正在下载更新', installing: '正在校验并安装', installed: '更新已安装', current: '已是最新版本', cancelled: '已取消更新', error: '更新未完成' })[status.phase] || '超级学霸更新';
  detail.textContent = status.phase === 'downloading'
    ? `${mb(status.received)}${status.total > 0 ? ` / ${mb(status.total)} · ${Math.floor(status.received / status.total * 100)}%` : ''}${speed > 0 ? ` · ${mb(speed)}/秒` : ''}`
    : status.phase === 'installing' ? '正在校验、备份和切换，请稍候。完成前请勿关闭电脑。' : '正在连接更新服务；网络无响应时会提示重试。';
  if (status.phase === 'downloading' && status.total > 0) { progress.max = status.total; progress.value = status.received; }
  else progress.removeAttribute('value');
  cancel.disabled = !status.canCancel;
});
cancel.addEventListener('click', () => { cancel.disabled = true; void window.kaixinUpdate.cancel(); });

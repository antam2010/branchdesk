// Downloads run independently of Git operations. Only applying an update restarts the app.
let appUpdate = {state: 'idle'}, updatePollTimer, updateRequestPending = false;
const updateMessages = {
  idle: L('앱 업데이트를 확인할 수 있습니다.'),
  checking: L('새 버전을 확인하고 있습니다. 창을 닫고 앱을 계속 사용해도 됩니다.'),
  available: L('새 버전이 있습니다. 먼저 내려받아 준비할 수 있습니다.'),
  downloading: L('실행 중인 앱을 유지한 채 새 버전을 내려받고 검증하고 있습니다.'),
  ready: L('새 버전이 준비됐습니다. 적용하면 현재 창이 닫히고 자동으로 다시 열립니다.'),
  applying: L('업데이트 적용을 준비하고 있습니다.'),
  restarting: L('새 버전으로 다시 여는 중입니다.'),
  current: L('현재 실행 중인 앱이 최신 버전입니다.')
};
function paintAppUpdate() {
  const state = appUpdate.state;
  $('#app-update-open').textContent = state === 'ready' ? L('업데이트 적용') : state === 'downloading' ? L('업데이트 받는 중…') : L('앱 업데이트');
  $('#app-update-status').textContent = translatedMessage(appUpdate.message) || L(updateMessages[state]) || L('업데이트를 다시 확인하세요.');
  $('#app-update-release').textContent = appUpdate.summary ? appUpdate.summary + (appUpdate.date ? ' · ' + appUpdate.date.slice(0, 10) : '') : '';
  $('#app-update-check').disabled = ['checking', 'downloading', 'applying', 'restarting'].includes(state) || updateRequestPending;
  $('#app-update-download').hidden = state !== 'available';
  $('#app-update-apply').hidden = state !== 'ready';
  $('#app-update-download').disabled = $('#app-update-apply').disabled = updateRequestPending;
}
function scheduleAppUpdatePoll() {
  clearTimeout(updatePollTimer);
  if (['checking', 'downloading'].includes(appUpdate.state)) updatePollTimer = setTimeout(() => appUpdateRequest('status'), 1000);
}
async function appUpdateRequest(action) {
  if (updateRequestPending) return;
  updateRequestPending = true; paintAppUpdate();
  try {
    appUpdate = await api('app-update', {action, ticket: appUpdate.ticket});
  } catch (error) {
    appUpdate = {state: 'error', message: error.message};
  } finally {
    updateRequestPending = false; paintAppUpdate(); scheduleAppUpdatePoll();
  }
}
$('#app-update-open').onclick = () => {
  if (busy) return notice(L('현재 Git 작업이 끝난 뒤 업데이트를 확인하세요.'));
  $('#app-update-dialog').showModal(); paintAppUpdate();
  if (appUpdate.state === 'idle') appUpdateRequest('check');
};
$('#app-update-close').onclick = () => $('#app-update-dialog').close();
$('#app-update-check').onclick = () => appUpdateRequest('check');
$('#app-update-download').onclick = () => appUpdateRequest('download');
$('#app-update-apply').onclick = () => {
  if (busy || updateRequestPending) return notice(L('현재 Git 작업이 끝난 뒤 적용하세요.'));
  exclusive(async () => {
    const ticket = appUpdate.ticket;
    $('#app-update-status').textContent = L('업데이트 도우미를 준비하고 있습니다…');
    $('#app-update-apply').disabled = true;
    try {
      appUpdate = await api('app-update', {action: 'apply', ticket, ui: {drafts: [...drafts], repo, mode, home: showingHome}});
      paintAppUpdate();
      await api('app-update', {action: 'restart', ticket});
    } catch (error) {
      appUpdate = {state: 'error', message: error.message}; paintAppUpdate();
    }
  });
};

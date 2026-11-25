// Environment and SSH settings never request or display a private key's contents.
let environmentData = {profiles: []}, selectedEnvironment = 'default', environmentTimer;
const environmentOptions = () => environmentData.profiles.map(p => [p.id, p.name + ' · ' + (p.kind === 'local' ? '현재 OS' : p.kind.toUpperCase())]);
async function loadEnvironments() {
  environmentData = await api('environments');
  return environmentData;
}
function envMessage(message) { $('#env-message').textContent = message; }
function environmentForm(profile) {
  selectedEnvironment = profile.id || '';
  $('#env-profile').value = selectedEnvironment;
  $('#env-fields').innerHTML = textField('env-name', '환경 이름', profile.name || '') +
    selectField('env-kind', '실행 위치', [['local', '현재 앱과 같은 OS'], ['windows', 'Windows'], ['wsl', 'WSL 배포판']], profile.kind || 'windows') +
    textField('env-distro', 'WSL 배포판 이름 (비우면 기본 배포판)', profile.distro || '', false) +
    textField('env-python', 'Python 실행 파일', profile.python || '', false) +
    textField('env-git', 'Git 실행 파일 (비우면 해당 환경에서 자동 검색)', profile.git || '', false) +
    textField('env-ssh', 'SSH 실행 파일 (선택)', profile.ssh || '', false) +
    textField('env-key', 'SSH 개인키 경로 (비우면 기존 SSH 설정·에이전트 사용)', profile.key || '', false) +
    textField('env-agent', 'WSL/Linux ssh-agent 소켓 (선택)', profile.agent || '', false);
  $('#env-kind').disabled = profile.id === 'default';
  $('#env-kind').onchange = () => {
    $('#env-distro').closest('label').hidden = valueOf('env-kind') !== 'wsl';
    $('#env-python').placeholder = valueOf('env-kind') === 'windows' ? 'C:\\...\\python.exe' : '/usr/bin/python3';
  };
  $('#env-kind').onchange();
  $('#env-report').textContent = '';
  $('#env-ssh-actions').hidden = !profile.id;
  $('#env-startup').hidden = !profile.id || !environmentData.windowsRoot;
  $('#env-install-kind').value = profile.kind === 'wsl' || profile.kind === 'local' && environmentData.os === 'wsl' ? 'wsl' : 'windows';
  $('#env-install-dir').value = environmentData.windowsRoot ? environmentData.windowsRoot.replace(/\\/g, '/') + '/tools' : '';
  $('#env-install-distro').value = profile.distro || '';
  $('#env-keys').replaceChildren();
}
function environmentSelect() {
  $('#env-profile').innerHTML = optionList([...environmentOptions(), ['', '＋ 새 환경']], selectedEnvironment);
}
async function openEnvironmentSettings() {
  if (busy) return notice('현재 Git 작업이 끝난 뒤 환경 설정을 여세요.');
  if (document.querySelector('dialog[open]')) return;
  try {
    await loadEnvironments();
    selectedEnvironment = s?.environment || 'default';
    environmentSelect();
    environmentForm(environmentData.profiles.find(p => p.id === selectedEnvironment) || {});
    envMessage('저장소를 열 때 실행 환경을 선택합니다. Python·Git 경로는 선택한 OS 기준으로 입력하세요.');
    $('#environment-dialog').showModal();
    environmentTimer = setInterval(async () => {
      if (!$('#environment-dialog').open) return clearInterval(environmentTimer);
      try {
        await loadEnvironments();
        $('#env-install-status').textContent = environmentData.install.message || '';
        $('#env-install').disabled = environmentData.install.state === 'running';
      } catch { /* Leave the form available for retry. */ }
    }, 1800);
  } catch (error) { notice(error.message); }
}
async function envTask(job) {
  const buttons = [...$('#environment-dialog').querySelectorAll('button[data-env-task]')];
  buttons.forEach(button => button.disabled = true);
  $('#env-profile').disabled = true;
  try { await job(); }
  catch (error) { envMessage(error.message); }
  finally { buttons.forEach(button => button.disabled = false); $('#env-profile').disabled = false; }
}
$('#environment-open').onclick = openEnvironmentSettings;
$('#environment-close').onclick = () => $('#environment-dialog').close();
$('#environment-dialog').addEventListener('close', () => clearInterval(environmentTimer));
$('#env-profile').onchange = () => environmentForm(environmentData.profiles.find(p => p.id === valueOf('env-profile')) || {});
$('#env-save').onclick = () => envTask(async () => {
  const profile = {id: selectedEnvironment};
  for (const field of ['name', 'kind', 'distro', 'python', 'git', 'ssh', 'key', 'agent']) profile[field] = valueOf('env-' + field);
  const result = await api('environments', {action: 'save', profile});
  await loadEnvironments(); selectedEnvironment = result.profile.id;
  environmentSelect(); environmentForm(result.profile);
  $('#env-report').textContent = JSON.stringify(result.probe, null, 2);
  envMessage('경로를 확인하고 저장했습니다. 이 환경을 선택한 저장소의 다음 작업부터 사용합니다.');
});
$('#env-check').onclick = () => envTask(async () => {
  const result = await api('environments', {action: 'probe', profile: selectedEnvironment});
  $('#env-report').textContent = JSON.stringify(result, null, 2);
  envMessage('저장된 실행 환경이 정상 동작합니다. 수정한 경로는 확인·저장 버튼으로 검사하세요.');
});
$('#env-install').onclick = () => envTask(async () => {
  const kind = valueOf('env-install-kind'), directory = valueOf('env-install-dir'), distro = valueOf('env-install-distro');
  if (selectedEnvironment === 'default' && ((kind === 'windows') !== (environmentData.os === 'windows'))) throw new Error('현재 OS와 다른 프로그램을 설치하려면 먼저 환경 목록에서 ＋ 새 환경을 선택하세요.');
  await api('environments', {action: 'install', kind, directory, distro});
  if (kind === 'windows') {
    $('#env-kind').value = selectedEnvironment === 'default' ? 'local' : 'windows';
    $('#env-python').value = directory.replace(/[\\/]$/, '') + '/python/python.exe';
    $('#env-git').value = directory.replace(/[\\/]$/, '') + '/git/cmd/git.exe';
  } else {
    if (selectedEnvironment !== 'default') $('#env-kind').value = 'wsl';
    $('#env-distro').value = distro;
    $('#env-python').value = '/usr/bin/python3'; $('#env-git').value = '/usr/bin/git';
  }
  $('#env-kind').onchange();
  envMessage('설치 창을 열었습니다. 설치 후 경로를 확인·저장하세요. WSL은 배포판 패키지 경로에 설치합니다.');
});
$('#env-startup').onclick = () => envTask(async () => {
  const message = await api('environments', {action: 'startup', profile: selectedEnvironment});
  envMessage(message);
});
$('#env-keys-load').onclick = () => envTask(async () => {
  const keys = await api('environments', {action: 'ssh-list', profile: selectedEnvironment});
  $('#env-keys').innerHTML = '<option value="">기존 키 선택…</option>' + optionList(keys.map(k => [k.path, k.path]));
  envMessage(keys.length ? '키를 선택한 뒤 확인·저장하세요.' : '기본 .ssh 폴더에 키가 없습니다. 직접 경로를 입력하거나 새 키를 생성하세요.');
});
$('#env-keys').onchange = () => { if (valueOf('env-keys')) $('#env-key').value = valueOf('env-keys'); };
$('#env-public').onclick = () => envTask(async () => {
  const publicKey = await api('environments', {action: 'ssh-public', profile: selectedEnvironment, key: valueOf('env-key')});
  $('#env-public-key').value = publicKey;
  envMessage('공개키만 표시했습니다. GitHub·GitLab 계정의 SSH Keys에 등록하세요.');
});
$('#env-copy').onclick = () => envTask(async () => {
  const field = $('#env-public-key');
  if (!field.value) throw new Error('먼저 공개키를 불러오세요.');
  try { await navigator.clipboard.writeText(field.value); }
  catch { field.focus(); field.select(); if (!document.execCommand('copy')) throw new Error('공개키를 선택해 복사하세요.'); }
  envMessage('공개키를 복사했습니다.');
});
$('#env-generate').onclick = () => envTask(async () => {
  const result = await api('environments', {action: 'ssh-generate', profile: selectedEnvironment,
    name: valueOf('env-key-name'), comment: valueOf('env-key-comment'), unprotected: checked('env-unprotected')});
  $('#env-key').value = result.path; $('#env-public-key').value = result.public;
  envMessage('새 키를 만들었습니다. 공개키를 서비스에 등록하고 확인·저장하세요.');
});
$('#env-test').onclick = () => envTask(async () => {
  const result = await api('environments', {action: 'ssh-test', profile: selectedEnvironment, host: valueOf('env-ssh-host')});
  $('#env-report').textContent = result.message + '\n' + result.hint;
  envMessage(result.authenticated ? 'SSH 인증에 성공했습니다.' : 'SSH 인증을 완료하지 못했습니다. 아래 결과를 확인하세요.');
});

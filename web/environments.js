// Environment and SSH settings never request or display a private key's contents.
let environmentData = {profiles: []}, selectedEnvironment = 'default', previousEnvironment = 'default', environmentTimer;
const environmentPlatform = profile => profile.platform || (profile.kind === 'local' ? ({windows: 'Windows', wsl: 'WSL2', linux: 'Linux'}[environmentData.os]) : profile.kind === 'windows' ? 'Windows' : 'WSL2');
function environmentLabel(profile) {
  const platform = environmentPlatform(profile), name = profile.name === L('현재 실행 환경') ? platform : profile.name;
  return (name?.startsWith(platform) ? name : platform + ' · ' + name) + (profile.id === 'default' ? L(' (기본)') : '');
}
const environmentOptions = () => environmentData.profiles.map(p => [p.id, environmentLabel(p)]);
async function loadEnvironments() {
  environmentData = await api('environments');
  return environmentData;
}
function envMessage(message) { $('#env-message').textContent = message; }
function showEnvironmentReport(result) {
  $('#env-report').textContent = result.message || [result.platform || result.os, result.distro, result.gitVersion, 'Python ' + result.pythonVersion, 'Git: ' + result.git, 'Python: ' + result.python].filter(Boolean).join('\n');
}
function environmentForm(profile = {}, newKind = 'windows') {
  selectedEnvironment = profile.id || '';
  const adding = !selectedEnvironment;
  const kind = adding ? newKind : profile.kind === 'local' ? environmentData.os === 'windows' ? 'windows' : environmentData.os === 'wsl' ? 'wsl' : 'local' : profile.kind;
  const platform = adding ? kind === 'windows' ? 'Windows' : kind === 'wsl' ? 'WSL2' : 'Linux' : environmentPlatform(profile);
  $('#env-profile').value = selectedEnvironment;
  $('#env-picker').hidden = adding;
  $('#env-add-heading').hidden = !adding;
  $('#env-add-back').hidden = !adding;
  $('#env-type-choice').hidden = !adding;
  $('#env-type-choice').innerHTML = [['windows', 'Windows', L('C:\\projects 같은 Windows 폴더')], ['wsl', 'WSL2', L('/home/... 같은 Linux 폴더')], ...(environmentData.os === 'linux' ? [['local', 'Linux', L('이 PC의 Linux 폴더')]] : [])].map(([value, title, description]) => '<button type="button" data-env-kind="' + value + '" aria-pressed="' + (kind === value) + '"><strong>' + title + '</strong><small>' + esc(description) + '</small></button>').join('');
  $('#env-type-choice').querySelectorAll('button').forEach(button => button.onclick = () => environmentForm({}, button.dataset.envKind));
  $('#env-fields').innerHTML = '<input id="env-kind" type="hidden" value="' + esc(adding ? kind : profile.kind) + '">' +
    '<div class="environment-summary"><strong>' + esc(platform + (profile.distro ? ' · ' + profile.distro : '')) + '</strong><span>' + (adding ? L('새로 연결할 환경') : profile.id === s?.environment ? L('이 저장소에서 사용 중') : L('등록된 환경')) + '</span></div>' +
    textField('env-name', L('환경 이름'), profile.name || platform) +
    (kind === 'wsl' ? textField('env-distro', L('WSL 배포판 (비우면 기본 배포판)'), profile.distro || '', false) : '<input id="env-distro" type="hidden" value="">') +
    '<p class="environment-help">' + (kind === 'windows' ? L('Windows에 설치된 Git·Python을 자동으로 찾아 연결합니다.') : kind === 'wsl' ? L('선택한 WSL 배포판의 Git·Python을 자동으로 찾아 연결합니다.') : L('Linux에 설치된 Git·Python을 사용합니다.')) + '</p>' +
    L('<details id="env-tool-settings"><summary>프로그램 경로 직접 지정 (선택)</summary>') +
    textField('env-python', L('Python 실행 파일'), profile.python || '', false) +
    textField('env-git', L('Git 실행 파일'), profile.git || '', false) + L('<p>자동으로 찾지 못했거나 다른 버전을 쓰고 싶을 때 지정하세요.</p></details>');
  $('#env-python').placeholder = kind === 'windows' ? L('자동 검색 · C:\\...\\python.exe') : L('자동 검색 · /usr/bin/python3');
  $('#env-git').placeholder = kind === 'windows' ? L('자동 검색 · C:\\...\\git.exe') : L('자동 검색 · /usr/bin/git');
  $('#env-ssh-fields').innerHTML = textField('env-key', L('SSH 개인키 경로 (비우면 기존 인증 사용)'), profile.key || '', false) +
    L('<details><summary>SSH 세부 설정</summary>') + textField('env-ssh', L('SSH 실행 파일 (선택)'), profile.ssh || '', false) + textField('env-agent', L('WSL/Linux ssh-agent 소켓 (선택)'), profile.agent || '', false) + '</details>';
  $('#env-report').textContent = '';
  $('#env-diagnostics').open = false;
  $('#env-ssh-actions').hidden = adding;
  $('#env-ssh-actions').open = false;
  $('#env-startup-settings').hidden = adding || !environmentData.windowsRoot;
  $('#env-startup-settings').open = false;
  $('#env-check').hidden = adding;
  $('#env-save').textContent = adding ? L('이 환경 연결하기') : L('변경 사항 저장');
  $('#env-install-kind').value = kind === 'wsl' ? 'wsl' : 'windows';
  $('#env-install-dir').value = environmentData.windowsRoot ? environmentData.windowsRoot.replace(/\\/g, '/') + '/tools' : '';
  $('#env-install-distro').value = profile.distro || '';
  $('#env-install-distro').closest('label').hidden = kind !== 'wsl';
  $('#env-install-dir').closest('label').hidden = kind === 'wsl';
  $('#env-install-settings').open = false;
  $('#env-keys').replaceChildren();
}
function environmentSelect() {
  $('#env-profile').innerHTML = optionList(environmentOptions(), selectedEnvironment);
}
async function openEnvironmentSettings(initialAdd = false) {
  if (busy) return notice(L('현재 Git 작업이 끝난 뒤 환경 설정을 여세요.'));
  if (document.querySelector('dialog[open]')) return;
  try {
    await loadEnvironments();
    selectedEnvironment = s?.environment || 'default';
    environmentSelect();
    if (initialAdd === true) startEnvironmentAdd();
    else {
      environmentForm(environmentData.profiles.find(p => p.id === selectedEnvironment) || {});
      envMessage(L('한 앱에서 Windows와 WSL2 저장소를 함께 사용할 수 있습니다. 다른 환경은 실행 환경 추가로 연결하세요.'));
    }
    $('#environment-dialog').showModal();
    environmentTimer = setInterval(async () => {
      if (!$('#environment-dialog').open) return clearInterval(environmentTimer);
      try {
        await loadEnvironments();
        $('#env-install-status').textContent = translatedMessage(environmentData.install.message) || '';
        $('#env-install').disabled = environmentData.install.state === 'running';
      } catch { /* Keep user input available for retry. */ }
    }, 1800);
  } catch (error) { notice(error.message); }
}
function startEnvironmentAdd() {
  if (selectedEnvironment) previousEnvironment = selectedEnvironment;
  const opposite = environmentData.os === 'windows' ? 'wsl' : 'windows';
  environmentForm({}, opposite);
  envMessage(L('① Windows 또는 WSL2 선택 → ② 환경 이름 확인 → ③ 연결하기. 프로그램 경로는 자동으로 찾습니다.'));
}
async function addEnvironmentFromRepository() {
  const resume = {mode: valueOf('operation'), profile: valueOf('repo-environment'), path: valueOf('repo-path'), url: $('#repo-url')?.value, name: $('#initial')?.value};
  $('#dialog').close();
  await openEnvironmentSettings(true);
  if (!$('#environment-dialog').open) { await repositoryDialog(resume); return; }
  $('#environment-dialog').addEventListener('close', () => {
    if (environmentData.profiles.some(p => p.id === selectedEnvironment)) resume.profile = selectedEnvironment;
    repositoryDialog(resume);
  }, {once: true});
}
async function envTask(job) {
  const buttons = [...$('#environment-dialog').querySelectorAll('button[data-env-task], #env-type-choice button')];
  buttons.forEach(button => button.disabled = true);
  $('#env-profile').disabled = true;
  try { await job(); }
  catch (error) { envMessage(error.message); }
  finally { buttons.forEach(button => button.disabled = false); $('#env-profile').disabled = false; }
}
$('#environment-open').onclick = () => openEnvironmentSettings();
$('#environment-close').onclick = () => $('#environment-dialog').close();
$('#environment-dialog').addEventListener('close', () => clearInterval(environmentTimer));
$('#env-add').onclick = startEnvironmentAdd;
$('#env-add-back').onclick = () => {
  selectedEnvironment = previousEnvironment || s?.environment || 'default'; environmentSelect();
  environmentForm(environmentData.profiles.find(p => p.id === selectedEnvironment));
  envMessage(L('저장소를 열 때 Windows 또는 WSL2 환경을 선택하세요.'));
};
$('#env-profile').onchange = () => {
  environmentForm(environmentData.profiles.find(p => p.id === valueOf('env-profile')));
  envMessage(L('이 환경의 설정입니다. SSH 키와 프로그램 경로는 필요할 때 펼쳐서 변경하세요.'));
};
$('#env-save').onclick = () => envTask(async () => {
  const profile = {id: selectedEnvironment};
  const adding = !selectedEnvironment;
  for (const field of ['name', 'kind', 'distro', 'python', 'git', 'ssh', 'key', 'agent']) profile[field] = valueOf('env-' + field);
  envMessage(L('Git·Python을 찾아 연결을 확인하고 있습니다…'));
  let result;
  try { result = await api('environments', {action: 'save', profile}); }
  catch (error) {
    $('#env-report').textContent = error.message;
    if (adding && !profile.python) throw new Error(L('프로그램을 자동으로 연결하지 못했습니다. 아래의 프로그램 설치를 이용하거나 프로그램 경로를 직접 지정하세요. 자세한 원인은 진단 결과에서 확인할 수 있습니다.'));
    throw error;
  }
  await loadEnvironments(); selectedEnvironment = result.profile.id;
  environmentSelect(); environmentForm(environmentData.profiles.find(p => p.id === selectedEnvironment));
  showEnvironmentReport(result.probe);
  envMessage(environmentLabel(result.profile) + (adding ? L(' 연결 완료! 저장소 열기에서 이 환경을 선택하세요.') : L(' 설정을 저장했습니다.')) + ' · ' + result.probe.gitVersion + ' · Python ' + result.probe.pythonVersion);
});
$('#env-ssh-save').onclick = () => $('#env-save').click();
$('#env-check').onclick = () => envTask(async () => {
  const result = await api('environments', {action: 'probe', profile: selectedEnvironment});
  showEnvironmentReport(result);
  envMessage((result.platform || environmentPlatform(environmentData.profiles.find(p => p.id === selectedEnvironment))) + L(' 연결 정상 · ') + result.gitVersion + ' · Python ' + result.pythonVersion);
});
$('#env-install').onclick = () => envTask(async () => {
  const kind = valueOf('env-install-kind'), directory = valueOf('env-install-dir'), distro = valueOf('env-install-distro');
  await api('environments', {action: 'install', kind, directory, distro});
  if (kind === 'windows') {
    $('#env-python').value = directory.replace(/[\\/]$/, '') + '/python/python.exe';
    $('#env-git').value = directory.replace(/[\\/]$/, '') + '/git/cmd/git.exe';
  } else {
    $('#env-distro').value = distro;
    $('#env-python').value = '/usr/bin/python3'; $('#env-git').value = '/usr/bin/git';
  }
  envMessage(L('설치 창을 열었습니다. 완료되면 이 환경 연결하기 또는 변경 사항 저장을 누르세요.'));
});
$('#env-startup').onclick = () => envTask(async () => {
  const message = await api('environments', {action: 'startup', profile: selectedEnvironment});
  envMessage(translatedMessage(message));
});
$('#env-keys-load').onclick = () => envTask(async () => {
  const keys = await api('environments', {action: 'ssh-list', profile: selectedEnvironment});
  $('#env-keys').innerHTML = L('<option value="">기존 키 선택…</option>') + optionList(keys.map(k => [k.path, k.path]));
  envMessage(keys.length ? L('키를 선택한 뒤 SSH 설정 저장을 누르세요.') : L('기본 .ssh 폴더에 키가 없습니다. 직접 경로를 입력하거나 새 키를 생성하세요.'));
});
$('#env-keys').onchange = () => { if (valueOf('env-keys')) $('#env-key').value = valueOf('env-keys'); };
$('#env-public').onclick = () => envTask(async () => {
  const publicKey = await api('environments', {action: 'ssh-public', profile: selectedEnvironment, key: valueOf('env-key')});
  $('#env-public-key').value = publicKey;
  envMessage(L('공개키만 표시했습니다. GitHub·GitLab 계정의 SSH Keys에 등록하세요.'));
});
$('#env-copy').onclick = () => envTask(async () => {
  const field = $('#env-public-key');
  if (!field.value) throw new Error(L('먼저 공개키를 불러오세요.'));
  try { await navigator.clipboard.writeText(field.value); }
  catch { field.focus(); field.select(); if (!document.execCommand('copy')) throw new Error(L('공개키를 선택해 복사하세요.')); }
  envMessage(L('공개키를 복사했습니다.'));
});
$('#env-generate').onclick = () => envTask(async () => {
  const result = await api('environments', {action: 'ssh-generate', profile: selectedEnvironment,
    name: valueOf('env-key-name'), comment: valueOf('env-key-comment'), unprotected: checked('env-unprotected')});
  $('#env-key').value = result.path; $('#env-public-key').value = result.public;
  envMessage(L('새 키를 만들었습니다. 공개키를 서비스에 등록하고 SSH 설정 저장을 누르세요.'));
});
$('#env-test').onclick = () => envTask(async () => {
  const result = await api('environments', {action: 'ssh-test', profile: selectedEnvironment, host: valueOf('env-ssh-host')});
  $('#env-report').textContent = result.message + '\n' + translatedMessage(result.hint);
  $('#env-diagnostics').open = true;
  envMessage(result.authenticated ? L('SSH 인증에 성공했습니다.') : L('SSH 인증을 완료하지 못했습니다. 아래 결과를 확인하세요.'));
});

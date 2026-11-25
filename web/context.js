// History commands always retain the right-clicked commit and repository.
let commitMenu = null, commitMenuOrigin = null, menuGeneration = 0;
function closeCommitMenu(restore = true) {
  menuGeneration++;
  commitMenu?.remove();
  commitMenu = null;
  if (restore && commitMenuOrigin?.isConnected) commitMenuOrigin.focus({preventScroll: true});
}
function commitInfo(ctx) {
  return '<div class="commit-target"><code>' + esc(ctx.rev.slice(0, 12)) + '</code> ' + esc(ctx.subject) + '</div>';
}
function parentField(ctx) {
  return ctx.parents.length > 1 ? selectField('mainline', '병합의 기준 부모', ctx.parents.map((id, i) => [String(i + 1), (i + 1) + '번째 부모 · ' + id.slice(0, 10)]), '1') : '';
}
async function contextMutation(ctx, op, data = {}) {
  if (repo !== ctx.repo) throw Error('저장소가 바뀌었습니다. 다시 선택하세요.');
  return mutation(op, {rev: ctx.rev, expectedHead: ctx.head, expectedBranch: ctx.branch, ...data});
}
function commitConfirmation(ctx, op, title, description) {
  const merge = ['revert_commit', 'cherry_pick_commit'].includes(op);
  dialog(title, commitInfo(ctx) + info(description) + (merge ? parentField(ctx) : ''), title, () =>
    contextMutation(ctx, op, merge ? {mainline: Number($('#mainline')?.value || 1)} : {}));
}
function resetCommitDialog(ctx) {
  dialog('이 커밋까지 현재 브랜치 초기화', commitInfo(ctx) + info('대상 브랜치: ' + ctx.branch) +
    selectField('reset-mode', '초기화 방식', [['soft', 'Soft · 커밋만 되돌리고 스테이징 유지'], ['mixed', 'Mixed · 스테이징 해제, 파일 내용 유지'], ['hard', 'Hard · 스테이징과 파일 내용을 대상 커밋으로 덮어쓰기']], 'mixed') +
    '<p id="reset-warning"></p><label id="hard-confirm-label" hidden>변경 내용을 버리려면 HARD 입력<input id="hard-confirm" autocomplete="off" spellcheck="false"></label>',
    '초기화', () => contextMutation(ctx, 'reset_commit', {mode: valueOf('reset-mode'), confirmation: valueOf('hard-confirm')}));
  const update = () => {
    const hard = valueOf('reset-mode') === 'hard';
    $('#reset-warning').textContent = hard ? '추적 파일의 미커밋 변경과 스테이징 내용이 삭제됩니다. 대상 파일과 겹치는 미추적 파일도 삭제될 수 있습니다.' : '브랜치 이력이 이동합니다. 이미 공유한 커밋이라면 협업자와 먼저 확인하세요.';
    $('#reset-warning').className = hard ? 'danger-note' : '';
    $('#hard-confirm-label').hidden = !hard;
    $('#hard-confirm').required = hard;
    $('#confirm').disabled = hard && valueOf('hard-confirm') !== 'HARD';
  };
  $('#reset-mode').onchange = $('#hard-confirm').oninput = update;
  update();
}
async function reorderDialog(ctx) {
  const plan = await api('rebase-plan', {rev: ctx.rev});
  if (repo !== ctx.repo || plan.head !== ctx.head || plan.branch !== ctx.branch) throw Error('브랜치가 바뀌었습니다. 다시 확인하세요.');
  const rows = plan.commits.map(c => ({...c, action: 'pick'}));
  dialog('자식 커밋 쌍방향 재배치', commitInfo(ctx) + info('위에서 아래 순서로 다시 적용합니다. 순서 변경·합치기·제외를 선택하세요. 공유한 커밋의 ID가 바뀔 수 있습니다.') +
    '<div class="rebase-plan"></div>' + info('pick: 유지 · squash: 앞 커밋과 메시지도 합치기 · fixup: 변경만 합치기 · drop: 제외'), '재배치', () =>
    contextMutation(ctx, 'reorder_commits', {plan: rows.map(({id, action}) => ({id, action}))}));
  function paint() {
    $('.rebase-plan').innerHTML = rows.map((c, i) => '<div class="rebase-row" data-plan-row="' + i + '"><div class="plan-order"><button type="button" data-move="-1" ' + (!i ? 'disabled' : '') + ' aria-label="위로">↑</button><button type="button" data-move="1" ' + (i === rows.length - 1 ? 'disabled' : '') + ' aria-label="아래로">↓</button></div><code>' + esc(c.id.slice(0, 8)) + '</code><span>' + esc(c.subject) + '</span><select aria-label="' + esc(c.subject) + ' 처리">' + optionList(['pick', 'squash', 'fixup', 'drop'], c.action) + '</select></div>').join('');
    const first = rows.find(c => c.action !== 'drop');
    $('#confirm').disabled = !!first && first.action !== 'pick';
  }
  $('.rebase-plan').onclick = event => {
    const button = event.target.closest('[data-move]');
    if (!button) return;
    const i = Number(button.closest('[data-plan-row]').dataset.planRow), j = i + Number(button.dataset.move);
    if (j < 0 || j >= rows.length) return;
    [rows[i], rows[j]] = [rows[j], rows[i]];
    paint();
  };
  $('.rebase-plan').onchange = event => {
    const i = Number(event.target.closest('[data-plan-row]').dataset.planRow);
    rows[i].action = event.target.value;
    const first = rows.find(c => c.action !== 'drop');
    $('#confirm').disabled = !!first && first.action !== 'pick';
  };
  paint();
}
async function exportCommit(ctx, kind) {
  if (repo !== ctx.repo) throw Error('저장소가 바뀌었습니다.');
  const result = await api('export', {rev: ctx.rev, kind});
  const raw = atob(result.content), bytes = Uint8Array.from(raw, c => c.charCodeAt(0));
  const url = URL.createObjectURL(new Blob([bytes], {type: result.mime}));
  const link = document.createElement('a');
  link.href = url; link.download = result.name;
  document.body.append(link); link.click(); link.remove();
  setTimeout(() => URL.revokeObjectURL(url), 30000);
  notice(result.name + ' 파일을 저장합니다.');
}
async function copyCommit(ctx) {
  try {
    await navigator.clipboard.writeText(ctx.rev);
    notice('SHA 값을 클립보드에 복사했습니다.');
  } catch {
    dialog('SHA 값 복사', textField('copy-sha', '커밋 SHA', ctx.rev) + info('Ctrl+C로 복사하세요.'), '닫기', () => {});
    $('#copy-sha').readOnly = true; $('#copy-sha').select();
  }
}
function commitBranchDialog(ctx) {
  dialog('선택한 커밋에서 브랜치 만들기', commitInfo(ctx) + textField('new-name', '새 브랜치 이름') + checkField('checkout', '생성 후 체크아웃', false), '만들기', () => mutation('branch', {name: valueOf('new-name'), rev: ctx.rev, checkout: checked('checkout')}));
}
function commitTagDialog(ctx) {
  dialog('선택한 커밋에 태그 만들기', commitInfo(ctx) + textField('tag-name', '태그 이름'), '만들기', () => mutation('tag_create', {name: valueOf('tag-name'), rev: ctx.rev}));
}
function buildCommitMenu(ctx, extra = false) {
  commitMenu._context = ctx;
  commitMenu.dataset.extra = String(extra);
  const confirm = (op, title, body) => () => commitConfirmation(ctx, op, title, body);
  const entries = extra ? [
    ['‹ 커밋 작업으로', '', () => buildCommitMenu(ctx)],
    null,
    ['HEAD와 비교', '', () => {compareBase = ctx.rev; waitingForEnd = false; rev = ctx.head; historyView();}],
    ['비교 시작점 지정', '', () => {compareBase = ctx.rev; waitingForEnd = true; historyView();}],
    null,
    ['터미널 열기', '', () => exclusive(() => api('action', {op: 'terminal'}))],
    ['탐색기 열기', '', () => exclusive(() => api('action', {op: 'explorer'}))]
  ] : [
    ['체크아웃…', 'checkout_commit', confirm('checkout_commit', '커밋 체크아웃', '선택한 시점으로 이동합니다. 브랜치에 연결되지 않은 detached HEAD 상태가 됩니다.')],
    ['병합…', 'merge_commit', confirm('merge_commit', '현재 브랜치에 병합', ctx.branch + '에 선택한 커밋을 병합합니다.')],
    ['재배치…', 'rebase_commit', confirm('rebase_commit', '현재 브랜치 재배치', '현재 브랜치의 커밋을 선택한 커밋 위에 다시 적용합니다. 커밋 ID가 바뀔 수 있습니다.')],
    ['태그…', '', () => commitTagDialog(ctx)],
    ['아카이브…', '', () => exclusive(() => exportCommit(ctx, 'archive'))],
    ['브랜치…', '', () => commitBranchDialog(ctx)],
    [ctx.rev.slice(0, 7) + '의 자식 커밋을 쌍방향 재배치…', 'reorder_commits', () => exclusive(() => reorderDialog(ctx))],
    null,
    ['이 커밋까지 현재 브랜치를 초기화…', 'reset_commit', () => resetCommitDialog(ctx)],
    ['커밋 되돌리기…', 'revert_commit', confirm('revert_commit', '커밋 되돌리기', '선택한 커밋의 변경을 취소하는 새 커밋을 만듭니다.')],
    ['패치 생성…', ctx.parents.length > 1 ? 'merge_patch' : '', () => exclusive(() => exportCommit(ctx, 'patch'))],
    ['체리 픽…', 'cherry_pick_commit', confirm('cherry_pick_commit', '체리 픽', '선택한 커밋의 변경을 현재 브랜치에 적용합니다.')],
    null,
    ['SHA 값을 클립보드에 복사', '', () => copyCommit(ctx)],
    null,
    ['외부 비교 도구', 'external_diff', () => exclusive(() => contextMutation(ctx, 'external_diff')), 'Ctrl+D'],
    null,
    ['추가 작업', '', () => buildCommitMenu(ctx, true), '›']
  ];
  commitMenu.replaceChildren();
  for (const entry of entries) {
    if (!entry) { const separator = document.createElement('div'); separator.setAttribute('role', 'separator'); commitMenu.append(separator); continue; }
    const [label, op, run, shortcut] = entry;
    const reason = op === 'merge_patch' ? '병합 커밋에는 단일 패치를 만들 수 없습니다.' : ctx.permissions[op];
    const button = document.createElement('button');
    button.type = 'button'; button.setAttribute('role', 'menuitem'); button.tabIndex = -1;
    button.disabled = !!reason; if (reason) button.title = reason;
    button.textContent = label;
    if (shortcut) {const hint = document.createElement('span'); hint.textContent = shortcut; button.append(hint);}
    button.onclick = event => {
      event.stopPropagation();
      if (label === '추가 작업' || label === '‹ 커밋 작업으로') {run(); fitCommitMenu(); return;}
      closeCommitMenu(false);
      Promise.resolve().then(run).catch(error => notice(error.message, true));
    };
    commitMenu.append(button);
  }
  commitMenu.querySelector('button:not(:disabled)')?.focus({preventScroll: true});
}
function fitCommitMenu() {
  if (!commitMenu) return;
  const box = commitMenu.getBoundingClientRect();
  commitMenu.style.left = Math.max(6, Math.min(Number(commitMenu.dataset.x), innerWidth - box.width - 6)) + 'px';
  commitMenu.style.top = Math.max(6, Math.min(Number(commitMenu.dataset.y), innerHeight - box.height - 6)) + 'px';
}
async function openCommitMenu(row, x, y) {
  if (busy || !s || $('#dialog').open || $('#diff-popup').open) return;
  closeCommitMenu(false);
  const generation = menuGeneration, selectedRepo = repo, id = row.dataset.rev;
  selectRev(id);
  commitMenuOrigin = document.querySelector('.logrow[data-rev="' + id + '"]');
  commitMenu = document.createElement('div');
  commitMenu.className = 'commit-context'; commitMenu.setAttribute('role', 'menu');
  commitMenu.setAttribute('aria-label', '커밋 작업'); commitMenu.textContent = '작업 확인 중…';
  commitMenu.dataset.x = x; commitMenu.dataset.y = y;
  document.body.append(commitMenu); fitCommitMenu();
  try {
    const ctx = await api('commit-context', {rev: id});
    if (!commitMenu || generation !== menuGeneration || selectedRepo !== repo) return;
    ctx.repo = selectedRepo;
    buildCommitMenu(ctx); fitCommitMenu();
  } catch (error) {
    if (generation === menuGeneration) {closeCommitMenu(); notice(error.message, true);}
  }
}
document.addEventListener('contextmenu', event => {
  const row = event.target.closest('.logrow');
  if (row) {event.preventDefault(); openCommitMenu(row, event.clientX, event.clientY);}
});
document.addEventListener('pointerdown', event => {if (commitMenu && !commitMenu.contains(event.target)) closeCommitMenu(false);});
document.addEventListener('scroll', event => {if (commitMenu && !commitMenu.contains(event.target)) closeCommitMenu(false);}, true);
window.addEventListener('resize', () => closeCommitMenu(false));
window.addEventListener('blur', () => closeCommitMenu(false));
document.addEventListener('keydown', event => {
  const row = event.target.closest('.logrow');
  if (row && ((event.shiftKey && event.key === 'F10') || event.key === 'ContextMenu')) {
    event.preventDefault(); const box = row.getBoundingClientRect(); openCommitMenu(row, box.x + 30, box.bottom); return;
  }
  if (!commitMenu) {
    if (event.ctrlKey && !event.altKey && !event.shiftKey && event.key.toLowerCase() === 'd' && mode === 'history' && rev && !busy && !$('#dialog').open && !event.target.closest('input,textarea,select')) {
      event.preventDefault();
      exclusive(async () => {
        const ctx = {...await api('commit-context', {rev}), repo};
        if (ctx.permissions.external_diff) throw Error(ctx.permissions.external_diff);
        await contextMutation(ctx, 'external_diff');
      });
    }
    return;
  }
  const items = [...commitMenu.querySelectorAll('button:not(:disabled)')], i = items.indexOf(document.activeElement);
  if (event.key === 'Escape' || event.key === 'Tab') {event.preventDefault(); closeCommitMenu();}
  else if (event.key === 'ArrowLeft' && commitMenu.dataset.extra === 'true') {event.preventDefault(); buildCommitMenu(commitMenu._context); fitCommitMenu();}
  else if (event.key === 'ArrowRight' && document.activeElement?.textContent.startsWith('추가 작업')) {event.preventDefault(); document.activeElement.click();}
  else if (['ArrowDown', 'ArrowUp', 'Home', 'End'].includes(event.key)) {
    event.preventDefault();
    const n = event.key === 'Home' ? 0 : event.key === 'End' ? items.length - 1 : (i + (event.key === 'ArrowDown' ? 1 : -1) + items.length) % items.length;
    items[n]?.focus();
  }
});

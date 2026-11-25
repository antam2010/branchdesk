// History commands always retain the right-clicked commit and repository.
let commitMenu = null, commitMenuOrigin = null, menuGeneration = 0;
let commitSubmenu = null, submenuOrigin = null, submenuTimer;
function closeContextSubmenu() {
  clearTimeout(submenuTimer);
  commitSubmenu?.remove(); commitSubmenu = null;
  submenuOrigin?.setAttribute('aria-expanded', 'false'); submenuOrigin = null;
}
function closeCommitMenu(restore = true) {
  menuGeneration++;
  closeContextSubmenu();
  commitMenu?.remove();
  commitMenu = null;
  if (restore && commitMenuOrigin?.isConnected) commitMenuOrigin.focus({preventScroll: true});
}
function createContextSurface(origin, x, y, label) {
  closeCommitMenu(false);
  commitMenuOrigin = origin;
  commitMenu = document.createElement('div');
  commitMenu.className = 'commit-context'; commitMenu.setAttribute('role', 'menu');
  commitMenu.setAttribute('aria-label', label);
  commitMenu.dataset.x = x; commitMenu.dataset.y = y;
  (origin?.closest('dialog[open]') || document.body).append(commitMenu);
  return commitMenu;
}
function contextContains(target) {
  return commitMenu?.contains(target) || commitSubmenu?.contains(target);
}
function openContextSubmenu(button, entries, focus = true) {
  closeContextSubmenu();
  if (!commitMenu || !button.isConnected) return;
  submenuOrigin = button; button.setAttribute('aria-expanded', 'true');
  commitSubmenu = document.createElement('div');
  commitSubmenu.className = 'commit-context context-submenu';
  commitSubmenu.setAttribute('role', 'menu'); commitSubmenu.setAttribute('aria-label', button.dataset.label);
  commitMenu.parentElement.append(commitSubmenu);
  renderContextEntries(commitSubmenu, entries, false);
  const parent = commitMenu.getBoundingClientRect(), row = button.getBoundingClientRect();
  const box = commitSubmenu.getBoundingClientRect();
  commitSubmenu.style.left = Math.max(4, parent.right + box.width <= innerWidth - 4 ? parent.right - 2 : parent.left - box.width + 2) + 'px';
  commitSubmenu.style.top = Math.max(4, Math.min(row.top - 3, innerHeight - box.height - 4)) + 'px';
  if (focus) commitSubmenu.querySelector('button:not(:disabled)')?.focus({preventScroll: true});
}
// Entries: label, disabled reason, action, shortcut, optional submenu entries.
function renderContextEntries(surface, entries, focus = true) {
  surface.replaceChildren();
  for (const entry of entries) {
    if (!entry) {const line = document.createElement('div'); line.setAttribute('role', 'separator'); surface.append(line); continue;}
    const [label, reason, run, shortcut, children] = entry;
    const button = document.createElement('button');
    button.type = 'button'; button.setAttribute('role', 'menuitem'); button.tabIndex = -1;
    button.dataset.label = label; button.disabled = !!reason;
    if (reason) button.title = reason;
    const text = document.createElement('span'); text.className = 'menu-label'; text.textContent = label; button.append(text);
    if (shortcut || children) {const hint = document.createElement('span'); hint.className = 'menu-hint'; hint.textContent = children ? '›' : shortcut; button.append(hint);}
    if (children) {button.setAttribute('aria-haspopup', 'menu'); button.setAttribute('aria-expanded', 'false'); button._children = children;}
    button.onpointerenter = () => {
      if (surface !== commitMenu) return;
      if (submenuOrigin !== button) closeContextSubmenu();
      if (children && !button.disabled) submenuTimer = setTimeout(() => openContextSubmenu(button, children, false), 160);
    };
    button.onfocus = () => {if (surface === commitMenu && submenuOrigin !== button) closeContextSubmenu();};
    button.onclick = event => {
      event.stopPropagation();
      if (children) {openContextSubmenu(button, children); return;}
      closeCommitMenu(false);
      Promise.resolve().then(run).catch(error => notice(error.message, true));
    };
    surface.append(button);
  }
  if (focus) surface.querySelector('button:not(:disabled)')?.focus({preventScroll: true});
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
function buildCommitMenu(ctx) {
  const confirm = (op, title, body) => () => commitConfirmation(ctx, op, title, body);
  const extra = [
    ['HEAD와 비교', '', () => {compareBase = ctx.rev; waitingForEnd = false; rev = ctx.head; historyView();}],
    ['비교 시작점 지정', '', () => {compareBase = ctx.rev; waitingForEnd = true; historyView();}],
    null,
    ['터미널 열기', '', () => exclusive(() => api('action', {op: 'terminal'}))],
    ['탐색기 열기', '', () => exclusive(() => api('action', {op: 'explorer'}))]
  ];
  const entries = [
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
    ['추가 작업', '', null, '', extra.map(item => item && [item[0], '', item[2]])]
  ];
  renderContextEntries(commitMenu, entries.map(entry => {
    if (!entry) return null;
    const [label, op, run, shortcut, children] = entry;
    const reason = op === 'merge_patch' ? '병합 커밋에는 단일 패치를 만들 수 없습니다.' : ctx.permissions[op];
    return [label, reason, run, shortcut, children];
  }));
}
function fitCommitMenu() {
  if (!commitMenu) return;
  const box = commitMenu.getBoundingClientRect();
  commitMenu.style.left = Math.max(6, Math.min(Number(commitMenu.dataset.x), innerWidth - box.width - 6)) + 'px';
  commitMenu.style.top = Math.max(6, Math.min(Number(commitMenu.dataset.y), innerHeight - box.height - 6)) + 'px';
}
async function openCommitMenu(row, x, y) {
  if (busy || !s || document.querySelector('dialog[open]')) return;
  const selectedRepo = repo, id = row.dataset.rev;
  selectRev(id);
  createContextSurface(document.querySelector('.logrow[data-rev="' + id + '"]'), x, y, '커밋 작업');
  const generation = menuGeneration;
  commitMenu.textContent = '작업 확인 중…'; fitCommitMenu();
  try {
    const ctx = await api('commit-context', {rev: id});
    if (!commitMenu || generation !== menuGeneration || selectedRepo !== repo) return;
    ctx.repo = selectedRepo;
    buildCommitMenu(ctx); fitCommitMenu();
  } catch (error) {
    if (generation === menuGeneration) {closeCommitMenu(); notice(error.message, true);}
  }
}
async function copyDesktopText(text) {
  try {await navigator.clipboard.writeText(text);}
  catch {
    const active = document.activeElement, field = document.createElement('textarea');
    field.value = text; field.readOnly = true; field.style.position = 'fixed'; field.style.left = '-10000px';
    (document.querySelector('dialog[open]') || document.body).append(field); field.select();
    const copied = document.execCommand('copy'); field.remove(); active?.focus({preventScroll: true});
    if (!copied) throw Error('복사할 텍스트를 선택한 뒤 Ctrl+C를 사용하세요.');
  }
  notice('클립보드에 복사했습니다.');
}
function showDesktopMenu(origin, x, y, title, entries) {
  createContextSurface(origin, x, y, title);
  renderContextEntries(commitMenu, entries); fitCommitMenu();
}
function isTextField(target) {
  return target instanceof HTMLTextAreaElement || target instanceof HTMLInputElement &&
    ['text', 'search', 'password', 'url', 'tel'].includes(target.type);
}
function openEditMenu(field, x, y) {
  const snapshot = field.value;
  const start = field.selectionStart ?? 0, end = field.selectionEnd ?? 0;
  const text = field.value.slice(start, end), writable = !field.readOnly && !field.disabled;
  const secret = field.type === 'password';
  const undo = writable && document.queryCommandEnabled('undo');
  const redo = writable && document.queryCommandEnabled('redo');
  const restore = () => {if (!field.isConnected) throw Error('입력창이 닫혔습니다.'); field.focus({preventScroll: true}); field.setSelectionRange(start, end);};
  const insert = value => {
    restore();
    if (!document.execCommand('insertText', false, value)) {
      field.setRangeText(value, start, end, 'end');
      field.dispatchEvent(new InputEvent('input', {bubbles: true, inputType: 'insertFromPaste', data: value}));
    }
  };
  showDesktopMenu(field, x, y, '텍스트 편집', [
    ['실행 취소', undo ? '' : '취소할 입력이 없습니다.', () => {restore(); document.execCommand('undo');}, 'Ctrl+Z'],
    ['다시 실행', redo ? '' : '다시 실행할 입력이 없습니다.', () => {restore(); document.execCommand('redo');}, 'Ctrl+Y'],
    null,
    ['잘라내기', writable && text && !secret ? '' : '잘라낼 텍스트를 선택하세요.', async () => {await copyDesktopText(text); if (field.value !== snapshot) throw Error('입력 내용이 바뀌었습니다. 다시 선택하세요.'); restore(); if (!document.execCommand('delete')) insert('');}, 'Ctrl+X'],
    ['복사', text && !secret ? '' : '복사할 텍스트를 선택하세요.', () => copyDesktopText(text), 'Ctrl+C'],
    ['붙여넣기', writable ? '' : '읽기 전용 입력창입니다.', async () => {
      let text;
      try {text = await navigator.clipboard.readText();}
      catch {restore(); throw Error('클립보드 접근을 허용하거나 Ctrl+V로 붙여넣으세요.');}
      if (field.value !== snapshot) throw Error('입력 내용이 바뀌었습니다. 다시 붙여넣으세요.');
      insert(text);
    }, 'Ctrl+V'],
    null,
    ['전체 선택', field.value ? '' : '선택할 텍스트가 없습니다.', () => {field.focus({preventScroll: true}); field.select();}, 'Ctrl+A']
  ]);
}
function assertMenuRepo(expected) {
  if (repo !== expected) throw Error('저장소가 바뀌었습니다. 메뉴를 다시 여세요.');
}
function showReferenceMenu(button, x, y) {
  const ref = {...s.refs[Number(button.dataset.ref)]}, expected = repo;
  const view = () => {assertMenuRepo(expected); query = ''; compareBase = ''; waitingForEnd = false; selectRev(ref.id); document.querySelector('.logrow.selected')?.scrollIntoView({block: 'nearest'});};
  const confirmAction = (title, description, op, values) => () => {
    assertMenuRepo(expected);
    dialog(title, info(description), title, () => {assertMenuRepo(expected); return mutation(op, values);});
  };
  const blocked = busy || s.progress ? '진행 중인 작업을 먼저 마치세요.' : '';
  const entries = [['이 참조의 커밋 보기', '', view], ['이름 복사', '', () => copyDesktopText(ref.name)], ['SHA 값 복사', '', () => copyDesktopText(ref.id)], null];
  if (ref.group === 'heads') {
    entries.push(
      ['체크아웃…', blocked || (ref.name === s.branch ? '현재 브랜치입니다.' : ''), confirmAction('브랜치 전환', ref.name + ' 브랜치로 전환합니다.', 'switch', {name: ref.name})],
      ['이름 변경…', blocked, () => {
        dialog('브랜치 이름 변경', info(ref.name) + textField('context-new-name', '새 이름', ref.name), '변경', () => {
          assertMenuRepo(expected); return mutation('branch_rename', {name: ref.name, new: valueOf('context-new-name')});
        });
      }],
      ['로컬 브랜치 삭제…', blocked || (ref.name === s.branch ? '현재 브랜치는 삭제할 수 없습니다.' : ''), confirmAction('브랜치 삭제', ref.name + '를 삭제합니다. Git이 병합 여부를 확인합니다.', 'branch_delete', {name: ref.name})]
    );
  } else if (ref.group === 'tags') {
    entries.push(['로컬 태그 삭제…', blocked, confirmAction('태그 삭제', ref.name + ' 로컬 태그를 삭제합니다.', 'tag_delete', {name: ref.name})]);
  } else {
    entries.push(['로컬 추적 브랜치 만들기…', blocked, () => {
      dialog('원격 브랜치 추적', info(ref.name) + textField('context-new-name', '로컬 브랜치 이름', ref.name.slice(ref.name.indexOf('/') + 1)), '만들고 체크아웃', () => {
        assertMenuRepo(expected); return mutation('track', {upstream: ref.name, name: valueOf('context-new-name')});
      });
    }]);
  }
  showDesktopMenu(button, x, y, ref.group === 'tags' ? '태그 작업' : '브랜치 작업', entries);
}
function showFileMenu(button, x, y) {
  const file = fileList[Number(button.dataset.file)], expected = repo;
  if (!file) return;
  const choose = async () => {
    assertMenuRepo(expected);
    selected = file; paintFiles(); await showDiff();
  };
  const entries = [
    ['변경 내용 보기', '', () => exclusive(choose)],
    ['변경 내용 크게 보기', '', () => exclusive(async () => {await choose(); await expandDiff();})],
    null,
    ['파일 경로 복사', '', () => copyDesktopText(file.path)]
  ];
  if (mode === 'work') {
    const blocked = busy ? '진행 중인 작업을 먼저 마치세요.' : '';
    entries.splice(2, 0,
      [file.kind === 'index' ? '스테이징 해제' : '스테이징', blocked || (file.code === 'U' ? '충돌을 먼저 해결하세요.' : ''), () => exclusive(async () => {assertMenuRepo(expected); await mutation(file.kind === 'index' ? 'unstage' : 'stage', {paths: [file.path]});})],
      [file.code === 'U' ? '충돌 해결…' : '줄 선택…', blocked, () => exclusive(async () => {await choose(); if (file.code === 'U') await conflictDialog(); else await linesDialog();})]
    );
  }
  const text = window.getSelection()?.toString();
  if (text) entries.push(['선택 영역 복사', '', () => copyDesktopText(text), 'Ctrl+C']);
  showDesktopMenu(button, x, y, '파일 작업', entries);
}
function showTabMenu(button, x, y) {
  const path = repos[Number(button.dataset.tab)];
  const blocked = busy ? '진행 중인 작업을 먼저 마치세요.' : '';
  showDesktopMenu(button, x, y, '저장소 탭', [
    ['이 저장소로 전환', blocked || (path === repo ? '현재 저장소입니다.' : ''), () => exclusive(async () => {await api('select-tab', {repo: path}); await refresh(path);})],
    ['탭 닫기', blocked, () => {const i = repos.indexOf(path); if (i >= 0) document.querySelector('[data-close="' + i + '"]')?.click();}],
    null,
    ['터미널 열기', blocked, () => exclusive(() => api('action', {repo: path, op: 'terminal'}))],
    ['탐색기 열기', blocked, () => exclusive(() => api('action', {repo: path, op: 'explorer'}))],
    ['저장소 경로 복사', '', () => copyDesktopText(path)]
  ]);
}
function openApplicationContext(target, x, y) {
  if (contextContains(target)) return;
  if (isTextField(target)) {openEditMenu(target, x, y); return;}
  // Dialogs retain their own text editing menu and never expose background Git actions.
  const modal = document.querySelector('dialog[open]');
  if (modal) {
    const text = window.getSelection()?.toString();
    if (text) showDesktopMenu(target, x, y, '선택 영역', [['복사', '', () => copyDesktopText(text), 'Ctrl+C']]);
    else closeCommitMenu(false);
    return;
  }
  const row = target.closest('.logrow');
  if (row) {openCommitMenu(row, x, y); return;}
  const ref = target.closest('[data-ref]');
  if (ref && s) {showReferenceMenu(ref, x, y); return;}
  const file = target.closest('.file')?.querySelector('[data-file]');
  if (file && s) {showFileMenu(file, x, y); return;}
  const tab = target.closest('[data-tab]');
  if (tab) {showTabMenu(tab, x, y); return;}
  const stash = target.closest('[data-stash]');
  if (stash && s) {showDesktopMenu(stash, x, y, '스태시 작업', [['스태시 적용·삭제…', busy ? '작업 중입니다.' : '', () => stashDialog(Number(stash.dataset.stash))]]); return;}
  const entries = [
    ['새로고침', busy || !s ? '열린 저장소가 없거나 작업 중입니다.' : '', () => exclusive(() => refresh()), 'F5'],
    ['저장소 열기…', busy ? '작업 중입니다.' : '', () => exclusive(async () => {await loadRecent(); repositoryDialog();})]
  ];
  if (s) entries.push(null, ['히스토리', busy ? '작업 중입니다.' : '', () => switchMode('history')], ['파일 상태', busy ? '작업 중입니다.' : '', () => switchMode('work')], null,
    ['터미널 열기', busy ? '작업 중입니다.' : '', () => exclusive(() => api('action', {op: 'terminal'}))],
    ['탐색기 열기', busy ? '작업 중입니다.' : '', () => exclusive(() => api('action', {op: 'explorer'}))]);
  const text = window.getSelection()?.toString();
  if (text) entries.unshift(['선택 영역 복사', '', () => copyDesktopText(text), 'Ctrl+C'], null);
  showDesktopMenu(target, x, y, '워크스페이스', entries);
}
document.addEventListener('contextmenu', event => {
  event.preventDefault();
  openApplicationContext(event.target, event.clientX, event.clientY);
}, true);
document.addEventListener('pointerdown', event => {if (commitMenu && !contextContains(event.target)) closeCommitMenu(false);});
document.addEventListener('scroll', event => {if (commitMenu && !contextContains(event.target)) closeCommitMenu(false);}, true);
window.addEventListener('resize', () => closeCommitMenu(false));
window.addEventListener('blur', () => closeCommitMenu(false));
document.addEventListener('keydown', event => {
  if ((event.shiftKey && event.key === 'F10') || event.key === 'ContextMenu') {
    event.preventDefault(); const box = event.target.getBoundingClientRect(); openApplicationContext(event.target, box.x + 20, box.bottom); return;
  }
  if (!commitMenu && event.key === 'F5' && !event.ctrlKey && !event.altKey && !event.shiftKey && !document.querySelector('dialog[open]')) {
    event.preventDefault(); if (s && !busy) exclusive(() => refresh()); return;
  }
  if (!commitMenu) {
    if (event.ctrlKey && !event.altKey && !event.shiftKey && event.key.toLowerCase() === 'd' && mode === 'history' && rev && !busy && !document.querySelector('dialog[open]') && !event.target.closest('input,textarea,select')) {
      event.preventDefault();
      exclusive(async () => {
        const ctx = {...await api('commit-context', {rev}), repo};
        if (ctx.permissions.external_diff) throw Error(ctx.permissions.external_diff);
        await contextMutation(ctx, 'external_diff');
      });
    }
    return;
  }
  const surface = commitSubmenu?.contains(document.activeElement) ? commitSubmenu : commitMenu;
  const items = [...surface.querySelectorAll('button:not(:disabled)')], i = items.indexOf(document.activeElement);
  if (event.key === 'Tab') {event.preventDefault(); closeCommitMenu();}
  else if (event.key === 'Escape') {event.preventDefault(); if (commitSubmenu) {const origin = submenuOrigin; closeContextSubmenu(); origin?.focus();} else closeCommitMenu();}
  else if (event.key === 'ArrowLeft' && commitSubmenu) {event.preventDefault(); const origin = submenuOrigin; closeContextSubmenu(); origin?.focus();}
  else if (event.key === 'ArrowRight' && document.activeElement?._children) {event.preventDefault(); document.activeElement.click();}
  else if (['ArrowDown', 'ArrowUp', 'Home', 'End'].includes(event.key)) {
    event.preventDefault();
    const n = event.key === 'Home' ? 0 : event.key === 'End' ? items.length - 1 : (i + (event.key === 'ArrowDown' ? 1 : -1) + items.length) % items.length;
    items[n]?.focus();
  }
});

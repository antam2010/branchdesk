// Dialogs for repository operations. Form values are passed as JSON to the local server.
function optionList(items, initial) {
  return items.map(item => {
    const [value, label] = Array.isArray(item) ? item : [item, item];
    return '<option value="' + esc(value) + '" ' + (value === initial ? 'selected' : '') + '>' + esc(label) + '</option>';
  }).join('');
}
function selectField(id, label, items, initial) {
  return '<label>' + esc(label) + '<select id="' + id + '" required>' + optionList(items, initial) + '</select></label>';
}
function textField(id, label, value = '', required = true) {
  return '<label>' + esc(label) + '<input class="form-input" id="' + id + '" value="' + esc(value) + '" ' + (required ? 'required' : '') + '></label>';
}
function checkField(id, label, on = false) {
  return '<label class="check"><input type="checkbox" id="' + id + '" ' + (on ? 'checked' : '') + '>' + esc(label) + '</label>';
}
const info = message => '<p>' + esc(message) + '</p>';
const valueOf = id => document.getElementById(id).value;
const checked = id => document.getElementById(id).checked;
const localHeads = () => s.refs.filter(r => r.group === 'heads').map(r => r.name);
function operations(title, entries, initial) {
  const available = entries.filter(item => item.show !== false);
  if (!available.length) {
    notice('사용할 수 있는 항목이 없습니다.');
    return;
  }
  let chosen;
  dialog(title, selectField('operation', '작업', available.map(e => [e.id, e.label]), initial) + '<div id="op-fields"></div>', '실행', () => chosen.run());
  const paint = () => {
    chosen = available.find(item => item.id === valueOf('operation'));
    $('#op-fields').innerHTML = chosen.form();
    $('#confirm').textContent = chosen.button || chosen.label;
    if (chosen.bind) chosen.bind();
  };
  $('#operation').onchange = paint;
  paint();
}
function bindDirectoryPicker() {
  const input = $('#repo-path');
  const list = $('#repo-path-options');
  let timer, generation = 0, active = -1;
  function close() {
    clearTimeout(timer);
    generation++;
    active = -1;
    list.hidden = true;
    list.replaceChildren();
    input.setAttribute('aria-expanded', 'false');
    input.removeAttribute('aria-activedescendant');
  }
  function suggest() {
    close();
    const request = generation, path = input.value;
    timer = setTimeout(async () => {
      let paths;
      try {
        paths = await api('directories', {path});
      } catch {
        return; // A typed path can still be submitted.
      }
      if (request !== generation || document.activeElement !== input || !paths.length) return;
      paths.forEach((value, index) => {
        const option = document.createElement('li');
        option.id = 'directory-option-' + index;
        option.setAttribute('role', 'option');
        option.setAttribute('aria-selected', 'false');
        option.textContent = value;
        list.append(option);
      });
      list.hidden = false;
      input.setAttribute('aria-expanded', 'true');
    }, 120);
  }
  function choose(option) {
    input.value = option.textContent;
    input.focus();
    input.setSelectionRange(input.value.length, input.value.length);
    suggest();
  }
  input.oninput = input.onfocus = suggest;
  input.onblur = close;
  list.onmousedown = event => event.preventDefault(); // Keep the text caret in the field.
  list.onclick = event => {
    const option = event.target.closest('[role="option"]');
    if (option) choose(option);
  };
  input.onkeydown = event => {
    if (event.isComposing) return;
    if (event.key === 'Escape' && !list.hidden) {
      event.preventDefault();
      event.stopPropagation();
      close();
    } else if (event.key === 'ArrowDown' || event.key === 'ArrowUp') {
      event.preventDefault();
      if (list.hidden) { suggest(); return; }
      const options = list.children;
      if (active >= 0) options[active].setAttribute('aria-selected', 'false');
      if (event.key === 'ArrowDown') active = (active + 1) % options.length;
      else active = active <= 0 ? options.length - 1 : active - 1;
      const option = options[active];
      option.setAttribute('aria-selected', 'true');
      input.setAttribute('aria-activedescendant', option.id);
      option.scrollIntoView({block: 'nearest'});
    } else if (event.key === 'Enter' && active >= 0) {
      event.preventDefault();
      choose(list.children[active]);
    }
  };
}
function repositoryDialog() {
  const path = () => '<div><label for="repo-path">WSL 저장소 경로</label>' +
    '<input class="form-input" id="repo-path" role="combobox" aria-expanded="false" ' +
    'aria-autocomplete="list" aria-controls="repo-path-options" autocomplete="off" spellcheck="false" required>' +
    '<ul id="repo-path-options" role="listbox" aria-label="추천 폴더" hidden></ul></div>';
  const enter = async mode => {
    const input = {
      mode,
      path: valueOf('repo-path')
    };
    if (mode === 'clone') input.url = valueOf('repo-url');
    if (mode === 'init') input.name = valueOf('initial');
    const next = await api(mode === 'open' ? 'open' : 'new', input);
    repos = await api('repos');
    await refresh(next);
  };
  operations('저장소', [{
    id: 'open',
    label: '기존 저장소 열기',
    form: path,
    bind: bindDirectoryPicker,
    run: () => enter('open')
  }, {
    id: 'clone',
    label: '원격 저장소 클론',
    form: () => textField('repo-url', '원격 주소') + path(),
    bind: bindDirectoryPicker,
    run: () => enter('clone')
  }, {
    id: 'init',
    label: '빈 저장소 만들기',
    form: () => path() + textField('initial', '첫 브랜치', 'main'),
    bind: bindDirectoryPicker,
    run: () => enter('init')
  }]);
  $('#repo-path').focus();
}
function fetchDialog() {
  dialog('페치', '<label>원격 저장소<select id="fetch-remote">' + optionList([['', '모든 원격'], ...s.remotes]) + '</select></label>' + checkField('fetch-prune', '리모트에서 제거된 브랜치 정리하기') + checkField('fetch-tags', '모든 태그 가져오기'), '페치', () => mutation('fetch', {
    remote: valueOf('fetch-remote'),
    prune: checked('fetch-prune'),
    tags: checked('fetch-tags')
  }));
}
function branchDialog() {
  const heads = localHeads(),
    others = heads.filter(n => n !== s.branch);
  const upstream = s.refs.filter(r => r.group === 'remotes').map(r => r.name);
  const pick = (names = others) => selectField('manage-name', '브랜치', names);
  const newName = () => textField('new-name', '새 브랜치 이름');
  const selectedCommit = rev && rev !== s.head ? [[rev, '선택한 커밋 · ' + rev.slice(0, 9)]] : [];
  operations('브랜치', [{
    id: 'create',
    label: '브랜치 만들기',
    form: () => newName() + selectField('start-rev', '시작점', [[s.head, '현재 HEAD'], ...selectedCommit]) + checkField('checkout', '생성 후 체크아웃', true),
    run: () => mutation('branch', {
      name: valueOf('new-name'),
      rev: valueOf('start-rev'),
      checkout: checked('checkout')
    })
  }, {
    id: 'switch',
    label: '체크아웃',
    show: !!others.length,
    form: () => pick(),
    run: () => mutation('switch', {
      name: valueOf('manage-name')
    })
  }, {
    id: 'rename',
    label: '이름 변경',
    form: () => pick(heads) + newName(),
    run: () => mutation('branch_rename', {
      name: valueOf('manage-name'),
      new: valueOf('new-name')
    })
  }, {
    id: 'delete',
    label: '로컬 브랜치 삭제',
    show: !!others.length,
    form: () => pick() + info('Git이 병합 여부를 확인한 후 로컬 브랜치를 삭제합니다.'),
    run: () => mutation('branch_delete', {
      name: valueOf('manage-name')
    })
  }, {
    id: 'track',
    label: '원격 브랜치 추적',
    show: !!upstream.length,
    form: () => selectField('upstream', '원격 브랜치', upstream) + newName(),
    run: () => mutation('track', {
      upstream: valueOf('upstream'),
      name: valueOf('new-name')
    })
  }, {
    id: 'rebase',
    label: '현재 브랜치 리베이스',
    show: !!others.length && !!s.branch,
    form: () => pick() + info(s.branch + '의 커밋을 선택한 브랜치 위에 다시 적용합니다.'),
    run: () => mutation('rebase', {
      name: valueOf('manage-name')
    })
  }]);
}
function tagDialog() {
  const tags = s.refs.filter(r => r.group === 'tags').map(r => r.name);
  const pick = () => selectField('tag-name', '태그', tags);
  operations('태그', [{
    id: 'create',
    label: '태그 만들기',
    form: () => textField('tag-name', '태그 이름') + info('대상 커밋 · ' + (rev || s.head).slice(0, 10)),
    run: () => mutation('tag_create', {
      name: valueOf('tag-name'),
      rev: rev || s.head
    })
  }, {
    id: 'delete',
    label: '로컬 태그 삭제',
    show: !!tags.length,
    form: pick,
    run: () => mutation('tag_delete', {
      name: valueOf('tag-name')
    })
  }, {
    id: 'push',
    label: '태그 푸시',
    show: !!tags.length && !!s.remotes.length,
    form: () => pick() + selectField('remote-name', '원격', s.remotes),
    run: () => mutation('tag_push', {
      name: valueOf('tag-name'),
      remote: valueOf('remote-name')
    })
  }]);
}
async function remotesDialog() {
  const list = await api('urls');
  const pick = () => selectField('remote-name', '원격', s.remotes);
  const urls = () => list.find(r => r.name === valueOf('remote-name'));
  function paintURLs() {
    const r = urls();
    $('#url-values').innerHTML = [['페치 주소', r.fetch], ['푸시 주소', r.push]].map(([label, values]) => values.map(v => '<label>' + label + '<input class="form-input" readonly value="' + esc(v) + '"></label>').join('')).join('');
  }
  operations('원격 저장소', [{
    id: 'view',
    label: '주소 보기',
    show: !!list.length,
    form: () => pick() + '<div id="url-values"></div>',
    button: '닫기',
    bind: () => {
      paintURLs();
      $('#remote-name').onchange = paintURLs;
    },
    run: () => {}
  }, {
    id: 'add',
    label: '원격 추가',
    form: () => textField('remote-name', '이름', list.length ? '' : 'origin') + textField('url', '주소'),
    run: () => mutation('remote_add', {
      name: valueOf('remote-name'),
      url: valueOf('url')
    })
  }, {
    id: 'edit',
    label: '주소 수정',
    show: !!list.length,
    form: () => pick() + selectField('url-type', '수정할 주소', [['fetch', '페치'], ['push', '푸시']]) + textField('url', '새 주소'),
    bind: () => {
      const fill = () => $('#url').value = urls()[valueOf('url-type')][0];
      fill();
      $('#remote-name').onchange = fill;
      $('#url-type').onchange = fill;
    },
    run: () => mutation('remote_edit', {
      name: valueOf('remote-name'),
      url: valueOf('url'),
      pushUrl: valueOf('url-type') === 'push'
    })
  }, {
    id: 'remove',
    label: '원격 연결 제거',
    show: !!list.length,
    form: () => pick() + info('이 저장소의 원격 설정과 해당 원격 추적 브랜치를 정리합니다.'),
    run: () => mutation('remote_remove', {
      name: valueOf('remote-name')
    })
  }]);
}
function stashDialog(index) {
  const item = s.stashes[index];
  const choose = op => mutation(op, {
    id: item.id,
    index
  });
  operations('스태시 · ' + item.title, [{
    id: 'apply',
    label: '적용',
    form: () => info('인덱스와 작업 트리에 적용하고 보관본을 유지합니다.'),
    run: () => choose('apply_stash')
  }, {
    id: 'pop',
    label: '적용 후 제거 (pop)',
    form: () => info('적용에 성공하면 목록에서 제거합니다.'),
    run: () => choose('stash_pop')
  }, {
    id: 'drop',
    label: '보관본 삭제',
    form: () => info('선택한 스태시를 적용하지 않고 삭제합니다.'),
    run: () => choose('stash_drop')
  }]);
}
function flowDialog() {
  const heads = localHeads();
  const match = /^(feature|release|hotfix)\/(.+)$/.exec(s.branch);
  const finish = match && s.flow;
  const settings = {
    id: 'init',
    label: '운영·개발 브랜치 설정',
    form: () => selectField('production', '운영 브랜치', heads, s.flow?.[0] || ['main', 'master'].find(x => heads.includes(x)) || s.branch) + textField('development', '개발 브랜치 (없으면 생성)', s.flow?.[1] || (heads.includes('dev') ? 'dev' : 'develop')),
    run: () => mutation('flow_init', {
      production: valueOf('production'),
      development: valueOf('development')
    })
  };
  operations('Git Flow', [{
    id: 'start',
    label: '작업 시작',
    show: !!s.flow,
    form: () => selectField('flow-kind', '유형', ['feature', 'release', 'hotfix']) + textField('flow-name', '이름 (접두사 제외)') + info('feature·release는 개발 브랜치에서, hotfix는 운영 브랜치에서 시작합니다.'),
    run: () => mutation('flow_start', {
      kind: valueOf('flow-kind'),
      name: valueOf('flow-name')
    })
  }, {
    id: 'finish',
    label: '현재 작업 종료',
    show: !!finish,
    form: () => info(s.branch + '를 ' + (match[1] === 'feature' ? s.flow[1] : s.flow.join(' 및 ')) + '에 병합하고 작업 브랜치를 삭제합니다.') + (match[1] === 'feature' ? '' : textField('version-tag', '버전 태그', match[2])),
    run: () => mutation('flow_finish', {
      kind: match[1],
      name: match[2],
      tag: $('#version-tag')?.value
    })
  }, settings], finish ? 'finish' : s.flow ? 'start' : 'init');
}
async function linesDialog() {
  const f = selected;
  if (!f) return;
  const data = await api('lines', {
    path: f.path,
    kind: f.kind
  });
  if (!data.lines.length) {
    notice('선택할 텍스트 변경이 없습니다. 파일 단위로 처리하세요.');
    return;
  }
  const reverse = f.kind === 'index';
  const rows = data.lines.map(l => '<label class="pick-line ' + (l.side === '+' ? 'added' : 'removed') + '"><input type="checkbox" value="' + l.id + '"><code>' + esc(l.side + ' ' + l.number + '  ' + l.text) + '</code></label>').join('');
  dialog(reverse ? '선택 줄 스테이징 해제' : '선택 줄 스테이징', info(f.path + (reverse ? ' · 인덱스 → HEAD' : ' · 인덱스 → 작업 트리')) + '<div class="line-list">' + rows + '</div>', '선택 줄 적용', async () => {
    const lines = Array.from(document.querySelectorAll('.pick-line input:checked'), x => Number(x.value));
    await api('lines-apply', {
      path: f.path,
      kind: f.kind,
      stamp: data.stamp,
      lines
    });
    await refresh();
    notice('선택한 줄을 적용했습니다.');
  });
  $('#confirm').disabled = true;
  $('.line-list').onchange = () => $('#confirm').disabled = !document.querySelector('.pick-line input:checked');
}
async function conflictDialog() {
  const path = selected.path,
    c = await api('conflict', {
      path
    });
  const choices = [['ours', '현재 쪽 채택' + (c.ours ? '' : ' (삭제)')], ['theirs', '상대 쪽 채택' + (c.theirs ? '' : ' (삭제)')]];
  if (c.editable) choices.unshift(['edit', '직접 편집']);
  dialog('충돌 해결', info(path) + selectField('resolution', '해결 방법', choices) + (c.editable ? '<label id="resolution-label">저장할 내용<textarea id="resolution-text" rows="10"></textarea></label>' : ''), '해결하고 스테이징', async () => {
    await api('resolve', {
      path,
      stamp: c.stamp,
      choice: valueOf('resolution'),
      text: $('#resolution-text')?.value
    });
    await refresh();
    notice('해결 내용을 스테이징했습니다.');
  });
  if (c.editable) {
    $('#resolution-text').value = c.text;
    $('#resolution').onchange = () => $('#resolution-label').hidden = valueOf('resolution') !== 'edit';
  }
}

"use strict";

const $ = s => document.querySelector(s);
const esc = v => String(v ?? "").replace(/[&<>"']/g, c => ({
  "&": "&amp;",
  "<": "&lt;",
  ">": "&gt;",
  '"': "&quot;",
  "'": "&#39;"
})[c]);
const paths = {
  branch: "M6 4v13m0-4c7 0 11-2 11-7 M8 4a2 2 0 1 1-4 0 2 2 0 0 1 4 0 M8 19a2 2 0 1 1-4 0 2 2 0 0 1 4 0 M19 4a2 2 0 1 1-4 0 2 2 0 0 1 4 0",
  repo: "M5 3h14v18H6a2 2 0 0 1-2-2V5a2 2 0 0 1 1-2 M5 17h14 M8 6h6",
  merge: "M6 4v14 M18 5c0 8-12 6-12 12 M8 4a2 2 0 1 1-4 0 2 2 0 0 1 4 0 M8 20a2 2 0 1 1-4 0 2 2 0 0 1 4 0 M20 4a2 2 0 1 1-4 0 2 2 0 0 1 4 0",
  stash: "M3 4h18v5H3z M5 9v11h14V9 M10 13h4",
  history: "M4 10a8 8 0 1 1 1 8 M3 4v6h6 M12 7v6l4 2",
  files: "M7 3h8l4 4v13H7z M14 3v5h5 M3 7v15h12",
  commit: "M2 12h6m8 0h6 M16 12a4 4 0 1 1-8 0 4 4 0 0 1 8 0",
  pull: "M12 3v13m-5-5 5 5 5-5 M4 16v5h16v-5",
  push: "M12 17V4m-5 5 5-5 5 5 M4 16v5h16v-5",
  fetch: "M6 16a5 5 0 0 1-1-10 7 7 0 0 1 13-1 5 5 0 0 1 1 10 M12 10v11m-4-4 4 4 4-4",
  refresh: "M20 10a8 8 0 0 0-14-5L3 8 M3 3v5h5 M4 14a8 8 0 0 0 14 5l3-3 M21 21v-5h-5",
  search: "M16 10a6 6 0 1 1-12 0 6 6 0 0 1 12 0 M15 15l6 6",
  tag: "M3 3h8l10 10-8 8L3 11z M7 7h.01",
  flow: "M5 3v18 M18 3v18 M5 7c8 0 5 8 13 8 M18 7c-5 0-8 7-13 7",
  terminal: "M2 4h20v16H2z M6 8l4 4-4 4 M13 16h4",
  plus: "M12 5v14 M5 12h14",
  folder: "M3 6h7l2 3h9v11H3z",
  settings: "M4 7h16 M4 17h16 M9 4v6 M15 14v6",
  remote: "M3 4h18v13H3z M8 21h8 M12 17v4",
  file: "M6 2h8l5 5v15H6z M14 2v6h5"
};
function icon(k) {
  return '<svg class="ic" viewBox="0 0 24 24" aria-hidden="true"><path d="' + paths[k] + '"/></svg>';
}
function empty(s) {
  return '<div class="empty">' + esc(s) + '</div>';
}
document.title = "Branchdesk [" + location.port + "]";
const token = location.hash.slice(1) || sessionStorage.deskKey || "";
if (location.hash) {
  sessionStorage.deskKey = token;
  history.replaceState(null, "", location.pathname);
}
let repos = [],
  recentRepos = [],
  repo = "",
  s = null,
  mode = "history",
  rev = "",
  selected = null,
  fileList = [],
  limit = 150,
  query = "";
let compareBase = "",
  waitingForEnd = false;
let busy = false,
  detailSeq = 0,
  diffSeq = 0,
  actionPending = null,
  toastTimer;
const drafts = new Map(),
  collapsed = new Set();
let tabWarningShown = "";
async function api(name, data = {}) {
  const res = await fetch("/api/" + name, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      "X-Desk-Key": token
    },
    body: JSON.stringify({
      repo,
      ...data
    })
  });
  const payload = await res.json();
  if (!res.ok) throw Error(payload.error || "요청을 처리하지 못했습니다.");
  if (payload.warning && payload.warning !== tabWarningShown) {
    tabWarningShown = payload.warning;
    notice(payload.warning, true);
  }
  return payload.value;
}
function notice(msg, error = false) {
  clearTimeout(toastTimer);
  $("#toast").hidden = false;
  $("#toast").textContent = msg;
  const b = document.createElement("button");
  b.textContent = "×";
  b.ariaLabel = "닫기";
  b.onclick = () => $("#toast").hidden = true;
  $("#toast").append(b);
  if (!error) toastTimer = setTimeout(() => $("#toast").hidden = true, 3500);
}
async function exclusive(job) {
  if (busy) return;
  busy = true;
  document.body.classList.add("busy");
  $("#foot-status").textContent = "Git 작업 중…";
  try {
    await job();
  } catch (e) {
    notice(e.message, true);
  } finally {
    busy = false;
    document.body.classList.remove("busy");
    $("#foot-status").textContent = "로컬 Git";
  }
}
function tool(k, label, disabled = false) {
  const title = ({remote: '원격 저장소 웹페이지를 기본 브라우저로 열기', settings: 'Git 원격 주소 추가·수정·관리', terminal: '현재 저장소의 터미널 열기', folder: '현재 저장소 폴더를 탐색기로 열기'})[k] || label;
  return '<button title="' + esc(title) + '" class="tool" data-tool="' + k + '" ' + (disabled ? 'disabled' : '') + '>' + icon(k) + esc(label) + '</button>';
}
const environmentRepoPath = value => value?.startsWith('bd:') ? value.slice(value.indexOf(':', 3) + 1) : value;
const environmentRepoName = value => environmentRepoPath(value)?.split(/[\\/]/).pop() || value;
function chrome() {
  $("#tabs").innerHTML = repos.map((p, i) => '<button class="repo-tab ' + (p === repo ? 'active' : '') + '" data-tab="' + i + '" title="' + esc(environmentRepoPath(p)) + '">' + icon("repo") + esc(environmentRepoName(p)) + '</button><button class="close-tab" data-close="' + i + '" aria-label="' + esc(p) + ' 탭 닫기">×</button>').join("") + '<button class="add-tab" id="add">' + icon("plus") + '저장소 열기</button>';
  const off = !s,
    remote = off || !s.remotes.length;
  $("#toolbar").innerHTML = tool("commit", "커밋", off) + '<span class="separator"></span>' + tool("pull", "풀", remote) + tool("push", "푸시", remote) + tool("fetch", "페치", remote) + '<span class="separator"></span>' + tool("branch", "브랜치", off || !s.head) + tool("merge", "병합", off || !s.branch || !s.refs.some(r => r.group === "heads" && r.name !== s.branch)) + tool("stash", "스태시", off || !s.head || !s.changes.length) + tool("tag", "태그", off || !s.head) + tool("flow", "Git Flow", off || !s.head) + tool("remote", "원격", remote) + tool("settings", "원격 설정", off) + tool("terminal", "터미널", off) + tool("folder", "탐색기", off) + '<span class="push-right"></span>' + tool("refresh", "새로고침", off);
  $("#go-log").innerHTML = icon("history") + "히스토리";
  $("#go-work").innerHTML = icon("files") + '파일 상태<span class="count">' + (s?.changes.length ?? 0) + '</span>';
  $("#go-log").className = mode === "history" ? "active-nav" : "";
  $("#go-work").className = mode === "work" ? "active-nav" : "";
  $("#go-log").disabled = off;
  $("#go-work").disabled = off;
  $("#foot-repo").textContent = (s ? (s.environmentName.startsWith(s.environmentPlatform) ? s.environmentName : s.environmentPlatform + " · " + s.environmentName) + " · " + s.displayPath : environmentRepoPath(repo)) || "저장소를 열어 주세요";
  $("#nav-refs").innerHTML = s ? [["heads", "브랜치", "branch"], ["remotes", "원격 브랜치", "remote"], ["tags", "태그", "tag"]].map(([g, name, k]) => {
    const refs = s.refs.map((r, i) => ({
      ...r,
      i
    })).filter(r => r.group === g);
    return '<details data-group="' + g + '" ' + (collapsed.has(g) ? '' : 'open') + '><summary>' + name + ' · ' + refs.length + '</summary>' + (refs.map(r => '<button class="nav-ref ' + (g === "heads" && r.name === s.branch ? 'current-ref' : '') + '" data-ref="' + r.i + '" title="' + esc(r.name) + '">' + icon(k) + '<span class="ellipsis">' + esc(r.name) + '</span>' + (g === "heads" && r.name === s.branch ? '<small>현재</small>' : '') + '</button>').join("") || '<div class="no-refs">없음</div>') + '</details>';
  }).join("") + '<details data-group="stash" ' + (collapsed.has("stash") ? '' : 'open') + '><summary>스태시 · ' + s.stashes.length + '</summary>' + (s.stashes.map((item, i) => '<button class="nav-ref" data-stash="' + i + '" title="' + esc(item.title) + '">' + icon("stash") + '<span class="ellipsis">' + esc(item.title) + '</span></button>').join("") || '<div class="no-refs">없음</div>') + '</details>' : "";
}
function head(title, search = false) {
  const b = s.branch || (s.head ? s.head.slice(0, 8) : "HEAD");
  return '<div class="page-head"><h1>' + title + '</h1><span class="head-branch">' + icon("branch") + esc(b) + '</span>' + (search ? '<label class="search">' + icon("search") + '<input id="search" aria-label="커밋 검색" placeholder="메시지, 작성자, 해시 검색" value="' + esc(query) + '"></label>' : '') + '</div>';
}
const colors = ["#25866c", "#6789bd", "#bb8242", "#936db4", "#548e9b", "#a76679"];
function graphData(commits) {
  let lanes = [],
    seq = 0,
    max = 1;
  const lane = id => ({
    id,
    color: colors[seq++ % colors.length]
  });
  const rows = commits.map(c => {
    let at = lanes.findIndex(l => l.id === c.id),
      fresh = at < 0;
    if (fresh) {
      at = lanes.length;
      lanes.push(lane(c.id));
    }
    const before = lanes.slice(),
      node = lanes[at];
    lanes.splice(at, 1);
    let insert = at;
    for (const [i, p] of c.parents.entries()) {
      if (!lanes.some(l => l.id === p)) {
        lanes.splice(insert++, 0, i === 0 ? {
          id: p,
          color: node.color
        } : lane(p));
      }
    }
    // Straight segments continue surviving lanes; each parent receives a lower half-edge.
    max = Math.max(max, before.length, lanes.length);
    const x = i => 10 + 13 * i;
    const seg = (a, y, b, v, color) => '<path d="M' + x(a) + ' ' + y + ' C' + x(a) + ' ' + (v + y) / 2 + ' ' + x(b) + ' ' + (v + y) / 2 + ' ' + x(b) + ' ' + v + '" stroke="' + color + '" fill="none" stroke-width="2"/>';
    let svg = "";
    before.forEach((l, i) => {
      if (i === at) {
        if (!fresh) svg += seg(i, 0, i, 16, node.color);
      } else svg += seg(i, 0, lanes.findIndex(n => n.id === l.id), 33, l.color);
    });
    c.parents.forEach((p, i) => {
      const j = lanes.findIndex(n => n.id === p);
      svg += seg(at, 16, j, 33, i === 0 ? node.color : lanes[j].color);
    });
    return svg + '<circle cx="' + x(at) + '" cy="16" r="3.8" fill="white" stroke="' + node.color + '" stroke-width="2.4"/>';
  });
  return {
    rows,
    width: Math.max(60, Math.min(max * 13 + 12, 190))
  };
}
let graph, labels;
function drawRows() {
  const needle = query.trim().toLowerCase();
  const items = s.commits.map((c, i) => ({
    c,
    i
  })).filter(({
    c
  }) => !needle || [c.subject, c.id, c.author, ...(labels.get(c.id) || []).map(r => r.name)].some(v => v.toLowerCase().includes(needle)));
  $("#rows").innerHTML = items.map(({
    c,
    i
  }) => {
    const refs = (labels.get(c.id) || []).map(r => '<span class="ref ' + r.group + '">' + esc(r.name) + '</span>').join("");
    return '<button class="logrow ' + (rev === c.id ? 'selected' : compareBase === c.id ? 'comparison-base' : '') + '" data-rev="' + c.id + '">' + (needle ? '<span>' + icon("commit") + '</span>' : '<svg class="graph" width="' + graph.width + '" height="33" aria-hidden="true">' + graph.rows[i] + '</svg>') + '<span class="ellipsis" title="' + esc(c.subject) + '">' + refs + esc(c.subject) + '</span><span class="ellipsis">' + esc(c.author) + '</span><span class="date">' + esc(c.date.slice(0, 10)) + '</span><span class="hash">' + c.id.slice(0, 7) + '</span></button>';
  }).join("") || empty(needle ? "불러온 커밋에서 검색 결과가 없습니다." : "첫 커밋을 만들면 이곳에 표시됩니다.");
}
function historyView() {
  $("#main").innerHTML = head("히스토리", true) + (rev ? '<div class="compare-bar"><button id="compare-pin">' + (waitingForEnd ? '대상 커밋 선택 중…' : '비교 시작점 지정') + '</button>' + (compareBase ? '<span>' + esc(compareBase.slice(0, 8)) + ' → ' + (waitingForEnd ? '그래프에서 대상 선택' : esc(rev.slice(0, 8))) + '</span><button id="compare-clear">비교 해제</button>' : '<span>두 번째 커밋을 Ctrl 또는 Shift와 함께 클릭해 비교</span>') + '<button class="right" id="cherry">체리픽</button></div>' : '') + '<div class="history-panes"><div class="history"><div class="table"><div class="loghead"><span>그래프</span><span>커밋 메시지</span><span>작성자</span><span>날짜</span><span>커밋</span></div><div id="rows"></div></div>' + (s.more && limit < 5000 ? '<button class="more" id="more">이전 커밋 더 보기 ↓</button>' : '') + '</div>' + separator('history') + '<section class="inspect" id="inspect"></section></div>';
  graph = graphData(s.commits);
  labels = new Map();
  for (const r of s.refs) {
    if (!labels.has(r.id)) labels.set(r.id, []);
    labels.get(r.id).push(r);
  }
  $(".table").style.setProperty("--graph", graph.width + "px");
  drawRows();
  if (rev) loadDetail();else $("#inspect").innerHTML = empty("선택한 커밋이 없습니다.");
}
let treeView = false;
function fileRow(f, i, editable, label = f.path) {
  return '<div class="file ' + (selected?.kind === f.kind && selected?.path === f.path ? 'selected' : '') + '"><button data-file="' + i + '" title="' + esc(f.path) + '"><span class="status-code code-' + esc(f.code) + '">' + esc(f.code) + '</span><span class="ellipsis">' + esc(label) + '</span></button>' + (editable ? '<button class="toggle" data-toggle="' + i + '" title="' + (f.kind === "index" ? "스테이징 해제" : "스테이징") + '" aria-label="' + esc(f.path) + (f.kind === "index" ? ' 스테이징 해제">−' : ' 스테이징">+') + '</button>' : '') + '</div>';
}
function treeRows(entries, editable) {
  const node = () => ({folders: new Map(), files: []});
  const root = node();
  for (const {f, i} of entries) {
    const parts = f.path.split("/");
    const name = parts.pop();
    let parent = root;
    for (const part of parts) {
      if (!parent.folders.has(part)) parent.folders.set(part, node());
      parent = parent.folders.get(part);
    }
    parent.files.push(fileRow(f, i, editable, name));
  }
  function draw(parent) {
    const folders = Array.from(parent.folders, ([name, child]) =>
      '<details class="file-folder" open><summary>' + icon("folder") + esc(name) +
      '</summary><div>' + draw(child) + '</div></details>');
    return folders.join("") + parent.files.join("");
  }
  return draw(root);
}
function filesHtml(group, editable) {
  const entries = fileList.map((f, i) => ({
    f,
    i
  })).filter(v => v.f.kind === group);
  const title = {
    index: "스테이징된 파일",
    work: "스테이징하지 않은 파일",
    commit: "변경 파일"
  }[group];
  return '<div class="subhead">' + title + ' <span>' + entries.length + '</span>' + (editable && entries.length ? '<button data-all="' + group + '">' + (group === "work" ? "모두 스테이지" : "모두 해제") + '</button>' : '') + '</div>' + ((treeView ? treeRows(entries, editable) : entries.map(({f, i}) => fileRow(f, i, editable)).join("")) || empty("파일 없음"));
}
function paintFiles() {
  const choices = '<div class="file-views" role="group" aria-label="변경 파일 보기">' +
    '<button data-file-view="list" aria-pressed="' + !treeView + '">목록</button>' +
    '<button data-file-view="tree" aria-pressed="' + treeView + '">트리</button></div>';
  $(".files").innerHTML = choices + (mode === "work" ? filesHtml("index", true) + filesHtml("work", true) : filesHtml("commit", false));
}
async function loadDetail() {
  const serial = ++detailSeq;
  ++diffSeq;
  const pane = $("#inspect");
  pane.innerHTML = empty("변경 내역을 불러오는 중…");
  try {
    const detail = await api("detail", {
      rev,
      base: waitingForEnd ? "" : compareBase
    });
    if (serial !== detailSeq || mode !== "history" || !pane.isConnected) return;
    const c = s.commits.find(c => c.id === rev);
    pane.innerHTML = '<div class="commit-head"><div class="meta"><span class="badge">' + (compareBase && !waitingForEnd ? "두 커밋 비교" : "커밋") + '</span><span class="hash">' + rev.slice(0, 10) + '</span>' + esc(c ? [c.author, c.date.slice(0, 10)].join(" · ") : "") + '</div><div class="commit-title">' + esc(compareBase && !waitingForEnd ? compareBase.slice(0, 10) + " → " + rev.slice(0, 10) + " · " + detail.files.length + "개 변경 파일" : detail.message) + '</div></div><div class="split"><div class="files"></div>' + separator('files') + '<div class="diff"></div></div>';
    fileList = detail.files.map(f => ({
      ...f,
      kind: "commit"
    }));
    selected = fileList[0] || null;
    paintFiles();
    showDiff();
  } catch (e) {
    if (serial === detailSeq && pane.isConnected) pane.innerHTML = empty(e.message);
  }
}
let previewRequest;
function patchHtml(patch) {
  if (patch && typeof patch === 'object' && patch.type === 'file') {
    const heading = '<div class="file-preview-heading">' + esc(patch.title || '파일 전체 내용') + '</div>';
    if (patch.message) return heading + empty(patch.message);
    if (patch.empty) return heading + empty('빈 파일입니다. 파일 내용이 없습니다.');
    const lines = patch.text.split('\n'), shown = lines.slice(0, 3000);
    return heading + '<div class="patch full-file-preview">' + shown.map((text, index) => '<div class="file-source-line"><span class="file-line-number">' + (index+1) + '</span><code>' + (esc(text) || ' ') + '</code></div>').join('') + '</div>' + (patch.truncated || lines.length>shown.length ? empty('미리보기 한도: 최대 192 KiB · 3,000줄까지 표시합니다.') : '');
  }
  const lines = patch.split("\n"), shown = lines.slice(0, 3000);
  return patch ? '<div class="patch">' + shown.map(l => {
      const cls = /^(diff |index |--- |\+\+\+ |new file|deleted file|old mode|new mode)/.test(l) ? "pmeta" : l.startsWith("@@") ? "hunk" : l.startsWith("+") ? "plus" : l.startsWith("-") ? "minus" : "";
      return '<div class="' + cls + '">' + (esc(l) || " ") + '</div>';
    }).join("") + '</div>' + (lines.length > shown.length ? empty("처음 3,000줄까지 표시합니다.") : "") : empty("표시할 텍스트 변경이 없습니다.");
}
async function expandDiff() {
  if (!selected || !previewRequest) return;
  const popup = $("#diff-popup"), request = previewRequest;
  $("#popup-file").textContent = selected.path;
  $("#popup-patch").innerHTML = empty("비교 내용을 불러오는 중…");
  popup.showModal();
  try {
    const patch = await request;
    if (popup.open && request === previewRequest) $("#popup-patch").innerHTML = patchHtml(patch);
  } catch (error) {
    if (popup.open && request === previewRequest) $("#popup-patch").innerHTML = empty(error.message);
  }
}
async function showDiff() {
  const serial = ++diffSeq,
    pane = $(".diff"),
    f = selected;
  if (!pane) return;
  if (!f) {
    pane.innerHTML = empty("비교할 파일이 없습니다.");
    return;
  }
  pane.innerHTML = empty("비교 내용을 불러오는 중…");
  try {
    previewRequest = api("diff", {
      rev,
      base: waitingForEnd ? "" : compareBase,
      kind: f.kind,
      code: f.code,
      path: f.path
    });
    const patch = await previewRequest;
    if (serial !== diffSeq || !pane.isConnected) return;
    pane.innerHTML = '<div class="subhead">' + icon("file") + '<span class="ellipsis" title="' + esc(f.path) + '">' + esc(f.path) +
      '</span><button id="expand-diff">크게 보기</button>' + (mode === "work" && !(patch?.type === 'file' && (patch.message || patch.empty)) ? '<button id="partial">' + (f.code === "U" ? '충돌 해결' : '줄 선택') + '</button>' : '') +
      '</div>' + patchHtml(patch);
  } catch (e) {
    if (serial === diffSeq && pane.isConnected) pane.innerHTML = empty(e.message);
  }
}
const conflict = f => ["DD", "AU", "UD", "UA", "DU", "AA", "UU"].includes(f.x + f.y);
function workView() {
  ++detailSeq;
  const indexed = s.changes.filter(f => !conflict(f) && ![" ", "?"].includes(f.x)).map(f => ({
    ...f,
    kind: "index",
    code: f.x
  }));
  const work = s.changes.filter(f => conflict(f) || f.y !== " ").map(f => ({
    ...f,
    kind: "work",
    code: conflict(f) ? "U" : f.y
  }));
  fileList = [...indexed, ...work];
  selected = fileList.find(f => f.kind === selected?.kind && f.path === selected?.path) || fileList[0] || null;
  $("#main").innerHTML = head("파일 상태") + (s.progress ? '<div class="compare-bar">' + esc(s.progress) + ' 진행 중 <button id="proceed">계속</button><button id="abort">중단</button></div>' : '') + '<div class="split work-split"><div class="files"></div>' + separator('files') + '<div class="diff"></div></div><div class="composer"><label>커밋 메시지<textarea id="message" placeholder="변경 내용을 입력하세요"></textarea></label>' + (s.head && !s.progress ? checkField("amend", "마지막 커밋 수정") : "") + '<button class="primary" id="do-commit">커밋</button></div>';
  $("#message").value = drafts.get(repo) || "";
  enableCommit();
  paintFiles();
  showDiff();
}
function enableCommit() {
  $("#do-commit").disabled = !$("#message").value.trim() || !$("#amend")?.checked && !fileList.some(f => f.kind === "index") && s.progress !== "merge" || s.changes.some(conflict);
}
function recentList() {
  if (!recentRepos.length) return "";
  const buttons = recentRepos.map(path => '<button type="button" data-recent="' + esc(path) +
    '"><strong>' + esc(environmentRepoName(path)) + '</strong><small>' + esc(environmentRepoPath(path)) + '</small></button>');
  return '<section class="recent-repos"><h3>최근 저장소</h3><div>' + buttons.join("") + '</div></section>';
}
async function loadRecent() {
  recentRepos = await api("recent");
}
function render() {
  if (typeof closeCommitMenu === "function") closeCommitMenu(false);
  ++detailSeq;
  ++diffSeq;
  chrome();
  if (!s) {
    $("#main").innerHTML = '<div class="blank">' + icon("folder") + '<h2>로컬 저장소 열기</h2><p>Windows 또는 WSL2 환경을 선택하고 작업할 저장소를 여세요.</p><button class="primary" id="open-empty">저장소 열기</button>' + recentList() + '</div>';
    return;
  }
  if (mode === "work") workView();else historyView();
}
async function refresh(next = repo) {
  const changed = next !== repo,
    n = changed ? 150 : limit;
  const data = await api("state", {
    repo: next,
    count: n
  });
  repo = next;
  s = data;
  limit = n;
  if (changed) {
    compareBase = "";
    waitingForEnd = false;
    query = "";
    mode = "history";
    selected = null;
    rev = "";
  }
  if (!rev || !s.commits.some(c => c.id === rev)) rev = s.head || s.commits[0]?.id || "";
  render();
}
function switchMode(value) {
  mode = value;
  selected = null;
  render();
}
function dialog(title, body, ok, fn) {
  $("#dialog-title").textContent = title;
  $("#dialog-body").innerHTML = body;
  $("#confirm").disabled = false;
  $("#confirm").textContent = ok;
  actionPending = fn;
  $("#dialog").showModal();
  ($("#dialog-body input") || $("#cancel")).focus();
}
async function mutation(op, more = {}) {
  try {
    await api("action", {
      op,
      ...more
    });
  } catch (error) {
    if (["switch", "merge", "pull", "apply_stash", "stash_pop", "rebase", "cherry_pick", "flow_finish", "continue", "abort", "merge_commit", "rebase_commit", "revert_commit", "reorder_commits", "cherry_pick_commit"].includes(op)) {
      mode = "work";
      await refresh();
    }
    throw error;
  }
  compareBase = "";
  waitingForEnd = false;
  if (!["stage", "unstage"].includes(op)) rev = "";
  if (op === "commit") {
    drafts.delete(repo);
    rev = "";
    query = "";
    mode = "history";
  }
  await refresh();
  notice({
    stash: "변경을 스태시에 보관했습니다.",
    apply_stash: "스태시를 적용했습니다.",
    merge: "병합을 완료했습니다.",
    commit: "커밋을 만들었습니다.",
    fetch: "페치를 완료했습니다.",
    pull: "풀을 완료했습니다.",
    push: "푸시를 완료했습니다.",
    branch: more.checkout === false ? "새 브랜치를 만들었습니다." : "새 브랜치로 전환했습니다.",
    switch: "브랜치를 전환했습니다."
  }[op] || (["stage", "unstage"].includes(op) ? "스테이징 상태를 변경했습니다." : "작업을 완료했습니다."));
}
async function openDesktop(op, path = repo) {
  notice(op === 'terminal' ? '터미널 창을 여는 중…' : '탐색기 창을 여는 중…', true);
  const result = await api('action', {repo: path, op});
  notice(result?.message || '열기를 요청했습니다. 작업 표시줄을 확인하세요.');
}
function remoteAction(op) {
  if (op === "fetch") return fetchDialog();
  if (!s.branch) return notice("로컬 브랜치를 먼저 체크아웃하세요.", true);
  const local = s.refs.find(r => r.group === "heads" && r.name === s.branch);
  const isPull = op === "pull",
    label = isPull ? "풀" : "푸시";
  const remote = local?.remote || (s.remotes.includes("origin") ? "origin" : s.remotes[0]);
  dialog(label, selectField("sync-remote", "원격 저장소", s.remotes, remote) + textField("sync-target", "원격 브랜치", local?.target || s.branch) + (isPull ? selectField("sync-strategy", "통합 방식", [["ff", "Fast-forward만 허용"], ["merge", "병합"], ["rebase", "리베이스"]]) : info("로컬 " + s.branch + "의 커밋을 푸시하고 업스트림을 설정합니다.")), label, () => mutation(op, {
    remote: valueOf("sync-remote"),
    target: valueOf("sync-target"),
    strategy: isPull ? valueOf("sync-strategy") : undefined
  }));
}
function selectRev(id) {
  mode = "history";
  rev = id;
  if (!$("#rows")) {
    render();
    return;
  }
  chrome();
  drawRows();
  loadDetail();
}
let referenceReveal = 0;
async function revealReference(reference) {
  const serial = ++referenceReveal, expectedRepo = repo, original = s;
  if (!s.commits.some(commit => commit.id === reference.id)) {
    notice(reference.name + '의 커밋 위치를 찾는 중…');
    const located = await api('locate-commit', {rev: reference.id, count: limit});
    const data = await api('state', {count: located.count});
    if (serial !== referenceReveal || repo !== expectedRepo || s !== original) return;
    if (data.head !== original.head || data.branch !== original.branch) return refresh();
    s = data; limit = located.count;
  }
  if (serial !== referenceReveal || repo !== expectedRepo) return;
  query = ''; compareBase = ''; waitingForEnd = false; mode = 'history'; rev = reference.id;
  $('#go-log').className = 'active-nav'; $('#go-work').className = '';
  // Keep sidebar button nodes alive so the second click can produce dblclick.
  document.querySelectorAll('[data-ref]').forEach(button => button.classList.toggle('viewed-ref', s.refs[Number(button.dataset.ref)]?.name === reference.name && s.refs[Number(button.dataset.ref)]?.group === reference.group));
  historyView();
  document.querySelector('.logrow.selected')?.scrollIntoView({block: 'center', behavior: 'smooth'});
}
function clickAction(e) {
  const el = e.target.closest("button");
  if (!el || busy) return;
  const d = el.dataset;
  if (["add", "open-empty"].includes(el.id)) return exclusive(async () => {
    await loadRecent();
    repositoryDialog();
  });
  if (d.recent !== undefined) return exclusive(async () => {
    if ($("#dialog").open) $("#dialog").close();
    const next = await api("open", {path: d.recent, exact: true});
    repos = await api("repos");
    await refresh(next);
  });
  if (d.close !== undefined) return exclusive(async () => {
    const closed = repos[Number(d.close)];
    repos = await api("close", {
      repo: closed
    });
    if (closed === repo && repos.length) await refresh(repos[Math.min(Number(d.close), repos.length - 1)]);else if (!repos.length) {
      repo = "";
      s = null;
      rev = "";
      compareBase = "";
      waitingForEnd = false;
      await loadRecent();
      render();
    } else chrome();
  });
  if (el.id === "partial") return exclusive(() => selected.code === "U" ? conflictDialog() : linesDialog());
  if (el.id === "compare-pin") {
    compareBase = rev;
    waitingForEnd = true;
    historyView();
    return;
  }
  if (el.id === "compare-clear") {
    compareBase = "";
    waitingForEnd = false;
    historyView();
    return;
  }
  if (el.id === "cherry") return dialog("체리픽", info(rev.slice(0, 10) + " 커밋을 현재 HEAD에 적용합니다. 병합 커밋은 첫 부모 기준입니다."), "적용", () => mutation("cherry_pick", {
    rev
  }));
  if (["proceed", "abort"].includes(el.id)) return dialog(s.progress, info("진행 중인 " + s.progress + " 작업을 " + (el.id === "abort" ? "중단" : "계속") + "합니다."), "확인", () => mutation(el.id === "abort" ? "abort" : "continue"));
  if (d.tool === "tag") return tagDialog();
  if (d.tool === "flow") return flowDialog();
  if (d.tool === "remote") return exclusive(openRemoteWebsite);
  if (d.tool === "settings") return exclusive(remotesDialog);
  if (d.tool === "terminal" || d.tool === "folder") return exclusive(() => openDesktop(d.tool === 'folder' ? 'explorer' : 'terminal'));
  if (el.id === "go-log") return switchMode("history");
  if (el.id === "go-work") return switchMode("work");
  if (el.id === "more") {
    limit = Math.min(limit + 250, 5000);
    return exclusive(() => refresh());
  }
  if (d.tab !== undefined) return exclusive(async () => {
    const next = repos[Number(d.tab)];
    await api("select-tab", {repo: next});
    await refresh(next);
  });
  if (d.tool === "refresh") return exclusive(() => refresh());
  if (d.tool === "commit") {
    switchMode("work");
    $("#message").focus();
    return;
  }
  if (d.tool === "branch") return branchDialog();
  if (d.tool === "merge") {
    const opts = s.refs.filter(r => r.group === "heads" && r.name !== s.branch).map(r => '<option>' + esc(r.name) + '</option>').join("");
    return dialog("브랜치 병합", '<p>선택한 브랜치를 현재 브랜치 ' + esc(s.branch) + '에 병합합니다.</p><label>병합할 브랜치<select id="answer">' + opts + '</select></label>', "병합", name => mutation("merge", {
      name
    }));
  }
  if (d.tool === "stash") return dialog("변경 사항 스태시", '<p>스테이징된 변경, 작업 트리 변경, 새 파일을 함께 보관합니다.</p><label>설명 (선택)<input class="form-input" id="answer"></label>', "보관", message => mutation("stash", {
    message
  }));
  if (d.stash !== undefined) return stashDialog(Number(d.stash));
  if (["fetch", "pull", "push"].includes(d.tool)) return remoteAction(d.tool);
  if (d.ref !== undefined) {
    const r = s.refs[Number(d.ref)];
    if (e.detail > 1) return;
    revealReference(r).catch(error => notice(error.message, true));
    return;
  }
  if (d.rev) {
    if (waitingForEnd || e.ctrlKey || e.metaKey || e.shiftKey) {
      compareBase = compareBase || rev;
      if (compareBase === d.rev) {
        compareBase = "";
      }
      waitingForEnd = false;
      rev = d.rev;
      historyView();
    } else if (compareBase) {
      compareBase = "";
      waitingForEnd = false;
      rev = d.rev;
      historyView();
    } else selectRev(d.rev);
    return;
  }
  if (d.fileView !== undefined) {
    treeView = d.fileView === "tree";
    paintFiles();
    $(".file-views [aria-pressed=true]").focus();
    return;
  }
  if (el.id === "expand-diff") return expandDiff();
  if (d.file !== undefined) {
    const next = fileList[Number(d.file)];
    if (selected === next) return;
    selected = next;
    $(".files .file.selected")?.classList.remove("selected");
    el.closest(".file").classList.add("selected");
    showDiff();
    return;
  }
  if (d.toggle !== undefined || d.all) {
    const rows = d.all ? fileList.filter(f => f.kind === d.all) : [fileList[Number(d.toggle)]];
    return exclusive(() => mutation(rows[0].kind === "index" ? "unstage" : "stage", {
      paths: rows.map(r => r.path)
    }));
  }
  if (el.id === "do-commit" && $("#amend")?.checked) return dialog("마지막 커밋 수정", info("현재 HEAD 커밋을 새 메시지와 인덱스 내용으로 교체합니다."), "수정", () => mutation("commit", {
    amend: true,
    message: $("#message").value
  }));
  if (el.id === "do-commit") return exclusive(() => mutation("commit", {
    message: $("#message").value
  }));
}
document.addEventListener("click", clickAction);
$("#diff-popup").addEventListener("close", () => $("#popup-patch").replaceChildren());
document.addEventListener("dblclick", event => {
  const button = event.target.closest('button[data-ref]');
  if (button && !busy && !document.querySelector('dialog[open]')) {
    const ref = s.refs[Number(button.dataset.ref)];
    if (ref?.group === 'heads') exclusive(() => branchSwitchDialog(ref.name));
    return;
  }
  if (!busy && event.target.closest("button[data-file]")) expandDiff();
});
document.addEventListener("input", e => {
  if (e.target.id === "search") {
    query = e.target.value;
    drawRows();
  }
  if (e.target.id === "amend") enableCommit();
  if (e.target.id === "message") {
    drafts.set(repo, e.target.value);
    enableCommit();
  }
});
document.addEventListener("toggle", e => {
  if (e.target.dataset?.group) {
    if (e.target.open) collapsed.delete(e.target.dataset.group);else collapsed.add(e.target.dataset.group);
  }
}, true);
$("#cancel").onclick = () => $("#dialog").close();
$("#form").onsubmit = e => {
  e.preventDefault();
  const value = $("#answer")?.value || "";
  $("#dialog").close();
  exclusive(() => actionPending(value));
};
exclusive(async () => {
  const workspace = await api("workspace");
  const resume = await api('app-update', {action: 'restore'});
  for (const [path, message] of resume.drafts || []) if (typeof path === 'string' && typeof message === 'string') drafts.set(path, message);
  repos = workspace.repos;
  if (!repos.length) await loadRecent();
  if (repos.length) {
    await refresh(repos.includes(resume.repo) ? resume.repo : workspace.active || repos[0]);
    if (resume.mode === 'work') switchMode('work');
  } else render();
});

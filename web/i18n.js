// Translate UI-owned literals only. Repository data and Git output stay untouched.
let uiLanguage = 'ko', uiCatalog = {}, uiKeys = [], staticUiNodes = [];
function T(key, values) {
  let result = uiLanguage === 'ko' ? key : (uiCatalog[uiLanguage]?.[key] ?? key);
  if (values) result = result.replace(/\{(\w+)\}/g, (all, name) => String(values[name] ?? all));
  return result;
}
function L(literal) {
  if (uiLanguage === 'ko' || typeof literal !== 'string') return literal;
  if (uiCatalog[uiLanguage]?.[literal] !== undefined) return T(literal);
  // Only source-code literals enter this function, never interpolated user data.
  let value = literal;
  for (const key of uiKeys) if (value.includes(key)) value = value.split(key).join(T(key));
  return value;
}
function translatedMessage(message) {
  if (typeof message !== 'string' || uiLanguage === 'ko') return message;
  if (uiCatalog[uiLanguage]?.[message] !== undefined) return T(message);
  const trimmed = message.trim();
  if (uiCatalog[uiLanguage]?.[trimmed] !== undefined) return message.replace(trimmed, T(trimmed));
  // Translate app-owned prefixes, retaining appended Git/system details verbatim.
  for (const key of uiKeys) {
    if (key.length >= 12 && trimmed.startsWith(key)) return message.replace(key, T(key));
  }
  for (const key of ['을 확인하세요.', ' 실행 파일을 찾지 못했습니다.']) {
    if (message.endsWith(key)) return message.slice(0, -key.length) + T(key);
  }
  return message;
}
function captureStaticUi() {
  const walker = document.createTreeWalker(document.body, NodeFilter.SHOW_TEXT);
  let node;
  while ((node = walker.nextNode())) {
    if (node.parentElement.closest('[data-no-i18n],script,style')) continue;
    if (/[가-힣]/.test(node.nodeValue)) staticUiNodes.push({node, original: node.nodeValue});
  }
  for (const element of document.querySelectorAll('[title],[placeholder],[aria-label]')) {
    if (element.closest('[data-no-i18n]')) continue;
    for (const attribute of ['title','placeholder','aria-label']) {
      const original = element.getAttribute(attribute);
      if (original && /[가-힣]/.test(original)) staticUiNodes.push({node: element, attribute, original});
    }
  }
}
function paintStaticUi() {
  document.documentElement.lang = uiLanguage;
  document.title = 'Branchdesk · ' + T('Git 워크스페이스');
  for (const item of staticUiNodes) {
    if (!item.node.isConnected) continue;
    if (item.attribute) item.node.setAttribute(item.attribute, L(item.original));
    else item.node.nodeValue = L(item.original);
  }
  document.querySelector('#language-select').value = uiLanguage;
  document.querySelector('#language-select').setAttribute('aria-label', T('언어 선택'));
}
async function initializeLanguage() {
  const response = await fetch('/i18n.json');
  if (!response.ok) throw new Error('Cannot load UI translations.');
  uiCatalog = await response.json();
  uiKeys = Object.keys(uiCatalog.en).sort((a, b) => b.length - a.length);
  captureStaticUi();
  const preference = await api('language');
  uiLanguage = preference.language;
  paintStaticUi();
  document.querySelector('#language-select').onchange = async event => {
    const select = event.target, previous = uiLanguage;
    if (busy || document.querySelector('dialog[open]')) { select.value = previous; return; }
    select.disabled = true;
    try {
      await api('language', {action: 'save', language: select.value});
      uiLanguage = select.value;
      paintStaticUi();
      document.querySelector('#toast').hidden = true;
      const scroll = document.querySelector('.history')?.scrollTop;
      render();
      document.querySelector('#foot-status').textContent = T('로컬 Git');
      if (scroll !== undefined && document.querySelector('.history')) document.querySelector('.history').scrollTop = scroll;
      if (typeof paintAppUpdate === 'function') paintAppUpdate();
    } catch (error) { select.value = previous; notice(error.message, true); }
    finally { select.disabled = false; }
  };
}

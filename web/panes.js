// Separators resize their two adjacent panes without intercepting wheel scrolling.
const paneLabels = {nav: '사이드바 너비', history: '커밋 그래프 높이', files: '변경 파일 영역 크기'};
const narrowPanes = matchMedia('(max-width: 680px)');
function verticalSplit(name) {
  return name === 'history' || (name === 'files' && narrowPanes.matches);
}
function separator(name) {
  const orientation = verticalSplit(name) ? 'horizontal' : 'vertical';
  return '<div class="pane-divider" data-pane="' + name + '" role="separator" tabindex="0" aria-label="' +
    paneLabels[name] + '" aria-orientation="' + orientation + '"></div>';
}
function paneMetrics(divider) {
  const first = divider.previousElementSibling.getBoundingClientRect();
  const second = divider.nextElementSibling.getBoundingClientRect();
  const size = verticalSplit(divider.dataset.pane) ? 'height' : 'width';
  const total = first[size] + second[size];
  return {total, ratio: total ? first[size] / total : 0.5};
}
function sizePane(divider, ratio) {
  const name = divider.dataset.pane;
  const percent = Math.round(Math.max(0.12, Math.min(name === 'nav' ? 0.55 : 0.85, ratio)) * 100);
  const variable = name === 'files' && narrowPanes.matches ? 'files-stacked' : name;
  document.documentElement.style.setProperty('--' + variable + '-size', percent + '%');
  divider.setAttribute('aria-valuenow', percent);
}
document.addEventListener('pointerdown', event => {
  const divider = event.target.closest('.pane-divider');
  if (!divider || event.button !== 0) return;
  event.preventDefault();
  divider.focus();
  const axis = verticalSplit(divider.dataset.pane) ? 'clientY' : 'clientX';
  const start = event[axis], {total, ratio} = paneMetrics(divider);
  if (!total) return;
  divider.setPointerCapture(event.pointerId);
  divider.onpointermove = moved => sizePane(divider, ratio + (moved[axis] - start) / total);
  divider.onlostpointercapture = () => { divider.onpointermove = null; };
});
document.addEventListener('keydown', event => {
  const divider = event.target.closest('.pane-divider');
  if (!divider) return;
  const vertical = verticalSplit(divider.dataset.pane);
  const direction = vertical ? ['ArrowUp', 'ArrowDown'] : ['ArrowLeft', 'ArrowRight'];
  if (!direction.includes(event.key)) return;
  event.preventDefault();
  sizePane(divider, paneMetrics(divider).ratio + (event.key === direction[0] ? -0.04 : 0.04));
});
document.addEventListener('focusin', event => {
  if (event.target.matches('.pane-divider')) {
    event.target.setAttribute('aria-valuenow', Math.round(paneMetrics(event.target).ratio * 100));
  }
});
narrowPanes.addEventListener('change', () => {
  for (const el of document.querySelectorAll('[data-pane="files"]'))
    el.setAttribute('aria-orientation', verticalSplit('files') ? 'horizontal' : 'vertical');
});

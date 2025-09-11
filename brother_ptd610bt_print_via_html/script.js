/**
 * Very basic HTML safety/validity check for injecting into #labels.
 * - Parses into a DocumentFragment.
 * - Rejects dangerous tags.
 * - Requires at least one element with class ".label".
 * Returns { ok:boolean, node?:DocumentFragment, reason?:string }
 */
function validateLabelHTML(html) {
  const tpl = document.createElement('template');
  tpl.innerHTML = html;

  // Disallow obviously dangerous elements
  if (tpl.content.querySelector('script, iframe, object, embed, link[rel="import"], meta, base')) {
    return { ok: false, reason: 'HTML contains disallowed elements (script/iframe/etc.)' };
    }

  // Require at least one .label
  if (!tpl.content.querySelector('.label')) {
    return { ok: false, reason: 'No element with class ".label" found.' };
  }

  return { ok: true, node: tpl.content };
}

/* Hook up controls */
const heightSel = document.getElementById('heightSel');
const widthNum  = document.getElementById('widthNum');
const htmlBox   = document.getElementById('htmlBox');
const labelsDiv = document.getElementById('labels');
const statusEl  = document.getElementById('status');

heightSel.addEventListener('change', () => {
  // values are like "12mm", "24mm" — include units
  setLabelHeight(heightSel.value);
});

widthNum.addEventListener('change', () => {
  const n = Number(widthNum.value);
  if (Number.isFinite(n) && n >= 1 && n <= 8) {
    setLabelWidth(`${n}in`);
    statusEl.textContent = '';
    statusEl.className = '';
  } else {
    statusEl.textContent = 'Width must be between 1 and 8 inches.';
    statusEl.className = 'err';
  }
});

htmlBox.addEventListener('input', () => {
  const raw = htmlBox.value.trim();
  if (!raw) {
    statusEl.textContent = 'Textbox is empty — preview unchanged.';
    statusEl.className = '';
    return;
  }
  const res = validateLabelHTML(raw);
  if (res.ok) {
    // Replace labels with validated fragment
    labelsDiv.replaceChildren(res.node);
    statusEl.textContent = 'HTML applied.';
    statusEl.className = 'ok';
  } else {
    statusEl.textContent = `Invalid HTML: ${res.reason}`;
    statusEl.className = 'err';
  }
});
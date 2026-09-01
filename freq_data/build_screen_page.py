#!/usr/bin/env python3
"""Build the vocabulary screening page for one book.

The deck evaluation counts words the Anki collection has no card for. That is not the
same as words Vincent does not know — 一个, 不是 and 这种 top the list, and he plainly
knows them. Only he can separate the two, so this makes that judgement fast: every word
is a tile, a tap marks it known, and the page saves itself with the answers embedded.

    build_screen_page.py <words.json> <out.html> "<book>"

Reads the records written by the screening query: w, n, py, m, z, c.
"""
import json
import sys
from pathlib import Path

CSS = """
:root{
  --paper:#faf8f5; --raised:#ffffff; --ink:#1c1d21; --muted:#6f6a63; --faint:#938d84;
  --line:#e4dfd7; --jade:#2f7d5f; --jade-soft:#e9f1ec; --jade-line:#b9d5c6;
  --shadow:0 1px 2px rgba(28,29,33,.06);
}
@media (prefers-color-scheme:dark){
  :root:not([data-theme="light"]){
    --paper:#16171a; --raised:#1d1f23; --ink:#ececef; --muted:#9a958e; --faint:#78736c;
    --line:#2c2e33; --jade:#6dbb97; --jade-soft:#1b2a23; --jade-line:#335645;
    --shadow:0 1px 2px rgba(0,0,0,.4);
  }
}
:root[data-theme="dark"]{
  --paper:#16171a; --raised:#1d1f23; --ink:#ececef; --muted:#9a958e; --faint:#78736c;
  --line:#2c2e33; --jade:#6dbb97; --jade-soft:#1b2a23; --jade-line:#335645;
  --shadow:0 1px 2px rgba(0,0,0,.4);
}
*{box-sizing:border-box}
body{
  background:var(--paper); color:var(--ink); margin:0;
  font-family:Archivo,-apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif;
  font-size:15px; line-height:1.5; -webkit-font-smoothing:antialiased;
}
.zh{font-family:"PingFang SC","Hiragino Sans GB","Microsoft YaHei","Noto Sans CJK SC",
     "Source Han Sans SC",sans-serif}
.wrap{max-width:1180px; margin:0 auto; padding:0 20px 72px}

header{padding:38px 0 20px}
h1{font-family:Newsreader,Georgia,serif; font-weight:500; font-size:2.1rem;
   letter-spacing:-.01em; margin:0 0 6px; text-wrap:balance}
h1 .zh{font-weight:600}
.lede{color:var(--muted); max-width:60ch; margin:0}

.bar{
  position:sticky; top:0; z-index:10; background:var(--paper);
  border-bottom:1px solid var(--line); padding:12px 0 13px; margin-bottom:22px;
}
.bar-in{display:flex; flex-wrap:wrap; gap:16px 22px; align-items:center}
.tally{display:flex; align-items:baseline; gap:8px; font-family:Newsreader,Georgia,serif}
.tally b{font-size:1.9rem; font-weight:500; font-variant-numeric:tabular-nums;
         color:var(--jade); line-height:1}
.tally span{color:var(--muted); font-family:Archivo,sans-serif; font-size:.85rem}
.grp{display:flex; align-items:center; gap:7px}
.lbl{font-size:.68rem; text-transform:uppercase; letter-spacing:.09em; color:var(--faint)}
select,button{font:inherit; color:var(--ink); background:var(--raised);
  border:1px solid var(--line); border-radius:7px; padding:6px 11px; cursor:pointer}
select{font-size:.85rem}
button:hover{border-color:var(--jade)}
button.primary{background:var(--jade); border-color:var(--jade); color:#fff; font-weight:600}
button.primary:hover{filter:brightness(1.08)}
button:disabled{opacity:.5; cursor:default}
:focus-visible{outline:2px solid var(--jade); outline-offset:2px}
input[type=range]{accent-color:var(--jade); width:150px}

.grid{display:grid; gap:10px; grid-template-columns:repeat(auto-fill,minmax(168px,1fr))}
.tile{
  position:relative; text-align:left; padding:11px 12px 10px; border-radius:9px;
  background:var(--raised); border:1px solid var(--line); box-shadow:var(--shadow);
  cursor:pointer; transition:background .12s, border-color .12s;
}
.tile:hover{border-color:var(--jade-line)}
.tile[aria-pressed="true"]{background:var(--jade-soft); border-color:var(--jade-line)}
.tile .w{font-size:1.5rem; line-height:1.2; letter-spacing:.01em}
.tile[aria-pressed="true"] .w{color:var(--jade)}
.tile .py{font-size:.78rem; color:var(--muted); margin-top:2px}
.tile .m{font-size:.75rem; color:var(--faint); margin-top:4px; line-height:1.35;
  display:-webkit-box; -webkit-line-clamp:2; -webkit-box-orient:vertical; overflow:hidden}
.tile .n{position:absolute; top:10px; right:11px; font-family:Newsreader,Georgia,serif;
  font-size:.9rem; color:var(--faint); font-variant-numeric:tabular-nums}
.tile[aria-pressed="true"] .n{color:var(--jade)}
.zbar{margin-top:8px; height:3px; border-radius:2px; background:var(--line); overflow:hidden}
.zbar i{display:block; height:100%; background:var(--faint)}
.tile[aria-pressed="true"] .zbar i{background:var(--jade)}
.nocard{position:absolute; bottom:9px; right:11px; font-size:.6rem; letter-spacing:.07em;
  text-transform:uppercase; color:var(--faint)}

.note{margin:26px 0 0; color:var(--muted); font-size:.85rem; max-width:62ch}
.toast{position:fixed; left:50%; bottom:22px; transform:translateX(-50%);
  background:var(--ink); color:var(--paper); padding:9px 18px; border-radius:999px;
  font-size:.85rem; opacity:0; pointer-events:none; transition:opacity .2s}
.toast.on{opacity:1}
@media (prefers-reduced-motion:reduce){*{transition:none!important}}
"""

APP = r"""
const DATA = JSON.parse(document.getElementById('data').textContent);
const state = JSON.parse(document.getElementById('state').textContent);
const known = new Set(state.known || []);
const LS = 'shinian-screen';
try{ const s = localStorage.getItem(LS);
     if(s && !known.size) JSON.parse(s).forEach(w=>known.add(w)); }catch(e){}

const grid = document.getElementById('grid');
const sortSel = document.getElementById('sort');
const sweep = document.getElementById('sweep');
const sweepOut = document.getElementById('sweepOut');
const saveBtn = document.getElementById('save');
const tally = document.getElementById('tally');
let artifact = null;

const ZMIN = 1.5, ZMAX = 6.6;
const pct = z => Math.max(0, Math.min(100, ((z - ZMIN) / (ZMAX - ZMIN)) * 100));

function order(){
  const v = sortSel.value, a = DATA.slice();
  if(v === 'freq')   a.sort((x,y)=> y.n - x.n);
  if(v === 'common') a.sort((x,y)=> y.z - x.z);
  if(v === 'rare')   a.sort((x,y)=> x.z - y.z);
  if(v === 'todo')   a.sort((x,y)=> (known.has(x.w)-known.has(y.w)) || (y.n - x.n));
  return a;
}

function render(){
  grid.replaceChildren(...order().map(d=>{
    const b = document.createElement('button');
    b.className = 'tile'; b.type = 'button';
    b.setAttribute('aria-pressed', known.has(d.w) ? 'true' : 'false');
    b.innerHTML =
      '<div class="n">' + d.n + '</div>' +
      '<div class="w zh"></div>' +
      '<div class="py"></div>' +
      '<div class="m"></div>' +
      '<div class="zbar"><i style="width:' + pct(d.z).toFixed(0) + '%"></i></div>' +
      (d.c === 'none' ? '<div class="nocard">no card</div>' : '');
    b.querySelector('.w').textContent = d.w;
    b.querySelector('.py').textContent = d.py || '—';
    b.querySelector('.m').textContent = d.m || '';
    b.addEventListener('click', ()=>{
      known.has(d.w) ? known.delete(d.w) : known.add(d.w);
      b.setAttribute('aria-pressed', known.has(d.w) ? 'true' : 'false');
      count(); persist();
    });
    return b;
  }));
  count();
}

function count(){
  tally.innerHTML = '<b>' + known.size + '</b><span>of ' + DATA.length +
    ' marked known — ' + (DATA.length - known.size) + ' left to study</span>';
}
function persist(){ try{ localStorage.setItem(LS, JSON.stringify([...known])); }catch(e){} }

sortSel.addEventListener('change', render);
sweep.addEventListener('input', ()=>{
  const z = +sweep.value / 10;
  sweepOut.textContent = z.toFixed(1) + ' — ' + DATA.filter(d=>d.z >= z).length + ' words';
});
document.getElementById('applySweep').addEventListener('click', ()=>{
  const z = +sweep.value / 10;
  DATA.forEach(d=>{ if(d.z >= z) known.add(d.w); });
  persist(); render(); toast('Marked every word at ' + z.toFixed(1) + ' or commoner');
});
document.getElementById('clear').addEventListener('click', ()=>{
  known.clear(); persist(); render(); toast('Cleared');
});

let toastT;
function toast(msg){
  const t = document.getElementById('toast');
  t.textContent = msg; t.classList.add('on');
  clearTimeout(toastT); toastT = setTimeout(()=>t.classList.remove('on'), 2200);
}

// The published document is the shell plus the answers — the tiles are rebuilt from
// state on load, so the emptied container is what gets saved, never the live DOM.
function buildDoc(){
  const root = document.documentElement.cloneNode(true);
  root.querySelector('#grid').innerHTML = '';
  root.querySelector('#toast').className = 'toast';
  root.querySelector('#state').textContent =
    JSON.stringify({known:[...known], updated:new Date().toISOString()});
  return '<!doctype html>\n' + root.outerHTML;
}

saveBtn.addEventListener('click', async ()=>{
  if(!artifact){ toast('Saving is not available in this view'); return; }
  saveBtn.disabled = true; saveBtn.textContent = 'Saving…';
  try{
    await artifact.publish(buildDoc());
    toast('Saved — Claude can read your answers now');
  }catch(e){
    toast(e && e.code === 'conflict' ? 'Someone saved first — reload' : 'Could not save');
  }finally{ saveBtn.disabled = false; saveBtn.textContent = 'Save answers'; }
});

render();
sweep.dispatchEvent(new Event('input'));
claude.use('artifact').then(a=>{
  artifact = a;
  if(!a){ saveBtn.title = 'This view cannot save'; }
});
"""


def main():
    words = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
    out = Path(sys.argv[2])
    book = sys.argv[3] if len(sys.argv) > 3 else "the book"
    nocard = sum(1 for w in words if w["c"] == "none")
    html = f"""<title>Ten Years Word Screen</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=Archivo:wght@400;500;600&family=Newsreader:wght@400;500&display=swap">
<style>{CSS}</style>

<div class="wrap">
  <header>
    <h1>Which of these do you already know?</h1>
    <p class="lede">Every word below appears <strong>5 times or more</strong> in
      <span class="zh">《{book}》</span> and has no studied card in your collection.
      {len(words)} words, {nocard} of them with no card at all.
      Tap the ones you already read without help. What is left becomes the deck.</p>
  </header>

  <div class="bar"><div class="bar-in">
    <div class="tally" id="tally"></div>
    <div class="grp">
      <span class="lbl">Sort</span>
      <select id="sort">
        <option value="freq">Times in the book</option>
        <option value="common">Commonest first</option>
        <option value="rare">Rarest first</option>
        <option value="todo">Unmarked first</option>
      </select>
    </div>
    <div class="grp">
      <span class="lbl">Sweep</span>
      <input type="range" id="sweep" min="15" max="66" value="50" step="1"
             aria-label="Commonness threshold">
      <span class="lbl" id="sweepOut" style="min-width:104px"></span>
      <button id="applySweep">Mark them</button>
    </div>
    <div class="grp" style="margin-left:auto">
      <button id="clear">Clear</button>
      <button id="save" class="primary">Save answers</button>
    </div>
  </div></div>

  <div class="grid" id="grid"></div>

  <p class="note">The bar under each word is how common it is in everyday Chinese.
    A long bar means you almost certainly know it. Sweep marks everything at or above a
    threshold in one go, then correct by hand. Your answers save in this browser as you
    go; press <strong>Save answers</strong> when you are done so I can read them.</p>
</div>

<div class="toast" id="toast"></div>

<script id="data" type="application/json">{json.dumps(words, ensure_ascii=False)}</script>
<script id="state" type="application/json">{{"known":[]}}</script>
<script>{APP}</script>
"""
    out.write_text(html, encoding="utf-8")
    print(f"{len(words)} words -> {out} ({out.stat().st_size:,} bytes)")


if __name__ == "__main__":
    main()

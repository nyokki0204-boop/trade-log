import { validateTrades, validateAssets, prepareAssets, tradeMetrics, legacyCSV, validateBundle } from './model.mjs';

const $ = (id) => document.getElementById(id);
const el = (tag, className, value) => { const node = document.createElement(tag); if (className) node.className = className; if (value !== undefined) node.textContent = value; return node; };
const today = () => { const now = new Date(); return `${now.getFullYear()}-${String(now.getMonth() + 1).padStart(2, '0')}-${String(now.getDate()).padStart(2, '0')}`; };
const money = (value, currency = 'JPY') => new Intl.NumberFormat('ja-JP', { style: 'currency', currency, maximumFractionDigits: currency === 'JPY' ? 0 : 2 }).format(value);
const signed = (value, currency) => `${value > 0 ? '+' : ''}${money(value, currency)}`;
const pct = (value) => `${value > 0 ? '+' : ''}${value.toFixed(2)}%`;
const empty = (node) => node.replaceChildren();
let state = { trades: [], assets: [], changedAt: null, backedUpAt: null };
let pendingBundle = null, pendingLegacy = null;
const channel = 'BroadcastChannel' in window ? new BroadcastChannel('trade-log-updates') : null;

function openDB() {
  return new Promise((resolve, reject) => {
    const request = indexedDB.open('trade-log-local', 1);
    request.onupgradeneeded = () => request.result.createObjectStore('app');
    request.onsuccess = () => resolve(request.result);
    request.onerror = () => reject(request.error);
  });
}
async function dbRead() {
  const db = await openDB();
  try { return await new Promise((resolve, reject) => {
    const tx = db.transaction('app', 'readonly');
    const request = tx.objectStore('app').get('state');
    request.onsuccess = () => resolve(request.result);
    request.onerror = () => reject(request.error);
  }); } finally { db.close(); }
}
async function dbWrite(next) {
  const db = await openDB();
  try { await new Promise((resolve, reject) => {
    const tx = db.transaction('app', 'readwrite');
    tx.objectStore('app').put(next, 'state');
    tx.oncomplete = resolve;
    tx.onabort = () => reject(tx.error || new Error('端末への保存に失敗しました'));
    tx.onerror = () => reject(tx.error || new Error('端末への保存に失敗しました'));
  }); } finally { db.close(); }
}
async function save(next, changed = true) {
  const valid = { trades: validateTrades(next.trades), assets: validateAssets(next.assets), changedAt: changed ? new Date().toISOString() : next.changedAt, backedUpAt: next.backedUpAt ?? null };
  await dbWrite(valid); state = valid; channel?.postMessage('updated'); render();
}
function toast(message) { const node = $('toast'); node.textContent = message; node.style.display = 'block'; clearTimeout(toast.timer); toast.timer = setTimeout(() => node.style.display = 'none', 4500); }
function report(error) { console.error(error); toast(error?.message || '操作に失敗しました'); }
function nav(name) { document.querySelectorAll('.view').forEach(v => v.classList.toggle('active', v.id === `view-${name}`)); document.querySelectorAll('.bottom-nav button').forEach(b => b.classList.toggle('selected', b.dataset.nav === name)); window.scrollTo(0, 0); }
function stat(label, value) { const node = el('div', 'stat'); node.append(el('div', 'muted', label), el('div', 'value', value)); return node; }
function summary(data) {
  if (!data.length) return null;
  const winners = data.filter(x => tradeMetrics(x).pnl > 0), losers = data.filter(x => tradeMetrics(x).pnl < 0);
  const wins = winners.reduce((sum, x) => sum + tradeMetrics(x).pnl, 0);
  const losses = -losers.reduce((sum, x) => sum + tradeMetrics(x).pnl, 0);
  const rs = data.map(x => tradeMetrics(x).r).filter(x => x !== null);
  return { count: data.length, rate: winners.length / data.length * 100, avg: data.reduce((sum, x) => sum + tradeMetrics(x).pnl, 0) / data.length, pf: losses ? (wins / losses).toFixed(2) : wins ? '∞' : '—', r: rs.length ? (rs.reduce((a, b) => a + b, 0) / rs.length).toFixed(2) : '—' };
}
function tradeCard(row) {
  const m = tradeMetrics(row), card = el('article', 'item');
  const head = el('div', 'item-head'), left = el('strong', '', row.ticker), right = el('span', m.pnl === null ? 'pill' : m.pnl < 0 ? 'negative' : 'positive', m.pnl === null ? '保有中' : pct(m.pnl));
  head.append(left, right);
  card.append(head, el('small', '', `#${row.id} · ${row.entry_date} · ${row.type}/${row.direction} · ${row.entry_price} → ${row.exit_price ?? '保有中'}`));
  if (row.tag || row.memo) card.append(el('p', '', [row.tag && `#${row.tag}`, row.memo].filter(Boolean).join('  ')));
  return card;
}
function chart(node, rows, field, currency) {
  empty(node);
  if (!rows.length) { node.append(el('p', 'hint', '資産を記録すると推移が表示されます。')); return; }
  const width = 620, height = 180, pad = 20;
  const values = rows.map(x => x[field]), min = Math.min(...values), max = Math.max(...values), span = max - min || Math.max(Math.abs(max) * .1, 1);
  const x = i => pad + i * (width - 2 * pad) / Math.max(rows.length - 1, 1);
  const y = value => height - pad - (value - min) / span * (height - 2 * pad);
  const svgNS = 'http://www.w3.org/2000/svg', svg = document.createElementNS(svgNS, 'svg'); svg.setAttribute('viewBox', `0 0 ${width} ${height}`); svg.setAttribute('role', 'img'); svg.setAttribute('aria-label', `総資産の推移 ${rows.map(x => `${x.date}: ${money(x[field], currency)}`).join('、')}`);
  const line = document.createElementNS(svgNS, 'line'); for (const [key, val] of Object.entries({ x1:pad, x2:width-pad, y1:height-pad, y2:height-pad })) line.setAttribute(key, val); svg.append(line);
  const poly = document.createElementNS(svgNS, 'polyline'); poly.setAttribute('points', rows.map((row, i) => `${x(i)},${y(row[field])}`).join(' ')); svg.append(poly);
  rows.forEach((row, i) => { const circle = document.createElementNS(svgNS, 'circle'); circle.setAttribute('cx', x(i)); circle.setAttribute('cy', y(row[field])); circle.setAttribute('r', '3'); svg.append(circle); });
  node.append(svg, el('div', 'hint', `${rows[0].date} — ${rows.at(-1).date}　${money(min, currency)} ～ ${money(max, currency)}`));
}
function renderHome(prepared) {
  const latest = prepared.at(-1), currency = latest?.currency || 'JPY';
  $('home-total').textContent = latest ? money(latest.total_assets, currency) : '未記録';
  $('home-operating').textContent = latest ? `入出金を除いた増減 ${signed(latest.cumulative_operating_change, currency)}` : '資産タブから最初の金額を登録';
  const reminder = $('backup-reminder');
  reminder.classList.toggle('hidden', !state.changedAt || state.changedAt <= (state.backedUpAt || ''));
  reminder.textContent = '記録が更新されました。引き継ぎタブでバックアップを保存してください。';
  const closed = state.trades.filter(x => x.exit_price !== null), open = state.trades.length - closed.length, stats = summary(closed);
  $('home-stats').replaceChildren(stat('保有中', `${open}件`), stat('決済済み', `${closed.length}件`), stat('勝率', stats ? `${stats.rate.toFixed(0)}%` : '—'), stat('平均損益率', stats ? pct(stats.avg) : '—'));
  const recent = $('home-recent'); recent.replaceChildren(...[...state.trades].sort((a,b) => b.id - a.id).slice(0,3).map(tradeCard));
  if (!state.trades.length) recent.append(el('p','hint','取引の記録はまだありません。'));
  $('past-tags').replaceChildren(...[...new Set(state.trades.map(x => x.tag).filter(Boolean))].map(tag => { const option = el('option'); option.value = tag; return option; }));
}
function renderTrades() {
  const filter = $('trade-filter').value, list = $('trade-list'); empty(list);
  const rows = [...state.trades].sort((a,b) => b.id - a.id).filter(row => filter === 'all' || filter === 'open' && row.exit_price === null || filter === 'closed' && row.exit_price !== null || row.type === filter);
  if (!rows.length) list.append(el('p','hint','該当する取引はありません。'));
  for (const row of rows) {
    const card = tradeCard(row), actions = el('div','row-actions');
    const edit = el('button','',row.exit_price === null ? '決済する' : '決済を修正'); edit.type = 'button';
    edit.addEventListener('click', () => showTradeEditor(card, row));
    const remove = el('button','danger','削除'); remove.type = 'button'; remove.addEventListener('click', async () => {
      if (!confirm(`#${row.id} ${row.ticker} を削除しますか？`)) return;
      try { await save({ ...state, trades: state.trades.filter(x => x.id !== row.id) }); toast('取引を削除しました'); } catch (e) { report(e); }
    }); actions.append(edit,remove); card.append(actions); list.append(card);
  }
  const analysis = $('analysis'); empty(analysis);
  const closed = state.trades.filter(x => x.exit_price !== null);
  for (const [label, rows] of [['全体',closed],['現物',closed.filter(x => x.type === '現物')],['CFD',closed.filter(x => x.type === 'CFD')]]) {
    const s = summary(rows), card = el('div','item'); card.append(el('strong','',label),el('p','',s ? `${s.count}件 · 勝率 ${s.rate.toFixed(0)}% · 平均損益 ${pct(s.avg)} · PF ${s.pf} · 平均R ${s.r}` : '決済済みなし')); analysis.append(card);
  }
  const groups = new Map(); closed.forEach(row => { if (!row.tag.trim()) return; const key = row.tag.trim(); groups.set(key, [...(groups.get(key) || []), row]); });
  if (groups.size) { const card = el('div','item'); card.append(el('strong','','タグ別')); for (const [key, rows] of groups) { const s = summary(rows); card.append(el('p','',`${key}：${s.count}件 · 勝率 ${s.rate.toFixed(0)}% · 平均 ${pct(s.avg)}`)); } analysis.append(card); }
}
function showTradeEditor(card, row) {
  card.querySelector('.inline-form')?.remove(); const form = el('form','inline-form');
  const price = el('input'); price.type='number'; price.step='any'; price.min='0'; price.required=true; price.placeholder='決済価格'; price.value=row.exit_price ?? '';
  const day = el('input'); day.type='date'; day.required=true; day.value=row.exit_date || today();
  const submit=el('button','secondary','決済を保存'); submit.type='submit'; form.append(el('label','','決済価格'),price,el('label','','決済日'),day,submit);
  form.addEventListener('submit',async event => { event.preventDefault(); try { const updated = { ...row, exit_price: price.value, exit_date: day.value }; await save({ ...state, trades: state.trades.map(x => x.id === row.id ? updated : x) }); toast('決済を保存しました'); } catch(e) { report(e); } }); card.append(form);
}
function renderAssets(prepared) {
  const latest = prepared.at(-1), currency = latest?.currency || 'JPY', summaryNode = $('asset-summary'); empty(summaryNode);
  if (latest) {
    const first = prepared[0], totalFlow = prepared.reduce((sum,x) => sum + x.net_flow, 0);
    summaryNode.append(stat('現在の総資産',money(latest.total_assets,currency)),stat('総資産の増減',signed(latest.asset_change,currency)),stat('入出金を除いた増減',signed(latest.cumulative_operating_change,currency)),el('p','hint',`基準日 ${first.date} · 基準額 ${money(first.total_assets,currency)} · 累計入出金 ${signed(totalFlow,currency)}。入出金を除いた増減＝現在額−基準額−累計入出金。`));
  } else summaryNode.append(el('p','hint','まず基準となる総資産額を登録してください。'));
  chart($('asset-chart'), prepared, 'total_assets', currency);
  $('currency-wrap').classList.toggle('hidden', Boolean(latest)); $('flow-wrap').classList.toggle('hidden', !latest);
  const list=$('asset-list'); empty(list);
  for(const row of [...prepared].reverse()) {
    const card=el('article','item'); card.append(el('div','item-head'),el('small','',row.date)); card.firstChild.append(el('strong','',money(row.total_assets,currency)),el('span',row.operating_change<0?'negative':'positive',signed(row.operating_change,currency)));
    card.append(el('p','',`入出金 ${signed(row.net_flow,currency)}${row.memo ? ` · ${row.memo}` : ''}`));
    if(row.date===latest.date) {
      const actions=el('div','row-actions'), edit=el('button','','最新を修正'), remove=el('button','danger','最新を取り消す'); edit.type=remove.type='button';
      edit.addEventListener('click',()=>showAssetEditor(card,row)); remove.addEventListener('click',async()=>{
        if(!confirm(`${row.date} の最新記録を取り消しますか？`)) return;
        try { await save({...state,assets:state.assets.filter(x=>x.date!==row.date)}); toast('最新記録を取り消しました'); } catch(e){report(e);}
      }); actions.append(edit,remove); card.append(actions);
    } list.append(card);
  }
}
function showAssetEditor(card,row) {
  card.querySelector('.inline-form')?.remove(); const form=el('form','inline-form');
  const input=(label,value)=>{const wrap=el('label','',label), field=el('input'); field.type='number';field.step='any';field.value=value;field.required=true;wrap.append(field);return [wrap,field];};
  const [totalLabel,total]=input('総資産',row.total_assets),[flowLabel,flow]=input('入出金',row.net_flow);total.min='0';if(state.assets.length===1){flow.value='0';flow.disabled=true;}
  const memoLabel=el('label','','メモ'),memo=el('input');memo.value=row.memo;memoLabel.append(memo);
  const submit=el('button','secondary','修正を保存');submit.type='submit';form.append(totalLabel,flowLabel,memoLabel,submit);
  form.addEventListener('submit',async event=>{event.preventDefault();try{await save({...state,assets:state.assets.map(x=>x.date===row.date?{...x,total_assets:total.value,net_flow:flow.value,memo:memo.value}:x)});toast('資産額を修正しました');}catch(e){report(e);}});card.append(form);
}
function render() {
  const prepared=prepareAssets(state.assets);renderHome(prepared);renderTrades();renderAssets(prepared);
  $('last-backup').textContent=state.backedUpAt?`最後の書き出し操作: ${new Date(state.backedUpAt).toLocaleString('ja-JP')}`:'バックアップはまだ書き出していません。';
}

document.querySelectorAll('[data-nav]').forEach(button=>button.addEventListener('click',()=>nav(button.dataset.nav)));
$('trade-filter').addEventListener('change',renderTrades);
$('trade-form').elements.entry_date.value=today();$('asset-form').elements.date.value=today();
$('trade-form').elements.type.addEventListener('change',event=>{const direction=$('trade-form').elements.direction;direction.disabled=event.target.value==='現物';if(direction.disabled)direction.value='買い';});
$('trade-form').addEventListener('submit',async event=>{event.preventDefault();const form=event.currentTarget, data=Object.fromEntries(new FormData(form));try{
  const id=Math.max(0,...state.trades.map(x=>x.id))+1;
  await save({...state,trades:[...state.trades,{...data,id,exit_price:null,exit_date:'',direction:data.direction||'買い'}]});form.reset();form.elements.entry_date.value=today();form.elements.direction.disabled=false;toast('取引を保存しました');nav('trades');
}catch(e){report(e);}});
$('asset-form').addEventListener('submit',async event=>{event.preventDefault();const form=event.currentTarget,data=Object.fromEntries(new FormData(form));try{
  if(state.assets.length && data.date<=state.assets.at(-1).date) throw new Error('最新記録より後の日付を入力してください。同日の修正は履歴からできます');
  const row={...data,currency:state.assets[0]?.currency||data.currency,net_flow:state.assets.length?data.net_flow||0:0};
  await save({...state,assets:[...state.assets,row]});form.reset();form.elements.date.value=today();toast('資産額を保存しました');
}catch(e){report(e);}});

$('export-button').addEventListener('click',async()=>{try{
  const bundle={app:'trade-log-local',version:1,exportedAt:new Date().toISOString(),trades:state.trades,assets:state.assets};
  const filename=`trade-log-backup-${today()}.json`, file=new File([JSON.stringify(bundle,null,2)],filename,{type:'application/json'});
  if(navigator.canShare?.({files:[file]})) await navigator.share({files:[file],title:'Trade Log バックアップ'});
  else {const url=URL.createObjectURL(file),link=el('a');link.href=url;link.download=filename;document.body.append(link);link.click();link.remove();setTimeout(()=>URL.revokeObjectURL(url),60000);}
  await save({...state,backedUpAt:new Date().toISOString()},false);toast('書き出しを開始しました。ファイルへの保存を確認してください');
}catch(e){if(e.name!=='AbortError')report(e);}});

async function readFile(file){if(!file)throw new Error('ファイルを選んでください');if(file.size>10*1024*1024)throw new Error('ファイルが大きすぎます（10MBまで）');return file.text();}
function importReady(prefix,pending){$(`${prefix}-button`).disabled=!pending||!$(`${prefix}-check`).checked;}
$('bundle-file').addEventListener('change',async event=>{pendingBundle=null;$('replace-check').checked=false;try{
  const parsed=JSON.parse(await readFile(event.target.files[0]));pendingBundle=validateBundle(parsed);
  $('import-preview').textContent=`復元する内容: 取引 ${pendingBundle.trades.length}件、資産 ${pendingBundle.assets.length}件。現在: 取引 ${state.trades.length}件、資産 ${state.assets.length}件。`;
}catch(e){$('import-preview').textContent=e.message;}importReady('restore',pendingBundle);});
$('replace-check').addEventListener('change',()=>importReady('restore',pendingBundle));
$('restore-button').addEventListener('click',async()=>{if(!pendingBundle||!$('replace-check').checked)return;
  if(!confirm('この端末の取引・資産データをバックアップの内容で置き換えますか？'))return;
  try{await save({...state,...pendingBundle,backedUpAt:null});pendingBundle=null;$('bundle-file').value='';$('replace-check').checked=false;$('import-preview').textContent='復元しました。';importReady('restore',null);toast('復元が完了しました');}catch(e){report(e);}
});
$('legacy-files').addEventListener('change',async event=>{pendingLegacy=null;$('legacy-check').checked=false;try{
  let trades=null,assets=null;
  for(const file of event.target.files){const source=await readFile(file);let imported,kind;
    try{imported=legacyCSV(source,'trades');kind='trades';}catch(tradeError){try{imported=legacyCSV(source,'assets');kind='assets';}catch{throw new Error(`${file.name}: 取引・資産どちらのCSVにも一致しません（${tradeError.message}）`);}}
    if(kind==='trades'){if(trades)throw new Error('取引CSVが複数あります');trades=imported;}else{if(assets)throw new Error('資産CSVが複数あります');assets=imported;}
  }
  if(trades===null&&assets===null)throw new Error('CSVを選んでください');
  pendingLegacy={trades:trades??state.trades,assets:assets??state.assets};
  $('legacy-preview').textContent=`移行後: 取引 ${pendingLegacy.trades.length}件、資産 ${pendingLegacy.assets.length}件。選ばなかった種類のデータは現状を維持します。`;
}catch(e){$('legacy-preview').textContent=e.message;}importReady('legacy',pendingLegacy);});
$('legacy-check').addEventListener('change',()=>importReady('legacy',pendingLegacy));
$('legacy-button').addEventListener('click',async()=>{if(!pendingLegacy||!$('legacy-check').checked)return;
  if(!confirm('選んだCSVの種類の端末内データを置き換えますか？'))return;
  try{await save({...state,...pendingLegacy,backedUpAt:null});pendingLegacy=null;$('legacy-files').value='';$('legacy-check').checked=false;$('legacy-preview').textContent='移行しました。引き継ぎバックアップも保存してください。';importReady('legacy',null);toast('CSVの移行が完了しました');}catch(e){report(e);}
});

try{const saved=await dbRead();if(saved)state={...state,...validateBundle({app:'trade-log-local',version:1,trades:saved.trades,assets:saved.assets}),changedAt:saved.changedAt,backedUpAt:saved.backedUpAt};render();if(navigator.storage?.persist)navigator.storage.persist().catch(()=>{});if('serviceWorker'in navigator)navigator.serviceWorker.register('./sw.js').catch(console.warn);
  channel?.addEventListener('message',async()=>{const current=await dbRead();if(current){state=current;render();toast('別の画面の更新を反映しました');}});
}catch(e){report(e);document.querySelectorAll('form button[type=submit],#export-button,#restore-button,#legacy-button').forEach(x=>x.disabled=true);$('backup-reminder').classList.remove('hidden');$('backup-reminder').textContent='端末の保存領域を開けません。Safariの設定をご確認ください。';}

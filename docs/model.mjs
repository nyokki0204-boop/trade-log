export const TRADE_COLUMNS = ['id', 'entry_date', 'ticker', 'type', 'direction', 'entry_price', 'stop_price', 'exit_price', 'exit_date', 'tag', 'memo'];
export const ASSET_COLUMNS = ['date', 'total_assets', 'net_flow', 'currency', 'memo'];

const date = (value) => {
  const text = String(value ?? '').trim();
  if (!/^\d{4}-\d{2}-\d{2}$/.test(text) || Number.isNaN(Date.parse(`${text}T12:00:00Z`)) || new Date(`${text}T12:00:00Z`).toISOString().slice(0, 10) !== text) throw new Error(`日付が正しくありません: ${text}`);
  return text;
};
const number = (value, label, minimum = -Infinity) => {
  if (value === '' || value === null || value === undefined || !Number.isFinite(Number(value)) || Number(value) < minimum) throw new Error(`${label}の金額が正しくありません`);
  return Number(value);
};
const optionalNumber = (value, label) => value === '' || value === null || value === undefined ? null : number(value, label, 0);

export function validateTrades(rows) {
  if (!Array.isArray(rows) || rows.length > 20000) throw new Error('取引データの形式または件数が不正です');
  const seen = new Set();
  return rows.map((row) => {
    if (!row || typeof row !== 'object') throw new Error('取引データが不正です');
    const id = number(row.id, '取引ID', 1);
    if (!Number.isSafeInteger(id) || seen.has(id)) throw new Error('取引IDが重複、または不正です');
    seen.add(id);
    const entry_date = date(row.entry_date);
    const ticker = String(row.ticker ?? '').trim().toUpperCase();
    if (!ticker || ticker.length > 30) throw new Error('銘柄が不正です');
    const type = String(row.type ?? '現物');
    const direction = String(row.direction ?? '買い');
    if (!['現物', 'CFD'].includes(type) || !['買い', '売り'].includes(direction) || (type === '現物' && direction !== '買い')) throw new Error('取引種別または方向が不正です');
    const entry_price = number(row.entry_price, '購入価格', 0);
    if (!entry_price) throw new Error('購入価格は0より大きくしてください');
    const stop_price = optionalNumber(row.stop_price, '損切り価格') ?? 0;
    const exit_price = optionalNumber(row.exit_price, '決済価格');
    const exit_date = row.exit_date ? date(row.exit_date) : '';
    if ((exit_price !== null) !== Boolean(exit_date) || (exit_date && exit_date < entry_date)) throw new Error('決済価格と決済日を確認してください');
    const tag = String(row.tag ?? '');
    const memo = String(row.memo ?? '');
    if (tag.length > 200 || memo.length > 5000) throw new Error('タグまたはメモが長すぎます');
    return { id, entry_date, ticker, type, direction, entry_price, stop_price, exit_price, exit_date, tag, memo };
  });
}

export function validateAssets(rows) {
  if (!Array.isArray(rows) || rows.length > 20000) throw new Error('資産データの形式または件数が不正です');
  const seen = new Set();
  const result = rows.map((row) => {
    if (!row || typeof row !== 'object') throw new Error('資産データが不正です');
    const day = date(row.date);
    if (seen.has(day)) throw new Error('同じ日の資産記録が重複しています');
    seen.add(day);
    const currency = String(row.currency ?? '').trim();
    if (!['JPY', 'USD'].includes(currency)) throw new Error('通貨はJPYまたはUSDにしてください');
    const memo = String(row.memo ?? '');
    if (memo.length > 5000) throw new Error('メモが長すぎます');
    return { date: day, total_assets: number(row.total_assets, '総資産', 0), net_flow: number(row.net_flow, '入出金'), currency, memo };
  }).sort((a, b) => a.date.localeCompare(b.date));
  if (result.length && (result[0].net_flow !== 0 || result.some(x => x.currency !== result[0].currency))) throw new Error('最初の入出金は0、通貨は全記録で同じにしてください');
  return result;
}

export function prepareAssets(rows) {
  const assets = validateAssets(rows);
  let operating = 0;
  return assets.map((row, i) => {
    const change = i ? row.total_assets - assets[i - 1].total_assets - row.net_flow : 0;
    operating += change;
    return { ...row, asset_change: row.total_assets - assets[0].total_assets, operating_change: change, cumulative_operating_change: operating };
  });
}

export function tradeMetrics(row) {
  if (row.exit_price === null) return { pnl: null, r: null, days: null };
  const profit = (row.exit_price - row.entry_price) * (row.direction === '売り' ? -1 : 1);
  const days = Math.round((Date.parse(`${row.exit_date}T12:00:00Z`) - Date.parse(`${row.entry_date}T12:00:00Z`)) / 86400000);
  return { pnl: profit / row.entry_price * 100, r: row.stop_price === row.entry_price ? null : profit / Math.abs(row.entry_price - row.stop_price), days };
}

export function parseCSV(input) {
  const source = String(input).replace(/^\uFEFF/, '');
  let field = '', row = [], records = [], quoted = false;
  for (let i = 0; i < source.length; i++) {
    const char = source[i];
    if (quoted) {
      if (char === '"' && source[i + 1] === '"') { field += '"'; i++; }
      else if (char === '"') quoted = false;
      else field += char;
    } else if (char === '"' && field === '') quoted = true;
    else if (char === ',') { row.push(field); field = ''; }
    else if (char === '\n' || char === '\r') {
      if (char === '\r' && source[i + 1] === '\n') i++;
      row.push(field); field = '';
      if (row.some(cell => cell !== '')) records.push(row);
      row = [];
    } else field += char;
  }
  if (quoted) throw new Error('CSVの引用符が閉じていません');
  row.push(field);
  if (row.some(cell => cell !== '')) records.push(row);
  if (!records.length) throw new Error('CSVが空です');
  const headers = records.shift().map(x => x.trim());
  if (new Set(headers).size !== headers.length) throw new Error('CSVの列が重複しています');
  return { headers, rows: records.map((cells, i) => {
    if (cells.length !== headers.length) throw new Error(`CSV ${i + 2}行目の列数が違います`);
    return Object.fromEntries(headers.map((key, j) => [key, cells[j]]));
  }) };
}

export function legacyCSV(input, kind) {
  const { headers, rows } = parseCSV(input);
  const required = kind === 'trades' ? TRADE_COLUMNS.filter(x => x !== 'tag' && x !== 'memo') : ASSET_COLUMNS.filter(x => x !== 'memo');
  if (required.some(key => !headers.includes(key))) throw new Error('CSVに必要な列がありません');
  return kind === 'trades' ? validateTrades(rows) : validateAssets(rows);
}

export function validateBundle(value) {
  if (!value || value.app !== 'trade-log-local' || value.version !== 1 || !Array.isArray(value.trades) || !Array.isArray(value.assets)) throw new Error('Trade Logのバックアップ形式ではありません');
  return { trades: validateTrades(value.trades), assets: validateAssets(value.assets) };
}

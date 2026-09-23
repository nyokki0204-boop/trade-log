import test from 'node:test';
import assert from 'node:assert/strict';
import { legacyCSV, validateBundle, validateTrades, prepareAssets, tradeMetrics } from './docs/model.mjs';

test('既存StreamlitのCSVを列順に依存せず読み込む', () => {
  const csv = '\uFEFFid,entry_date,ticker,type,direction,entry_price,stop_price,exit_price,exit_date,memo,tag\r\n1,2026-09-23,AAPL,現物,買い,1.0,2.0,2.0,2026-09-23,"メモ,あり",押し目\r\n';
  const [row] = legacyCSV(csv, 'trades');
  assert.equal(row.memo, 'メモ,あり');
  assert.equal(tradeMetrics(row).pnl, 100);
  assert.equal(tradeMetrics(row).r, 1);
});

test('資産履歴は入出金を除いて計算し、日付順で復元', () => {
  const csv = 'date,total_assets,net_flow,currency,memo\n2026-09-21,1300,200,JPY,\n2026-09-20,1000,0,JPY,初回\n2026-09-22,1250,-100,JPY,\n';
  const prepared = prepareAssets(legacyCSV(csv, 'assets'));
  assert.equal(prepared.at(-1).asset_change, 250);
  assert.equal(prepared.at(-1).cumulative_operating_change, 150);
});

test('壊れたバックアップや重複IDと日付を拒否', () => {
  assert.throws(() => validateBundle({ app: 'other', version: 1, trades: [], assets: [] }));
  const trade = { id: 1, entry_date: '2026-09-23', ticker: 'AAPL', type: '現物', direction: '買い', entry_price: 100, stop_price: 90, exit_price: null, exit_date: '' };
  assert.throws(() => validateTrades([trade, trade]), /重複/);
  assert.throws(() => validateTrades([{ ...trade, entry_date: '2026-02-30' }]), /日付/);
  assert.throws(() => validateBundle({ app: 'trade-log-local', version: 1, trades: [], assets: [{ date: '2026-09-23', total_assets: 100, net_flow: 10, currency: 'JPY' }] }), /最初/);
});

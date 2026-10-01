// TypeScriptの純粋関数を既存のコンパイラで読み込み、追加のテスト依存を増やさない。
import { readFileSync } from "node:fs";
import { resolve, dirname } from "node:path";
import { fileURLToPath } from "node:url";
import { test } from "node:test";
import assert from "node:assert/strict";
import ts from "typescript";
const __dirname = dirname(fileURLToPath(import.meta.url));
const source = readFileSync(resolve(__dirname, "../src/lib/stock-performance.ts"), "utf8");
const compiled = ts.transpileModule(source, { compilerOptions: { target: ts.ScriptTarget.ES2022, module: ts.ModuleKind.CommonJS } }).outputText;
const loaded = { exports: {} };
new Function("exports", "module", compiled)(loaded.exports, loaded);
const { calculateHitRate } = loaded.exports;
const dates = ["2026-09-25", "2026-09-28", "2026-09-29", "2026-09-30", "2026-10-01", "2026-10-02", "2026-10-05"];
const signals = [{ date: dates[0], ml_signal: "buy_candidate" }];

test("個別銘柄の途中欠損でも市場の5営業日後で評価する", () => {
  const prices = dates.map((date, i) => ({ date, close: i === 5 ? 110 : 100 }));
  prices.splice(2, 1);
  assert.deepEqual(calculateHitRate(prices, signals, dates), { rate: 100, total: 1 });
});

test("評価日の価格欠損を6営業日後の価格で補わない", () => {
  const prices = dates.map((date) => ({ date, close: 110 })).filter((p) => p.date !== dates[5]);
  assert.equal(calculateHitRate(prices, signals, dates), null);
});

test("null・0・無限大の終値と未確定期間を集計しない", () => {
  for (const invalid of [null, 0, Infinity]) {
    const prices = dates.map((date, i) => ({ date, close: i === 0 ? invalid : 110 }));
    assert.equal(calculateHitRate(prices, signals, dates), null);
  }
  assert.equal(calculateHitRate([], signals, dates.slice(0, 3)), null);
});

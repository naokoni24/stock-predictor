import { readFileSync } from "node:fs";
import { test } from "node:test";
import assert from "node:assert/strict";
import ts from "typescript";
function load(path) {
  const code = ts.transpileModule(
    readFileSync(new URL(path, import.meta.url), "utf8"),
    {
      compilerOptions: {
        target: ts.ScriptTarget.ES2022,
        module: ts.ModuleKind.CommonJS,
      },
    },
  ).outputText;
  const loaded = { exports: {} };
  new Function("exports", "module", code)(loaded.exports, loaded);
  return loaded.exports;
}
const { signalChanges, holdingReview, watchAlerts, parseWatchPrices } = load(
  "../src/lib/signal-activity.ts",
);
const { selectOutcomes, summarize, scoreBand, groupOutcomes, dateDaysAgo } =
  load("../src/lib/performance-summary.ts");
const previous = {
  ticker: "7203.T",
  date: "2026-09-30",
  close: 100,
  signal: "buy_candidate",
  ml_signal: "buy_candidate",
  ml_score: 0.8,
  model_version: "v1",
};
const current = {
  ...previous,
  date: "2026-10-01",
  signal: "sell_candidate",
  ml_signal: "hold",
  ml_score: 0.7,
};

test("テクニカルとAIの変化を独立に比較する", () => {
  const change = signalChanges([current], [previous])[0];
  assert.equal(change.changes.length, 2);
  assert.ok(Math.abs(change.scoreDelta + 0.1) < 1e-9);
  assert.match(change.changes[0], /買い候補 → 売り候補/);
});
test("分析対象からの脱落・初登場・欠損・不明判定を変化と数えない", () => {
  assert.deepEqual(signalChanges([], [previous]), []);
  assert.deepEqual(signalChanges([current], []), []);
  for (const value of [null, 0, Infinity])
    assert.deepEqual(
      signalChanges([{ ...current, close: value }], [previous]),
      [],
    );
  assert.deepEqual(
    signalChanges([{ ...current, signal: null, ml_signal: null }], [previous]),
    [],
  );
  assert.deepEqual(signalChanges([previous], [previous]), []);
});
test("モデル世代が違う・不明な場合、スコア差を計算しない", () => {
  assert.equal(
    signalChanges([{ ...current, model_version: "v2" }], [previous])[0]
      .scoreDelta,
    null,
  );
  assert.equal(
    signalChanges([{ ...current, model_version: null }], [previous])[0]
      .scoreDelta,
    null,
  );
});
const review = (extra = {}) =>
  holdingReview({
    close: 100,
    costPrice: 100,
    priceDate: current.date,
    latestDate: current.date,
    current,
    previous,
    ...extra,
  });
test("損切り到達・売り候補・接近を優先し、境界を含む", () => {
  assert.equal(review({ close: 92 }).priority, 100);
  assert.equal(review().priority, 90);
  const held = { ...current, signal: "hold", ml_score: 0.8 };
  assert.equal(review({ close: 94, current: held }).priority, 70);
  assert.equal(review({ current: { ...held, ml_score: 0.7 } }).priority, 60);
});
test("古い価格やシグナルから売り優先・損切り到達を新規判定しない", () => {
  const result = review({
    close: 80,
    priceDate: previous.date,
    current: previous,
  });
  assert.equal(result.priority, 80);
  assert.ok(
    !result.reasons.some(
      (reason) => reason.includes("到達") || reason.includes("売り候補"),
    ),
  );
  assert.equal(
    review({ current: { ...current, signal: "hold", model_version: "v2" } })
      .priority,
    20,
  );
});
const rule = {
  price_above: 100,
  price_below: 90,
  signal_alert: true,
  created_at: "2026-09-29T15:00:00Z",
};
test("価格の一致も通知し、同じ最新日の価格だけを使う", () => {
  assert.ok(
    watchAlerts(
      rule,
      { close: 100, date: current.date },
      null,
      null,
      current.date,
    )[0].includes("以上"),
  );
  assert.ok(
    watchAlerts(
      rule,
      { close: 90, date: current.date },
      null,
      null,
      current.date,
    )[0].includes("以下"),
  );
  assert.deepEqual(
    watchAlerts(
      rule,
      { close: 110, date: previous.date },
      null,
      null,
      current.date,
    ),
    [],
  );
});
test("登録前のシグナル変化と無効価格は通知しない", () => {
  const lateRule = { ...rule, created_at: "2026-09-30T15:00:00Z" }; // JSTでは10/1
  assert.deepEqual(
    watchAlerts(lateRule, null, current, previous, current.date),
    [],
  );
  assert.equal(
    watchAlerts(rule, null, current, previous, current.date).length,
    2,
  );
  assert.deepEqual(
    watchAlerts(
      { ...rule, signal_alert: false },
      { close: null, date: current.date },
      current,
      previous,
      current.date,
    ),
    [],
  );
});
test("アラート価格の空欄・不正数値・上下限を検証する", () => {
  assert.deepEqual(parseWatchPrices("", ""), {
    price_above: null,
    price_below: null,
  });
  for (const value of ["NaN", "Infinity", "-1", "0", "1e20"])
    assert.ok(parseWatchPrices(value, "").error);
  assert.ok(parseWatchPrices("100", "100").error);
  assert.ok(parseWatchPrices("100", "110").error);
  assert.deepEqual(parseWatchPrices("100", "90"), {
    price_above: 100,
    price_below: 90,
  });
});
const outcome = {
  ticker: "7203.T",
  signal_date: "2026-09-01",
  outcome_date: "2026-10-01",
  net_return: 0.02,
  ml_score: 0.65,
  model_version: "v1",
  sector: "輸送用機器",
  evaluation_version: "next_open_stop_excess_v2",
};
const now = new Date("2026-09-30T15:30:00Z");
test("実績の期間はJSTで判定し、旧定義・未来・null・無限値を除外する", () => {
  assert.equal(dateDaysAgo(0, now), "2026-10-01");
  const rows = [
    outcome,
    { ...outcome, evaluation_version: "legacy" },
    { ...outcome, outcome_date: "2026-10-02" },
    { ...outcome, outcome_date: "2026-08-31" },
    { ...outcome, net_return: null },
    { ...outcome, net_return: Infinity },
  ];
  assert.deepEqual(selectOutcomes(rows, 30, now), [outcome]);
});
test("勝率はネット超過プラス、ゼロは勝ちに数えず、平均は小数単位を保持する", () => {
  assert.deepEqual(
    summarize([
      outcome,
      { ...outcome, net_return: -0.01 },
      { ...outcome, net_return: 0 },
    ]),
    {
      trades: 3,
      winRate: 1 / 3,
      netReturn: 0.01 / 3,
    },
  );
  assert.equal(summarize([]), null);
});
test("スコア境界と不明値を別の帯に分け、業種・世代で集計する", () => {
  assert.equal(scoreBand(0.55), "0.55〜0.65未満");
  assert.equal(scoreBand(0.65), "0.65〜0.75未満");
  assert.equal(scoreBand(0.75), "0.75〜1.00");
  assert.equal(scoreBand(1), "0.75〜1.00");
  assert.equal(scoreBand(null), "不明");
  assert.equal(scoreBand(1.1), "不明");
  const rows = [outcome, { ...outcome, sector: null, model_version: "v2" }];
  assert.equal(groupOutcomes(rows, "score")[0].trades, 2);
  assert.equal(groupOutcomes(rows, "sector").length, 2);
  assert.equal(groupOutcomes(rows, "model").length, 2);
});

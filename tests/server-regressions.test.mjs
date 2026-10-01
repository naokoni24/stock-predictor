import { readFileSync } from "node:fs";
import { resolve, dirname } from "node:path";
import { fileURLToPath } from "node:url";
import { test } from "node:test";
import assert from "node:assert/strict";
import ts from "typescript";
import { createRequire } from "node:module";
const runtimeRequire = createRequire(import.meta.url);
const __dirname = dirname(fileURLToPath(import.meta.url));

function loadSource(path, imports, globals = {}) {
  const source = readFileSync(resolve(__dirname, "..", path), "utf8");
  const compiled = ts.transpileModule(source, { compilerOptions: { target: ts.ScriptTarget.ES2022, module: ts.ModuleKind.CommonJS, jsx: ts.JsxEmit.ReactJSX } }).outputText;
  const loaded = { exports: {} };
  new Function("require", "exports", "module", ...Object.keys(globals), compiled)(
    (name) => imports[name] ?? runtimeRequire(name), loaded.exports, loaded, ...Object.values(globals)
  );
  return loaded.exports;
}

function loadCron(runs, env = { CRON_SECRET: "test", GITHUB_ACTIONS_TOKEN: "test" }) {
  const requests = [];
  class FixedDate extends Date {
    constructor(...args) { super(...(args.length ? args : ["2026-10-01T09:00:00Z"])); }
  }
  const handler = loadSource("src/app/api/cron/repair-check/route.ts", {
    "next/server": { NextResponse: { json: (body, options) => ({ body, status: options?.status ?? 200 }) } },
  }, {
    Date: FixedDate, process: { env },
    fetch: async (url, options) => {
      requests.push({ url, options });
      return { ok: true, json: async () => ({ workflow_runs: runs }) };
    },
  });
  return { requests, GET: handler.GET };
}

const request = { headers: new Headers({ authorization: "Bearer test" }) };
test("15:29開始の成功を当日終値の更新済みと誤判定しない", async () => {
  const cron = loadCron([{ status: "completed", conclusion: "success", run_started_at: "2026-10-01T06:29:59Z" }]);
  const result = await cron.GET(request);
  assert.equal(result.body.action, "dispatched");
  assert.match(cron.requests[0].url, /branch=main/);
  assert.deepEqual(JSON.parse(cron.requests[1].options.body), { ref: "main", inputs: { repair_only: "1" } });
});

test("15:30以降の成功・実行中なら二重起動しない", async () => {
  for (const status of ["completed", "in_progress", "queued"]) {
    const cron = loadCron([{ status, conclusion: "success", run_started_at: "2026-10-01T06:30:00Z", html_url: "https://example.com/run" }]);
    assert.equal((await cron.GET(request)).body.action, "skip");
    assert.equal(cron.requests.length, 1);
  }
});

test("Cron認証失敗時はGitHubを呼ばない", async () => {
  const cron = loadCron([]);
  assert.equal((await cron.GET({ headers: new Headers() })).status, 401);
  assert.equal(cron.requests.length, 0);
});

function responseWithCookies() {
  const jar = new Map();
  return {
    cookies: {
      set: (name, value, options) => {
        const cookie = typeof name === "object" ? name : { name, value, ...options };
        jar.set(cookie.name, cookie);
      },
      getAll: () => [...jar.values()],
    },
  };
}

test("認証更新・削除Cookieをリダイレクト時も維持する", async () => {
  for (const user of [null, { id: "user" }]) {
    const proxy = loadSource("src/proxy.ts", {
      "@supabase/ssr": { createServerClient: (_url, _key, options) => ({ auth: {
        getUser: async () => {
          options.cookies.setAll([{ name: "auth", value: user ? "refreshed" : "", options: { httpOnly: true, maxAge: user ? 3600 : 0 } }]);
          return { data: { user } };
        },
      } }) },
      "next/server": { NextResponse: {
        next: () => responseWithCookies(),
        redirect: (url) => ({ ...responseWithCookies(), location: url.pathname }),
      } },
    });
    const path = user ? "/login" : "/holdings";
    const url = new URL("https://example.com" + path);
    url.clone = () => new URL(url);
    const response = await proxy.proxy({ nextUrl: url, cookies: responseWithCookies().cookies });
    assert.equal(response.location, user ? "/" : "/login");
    assert.deepEqual(response.cookies.getAll(), [{ name: "auth", value: user ? "refreshed" : "", httpOnly: true, maxAge: user ? 3600 : 0 }]);
  }
});

test("本番成績が1000行を超えても90日分をページングして集計する", async () => {
  const all = Array.from({ length: 1505 }, () => ({ outcome_date: new Date().toLocaleDateString("sv-SE", { timeZone: "Asia/Tokyo" }), net_return: 0.01, model_version: "test", evaluation_version: "next_open_stop_excess_v1" }));
  const ranges = [];
  const query = () => {
    let range;
    const builder = {
      select: () => builder, eq: () => builder, gte: () => builder, lte: () => builder, order: () => builder,
      range: (from, to) => { range = [from, to]; ranges.push(range); return builder; },
      then: (resolve) => resolve({ data: all.slice(range[0], range[1] + 1), error: null }),
    };
    return builder;
  };
  const summary = loadSource("src/lib/performance-summary.ts", {});
  const loaded = loadSource("src/lib/performance-data.ts", {
    react: { cache: (fn) => fn },
    "@/lib/supabase": { supabase: { from: query } },
    "@/lib/performance-summary": summary,
  });
  const result = await loaded.fetchLivePerformance();
  assert.equal(result.longer.trades, 1505);
  assert.deepEqual(ranges, [[0, 999], [1000, 1999]]);
});

test("保有株は銘柄ごとの最新2価格を使い、古いsignals価格に戻らない", async () => {
  const calls = [];
  const fixtures = {
    holdings: [{ id: 1, ticker: "7203.T", shares: 100, cost_price: 100, stocks: { name: "トヨタ" } }],
    prices: [{ date: "2026-10-01", close: 120 }, { date: "2026-09-30", close: 110 }],
    signals: [{ date: "2026-09-28", close: 90, signal: "hold", rsi14: 50 }],
  };
  const from = (table) => {
    const call = { table }; calls.push(call);
    const query = {
      select: () => query, order: () => query, not: () => query,
      eq: (_key, ticker) => { call.ticker = ticker; return query; },
      limit: (limit) => { call.limit = limit; return query; },
      maybeSingle: () => { call.single = true; return query; },
      then: (resolve) => resolve({ data: call.single ? fixtures[table][0] : fixtures[table], error: null }),
    };
    return query;
  };
  const { createElement } = runtimeRequire("react");
  const { renderToStaticMarkup } = runtimeRequire("react-dom/server");
  const component = ({ children }) => createElement("div", {}, children);
  const page = loadSource("src/app/holdings/page.tsx", new Proxy({
    "@/lib/supabase-server": { createClient: async () => ({ from }) },
    "@/lib/activity-data": { fetchMarketSignals: async () => ({ latestDate: "2026-10-01", current: [], previous: [], error: null }) },
    "@/lib/signal-activity": loadSource("src/lib/signal-activity.ts", {}),
    "@/lib/utils": { cn: () => "", getCloseLabel: (date) => date },
    "next/link": { default: component },
  }, {
    get: (target, name) => target[name] ?? (name.startsWith("@/") || name.startsWith("./")
      ? { default: component, Card: component, CardHeader: component, CardContent: component, CardTitle: component, Badge: component } : undefined),
  })).default;
  const html = renderToStaticMarkup(await page({ searchParams: Promise.resolve({}) }));
  assert.match(html, /12,000/);
  assert.match(html, /1,000/);
  assert.equal(calls.find((c) => c.table === "prices").limit, 2);
  assert.equal(calls.find((c) => c.table === "signals").limit, 1);
  assert.equal(calls.find((c) => c.table === "prices").ticker, "7203.T");
});

test("実績の途中ページ取得失敗を部分的な成績として表示しない", async () => {
  let requests = 0;
  const builder = { select: () => builder, eq: () => builder, gte: () => builder, lte: () => builder,
    order: () => builder, range: () => builder,
    then: (resolve) => resolve(++requests === 1
      ? { data: Array(1000).fill({ net_return: 1 }), error: null }
      : { data: null, error: { message: "取得失敗" } }),
  };
  const loaded = loadSource("src/lib/performance-data.ts", {
    react: { cache: (fn) => fn }, "@/lib/supabase": { supabase: { from: () => builder } },
    "@/lib/performance-summary": loadSource("src/lib/performance-summary.ts", {}),
  });
  const result = await loaded.fetchLivePerformance();
  assert.equal(result.longer, null);
  assert.ok(result.error);
});

test("ウォッチリスト更新は認証済みの本人に限定し、未認証ではDBを呼ばない", async () => {
  for (const user of [null, { id: "本人" }]) {
    const calls = [];
    const builder = { update: (values) => { calls.push(values); return builder; },
      eq: (key, value) => { calls.push([key, value]); return builder; },
      select: async () => ({ data: [{ ticker: "7203.T" }], error: null }),
    };
    const actions = loadSource("src/app/watchlist/actions.ts", {
      "next/navigation": { redirect: (url) => { throw new Error(url); } },
      "next/cache": { revalidatePath: () => {} },
      "@/lib/supabase-server": { createClient: async () => ({ auth: { getUser: async () => ({ data: { user }, error: null }) },
        from: () => builder }) },
      "@/lib/signal-activity": loadSource("src/lib/signal-activity.ts", {}),
    });
    const form = new FormData();
    form.set("ticker", "7203.T"); form.set("priceAbove", "200");
    await assert.rejects(actions.updateWatch(form), (error) => error.message.startsWith(user ? "/watchlist?success=" : "/login"));
    if (user) {
      assert.ok(calls.some((call) => Array.isArray(call) && call[0] === "user_id" && call[1] === "本人"));
      assert.ok(calls.some((call) => Array.isArray(call) && call[0] === "ticker" && call[1] === "7203.T"));
    } else assert.deepEqual(calls, []);
  }
});

import { readFileSync } from "node:fs";
import assert from "node:assert/strict";
// 本番DBへ接続せず、一時PostgreSQLで supabase/restrict_stocks_insert.sql を検証する。
// PGLITE_TEST_MODULEで/tmp等に導入した@electric-sql/pgliteのパスを指定できる。
const { PGlite } = await import(process.env.PGLITE_TEST_MODULE || "@electric-sql/pglite");
const db = new PGlite();
await db.exec(`create role authenticated; create role service_role bypassrls;
  create table public.stocks(ticker text primary key, name text);
  alter table public.stocks enable row level security;
  grant usage on schema public to authenticated, service_role; grant insert on public.stocks to authenticated, service_role;
  create policy "authenticated users can insert stocks" on public.stocks for insert to authenticated with check (true);`);
const sql = readFileSync(new URL("../supabase/restrict_stocks_insert.sql", import.meta.url), "utf8");
await db.exec(sql); await db.exec(sql);
await db.exec("set role authenticated");
for (const [t, n] of [["7203.T", "トヨタ"], ["285A.T", null]]) await db.query("insert into public.stocks values ($1,$2)", [t, n]);
for (const [t, n] of [["BAD", "x"], ["5802@F.T", "x"], ["7203.TX", "x"], ["0", "x"], ["1234.T", "x".repeat(101)], ["1235.T", ""]])
  await assert.rejects(db.query("insert into public.stocks values ($1,$2)", [t, n]), /row-level security/);
await db.exec("reset role; set role service_role");
await db.query("insert into public.stocks values ('XXXX', 'service')");
console.log("stocks insert policy: 10 checks ok");

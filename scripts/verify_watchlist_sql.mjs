// 本番DBへ接続せず、一時PostgreSQLでSQL・権限・RLSを検証する。
// PGLITE_TEST_MODULEで/tmp等に導入した@electric-sql/pgliteのパスを指定できる。
import { readFileSync } from "node:fs";
import assert from "node:assert/strict";
const { PGlite } = await import(
  process.env.PGLITE_TEST_MODULE || "@electric-sql/pglite"
);
const db = new PGlite();
const a = "11111111-1111-4111-8111-111111111111";
const b = "22222222-2222-4222-8222-222222222222";
let checks = 0;
const sql = readFileSync(
  new URL("../supabase/add_personal_watchlists.sql", import.meta.url),
  "utf8",
);
try {
  await db.exec(`
    create role anon; create role authenticated; create role service_role bypassrls;
    create schema auth;
    create table auth.users(id uuid primary key);
    create function auth.uid() returns uuid language sql stable as
      $$ select nullif(current_setting('request.jwt.claim.sub', true), '')::uuid $$;
    grant usage on schema auth, public to anon, authenticated, service_role;
    grant execute on function auth.uid() to anon, authenticated, service_role;
    create table public.stocks(ticker text primary key, name text);
    insert into auth.users values ('${a}'), ('${b}');
    insert into public.stocks select i::text || '.T', i::text from generate_series(1000, 1040) i;
  `);
  await db.exec(sql);
  await db.exec(sql); // 再適用可能性
  checks++;
  async function role(name, user = "") {
    await db.exec(`reset role; set role ${name}`);
    await db.query("select set_config('request.jwt.claim.sub', $1, false)", [
      user,
    ]);
  }
  async function denied(query, params = [], code = "42501") {
    await assert.rejects(
      db.query(query, params),
      (error) => error.code === code,
    );
    checks++;
  }
  const insert =
    "insert into public.watchlists(user_id, ticker) values ($1, $2)";
  await role("anon");
  await denied("select * from public.watchlists");
  await denied(insert, [a, "1000.T"]);
  await denied("update public.watchlists set price_above = 200");
  await denied("delete from public.watchlists");
  await role("authenticated", a);
  await db.query(insert, [a, "1000.T"]);
  checks++;
  await denied(insert, [b, "1001.T"]);
  assert.equal(
    (await db.query("select * from public.watchlists")).rows.length,
    1,
  );
  checks++;
  await db.query(
    "update public.watchlists set price_above=200, price_below=100, signal_alert=false where ticker=$1",
    ["1000.T"],
  );
  checks++;
  await denied("update public.watchlists set user_id=$1", [b]);
  await denied("update public.watchlists set created_at='2020-01-01'");
  await denied("update public.watchlists set price_below=300", [], "23514");
  await denied("update public.watchlists set price_above='NaN'", [], "23514");
  await denied(insert, [a, "1000.T"], "23505");
  await role("authenticated", b);
  assert.equal(
    (await db.query("select * from public.watchlists")).rows.length,
    0,
  );
  checks++;
  assert.equal(
    (
      await db.query(
        "update public.watchlists set price_above=500 where ticker='1000.T' returning *",
      )
    ).rows.length,
    0,
  );
  checks++;
  assert.equal(
    (
      await db.query(
        "delete from public.watchlists where ticker='1000.T' returning *",
      )
    ).rows.length,
    0,
  );
  checks++;
  await db.query(insert, [b, "1000.T"]);
  checks++;
  await role("authenticated", a);
  for (let i = 1001; i < 1030; i++) await db.query(insert, [a, `${i}.T`]);
  assert.equal(
    (await db.query("select * from public.watchlists")).rows.length,
    30,
  );
  checks++;
  await denied(insert, [a, "1030.T"], "23514");
  await db.query("delete from public.watchlists where ticker='1001.T'");
  await db.query(insert, [a, "1030.T"]);
  checks++;
  await role("service_role");
  assert.equal(
    (await db.query("select * from public.watchlists")).rows.length,
    31,
  );
  checks++;
  console.log(
    `ウォッチリストSQL/RLS: ${checks}チェック成功（SQL再適用、anon拒否、2ユーザー分離、CRUD、上限、価格制約、バッチ読取）`,
  );
} finally {
  await db.close();
}

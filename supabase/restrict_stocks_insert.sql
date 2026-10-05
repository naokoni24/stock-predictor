-- Supabase SQL Editorで実行してください。既存データは変更しません。何度実行しても同じ結果になります。
-- 認証ユーザーによる銘柄マスタ(stocks)への追加を、東証の4桁コード形式・常識的な銘柄名の長さに限定する。
-- 以前のポリシーは with check (true) で、新規登録が開いている間は第三者が任意の値を登録できた。
-- アプリの保有株追加(src/app/holdings/actions.ts)と同じ形式条件。日次バッチはservice_roleのため影響しない。
begin;
drop policy if exists "authenticated users can insert stocks" on public.stocks;
create policy "authenticated users can insert stocks"
  on public.stocks
  for insert
  to authenticated
  with check (
    ticker ~ '^[0-9][0-9A-Z]{3}\.T$'
    and (name is null or char_length(name) between 1 and 100)
  );
commit;

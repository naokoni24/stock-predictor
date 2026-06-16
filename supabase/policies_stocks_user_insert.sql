-- 認証ユーザーが stocks へ新規銘柄を登録できるようにするポリシー
-- 保有株追加時、まだ日次バッチで取得していない銘柄を登録するために必要
create policy "authenticated users can insert stocks"
  on stocks
  for insert
  to authenticated
  with check (true);

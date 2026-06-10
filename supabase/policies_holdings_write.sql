-- 保有株の登録・削除をUIから行えるようにする（個人利用の簡易版のため認証なし）
create policy "public insert holdings" on holdings for insert with check (true);
create policy "public delete holdings" on holdings for delete using (true);
create policy "public insert stocks" on stocks for insert with check (true);

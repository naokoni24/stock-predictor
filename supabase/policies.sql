-- 匿名(anon)からの読み取りを許可（個人利用の簡易版のため、書き込みは許可しない）
alter table stocks enable row level security;
alter table prices enable row level security;
alter table signals enable row level security;
alter table holdings enable row level security;

create policy "public read stocks" on stocks for select using (true);
create policy "public read prices" on prices for select using (true);
create policy "public read signals" on signals for select using (true);
create policy "public read holdings" on holdings for select using (true);

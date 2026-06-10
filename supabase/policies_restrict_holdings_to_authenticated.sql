-- 保有株は個人情報に近いため、公開APIからの読み書きを止めてログイン済みユーザーに限定する。
-- Supabase SQL Editorで実行してください。

drop policy if exists "public read holdings" on holdings;
drop policy if exists "public insert holdings" on holdings;
drop policy if exists "public delete holdings" on holdings;
drop policy if exists "public insert stocks" on stocks;
drop policy if exists "authenticated read holdings" on holdings;
drop policy if exists "authenticated insert holdings" on holdings;
drop policy if exists "authenticated delete holdings" on holdings;
drop policy if exists "authenticated insert stocks" on stocks;

create policy "authenticated read holdings"
on holdings for select
to authenticated
using (true);

create policy "authenticated insert holdings"
on holdings for insert
to authenticated
with check (shares > 0 and cost_price > 0);

create policy "authenticated delete holdings"
on holdings for delete
to authenticated
using (true);

create policy "authenticated insert stocks"
on stocks for insert
to authenticated
with check (true);

do $$
begin
  if not exists (
    select 1
    from pg_constraint
    where conname = 'holdings_positive_values'
      and conrelid = 'holdings'::regclass
  ) then
    alter table holdings
      add constraint holdings_positive_values
      check (shares > 0 and cost_price > 0)
      not valid;
  end if;
end $$;

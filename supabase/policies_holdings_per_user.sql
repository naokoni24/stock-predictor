-- 保有株をログインユーザーごとに分離する
-- Supabase SQL Editorで実行してください。

alter table holdings add column if not exists user_id uuid references auth.users(id) on delete cascade default auth.uid();

-- 既存データ(user_idがnullの行)は表示・編集できなくなるため、
-- 必要であれば自分のユーザーIDで更新してください。
-- update holdings set user_id = '<自分のユーザーID>' where user_id is null;

alter table holdings alter column user_id set not null;

drop policy if exists "authenticated read holdings" on holdings;
drop policy if exists "authenticated insert holdings" on holdings;
drop policy if exists "authenticated delete holdings" on holdings;

create policy "user read own holdings"
on holdings for select
to authenticated
using (auth.uid() = user_id);

create policy "user insert own holdings"
on holdings for insert
to authenticated
with check (auth.uid() = user_id and shares > 0 and cost_price > 0);

create policy "user delete own holdings"
on holdings for delete
to authenticated
using (auth.uid() = user_id);

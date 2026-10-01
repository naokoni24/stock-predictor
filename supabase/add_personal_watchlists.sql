-- Supabase SQL Editorで実行してください。既存のテーブル・データは変更しません。
begin;
create table if not exists public.watchlists (
  user_id uuid not null references auth.users(id) on delete cascade,
  ticker text not null references public.stocks(ticker) on delete cascade,
  price_above numeric,
  price_below numeric,
  signal_alert boolean not null default true,
  created_at timestamptz not null default now(),
  primary key (user_id, ticker),
  constraint watchlists_price_above_valid check (price_above is null or (price_above > 0 and price_above <= 1000000000000)),
  constraint watchlists_price_below_valid check (price_below is null or (price_below > 0 and price_below <= 1000000000000)),
  constraint watchlists_price_order check (price_above is null or price_below is null or price_below < price_above)
);
create index if not exists idx_watchlists_created on public.watchlists(created_at, ticker);
alter table public.watchlists enable row level security;
revoke all on public.watchlists from public, anon, authenticated;
grant select, delete on public.watchlists to authenticated;
grant insert (user_id, ticker, price_above, price_below, signal_alert) on public.watchlists to authenticated;
grant update (price_above, price_below, signal_alert) on public.watchlists to authenticated;
grant all on public.watchlists to service_role;
drop policy if exists watchlists_select_own on public.watchlists;
create policy watchlists_select_own on public.watchlists for select to authenticated using ((select auth.uid()) = user_id);
drop policy if exists watchlists_insert_own on public.watchlists;
create policy watchlists_insert_own on public.watchlists for insert to authenticated with check ((select auth.uid()) = user_id);
drop policy if exists watchlists_update_own on public.watchlists;
create policy watchlists_update_own on public.watchlists for update to authenticated using ((select auth.uid()) = user_id) with check ((select auth.uid()) = user_id);
drop policy if exists watchlists_delete_own on public.watchlists;
create policy watchlists_delete_own on public.watchlists for delete to authenticated using ((select auth.uid()) = user_id);

-- 同時追加でも1人30銘柄を超えないよう、ユーザー単位で追加を直列化する。
-- SECURITY INVOKERのまま実行し、ユーザーのRLSを迂回しない。
create or replace function public.check_watchlist_limit() returns trigger
language plpgsql security invoker set search_path = '' as $$
begin
  perform pg_catalog.pg_advisory_xact_lock(pg_catalog.hashtextextended(new.user_id::text, 0));
  if (select count(*) from public.watchlists where user_id = new.user_id) >= 30 then
    raise exception 'ウォッチリストは30銘柄までです。' using errcode = '23514';
  end if;
  return new;
end;
$$;
revoke all on function public.check_watchlist_limit() from public, anon, authenticated;
drop trigger if exists watchlists_limit on public.watchlists;
create trigger watchlists_limit before insert on public.watchlists for each row execute function public.check_watchlist_limit();
comment on table public.watchlists is '個人ウォッチリスト。最新市場日の終値・シグナルでアプリ内アラートを表示。';
commit;

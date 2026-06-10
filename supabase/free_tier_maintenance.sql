-- 無料枠運用向けのDBメンテナンスSQL。
-- Supabase SQL Editorで実行してください。
-- 予測精度に使うモデル学習はyfinanceから取得するため、DB上の古い表示用データを削っても精度は落ちにくい。

create index if not exists idx_signals_ticker_date on signals(ticker, date desc);
create index if not exists idx_news_ticker_published on news(ticker, published_at desc);

-- 画面表示を「銘柄ごとの最新シグナル」中心にするためのview。
-- フロント側を後で signals から latest_signals に切り替えると、読み込み行数を抑えられる。
create or replace view latest_signals as
select distinct on (ticker)
  *
from signals
order by ticker, date desc;

-- 古い表示用データを削除する関数。
-- prices: チャート表示用。180日を残す。
-- signals: 履歴確認用。400日を残す。
-- news: 最新ニュース表示用。90日を残す。
create or replace function prune_free_tier_data()
returns table (
  deleted_prices bigint,
  deleted_signals bigint,
  deleted_news bigint
)
language plpgsql
as $$
declare
  prices_count bigint;
  signals_count bigint;
  news_count bigint;
begin
  with deleted as (
    delete from prices
    where date < current_date - interval '180 days'
    returning 1
  )
  select count(*) into prices_count from deleted;

  with deleted as (
    delete from signals
    where date < current_date - interval '400 days'
    returning 1
  )
  select count(*) into signals_count from deleted;

  with deleted as (
    delete from news
    where published_at is not null
      and published_at < now() - interval '90 days'
    returning 1
  )
  select count(*) into news_count from deleted;

  return query select prices_count, signals_count, news_count;
end;
$$;

-- 手動実行例:
-- select * from prune_free_tier_data();

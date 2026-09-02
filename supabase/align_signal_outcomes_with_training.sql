-- 本番AI実績を学習・バックテストの条件へ統一するためのスキーマ拡張
-- Supabase SQL Editorで1回だけ実行してください。
-- 実行後、次回の日次バッチが直近45日分を再計算して更新します。

alter table signal_outcomes add column if not exists entry_date date;
alter table signal_outcomes add column if not exists entry_open numeric;
alter table signal_outcomes add column if not exists exit_open numeric;
alter table signal_outcomes add column if not exists exit_reason text;
alter table signal_outcomes add column if not exists benchmark_return numeric;
alter table signal_outcomes add column if not exists excess_return numeric;
alter table signal_outcomes add column if not exists evaluation_version text;

comment on column signal_outcomes.net_return is
  '業種/TOPIXに対する超過リターンから往復コスト0.2%を控除した値。';
comment on column signal_outcomes.evaluation_version is
  'next_open_stop_excess_v1: 翌営業日始値約定、8%損切り、5営業日後始値決済。';

-- 本番AI買い候補の実績台帳・モデル世代管理を追加
-- Supabase SQL Editorで手動実行してください。

alter table signals add column if not exists model_version text;

create table if not exists signal_outcomes (
  ticker text not null,
  signal_date date not null,
  outcome_date date not null,
  entry_close numeric not null,
  exit_close numeric not null,
  gross_return numeric not null,
  net_return numeric not null,
  ml_score numeric,
  ml_threshold numeric,
  model_version text not null default 'legacy',
  sector text,
  primary key (ticker, signal_date),
  foreign key (ticker, signal_date) references signals(ticker, date) on delete cascade
);

create index if not exists idx_signal_outcomes_outcome_date
  on signal_outcomes(outcome_date desc);
create index if not exists idx_signal_outcomes_model_version
  on signal_outcomes(model_version, outcome_date desc);

alter table signal_outcomes enable row level security;
grant select on table signal_outcomes to anon, authenticated;
grant all on table signal_outcomes to service_role;

drop policy if exists "public read signal outcomes" on signal_outcomes;
create policy "public read signal outcomes"
on signal_outcomes for select
using (true);

-- 2026-09: 学習/バックテストと本番実績を同じ約定・評価条件にそろえるための拡張。
-- 既存行は日次バッチが直近45日分を新条件で再計算して更新する。
alter table signal_outcomes add column if not exists entry_date date;
alter table signal_outcomes add column if not exists entry_open numeric;
alter table signal_outcomes add column if not exists exit_open numeric;
alter table signal_outcomes add column if not exists exit_reason text;
alter table signal_outcomes add column if not exists benchmark_return numeric;
alter table signal_outcomes add column if not exists excess_return numeric;
alter table signal_outcomes add column if not exists evaluation_version text;

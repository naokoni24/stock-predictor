-- MLモデル予測結果用カラムを追加
alter table signals add column if not exists ml_signal text;
alter table signals add column if not exists ml_score numeric;

-- MACD・ボリンジャーバンド用カラムを追加
alter table signals add column if not exists macd numeric;
alter table signals add column if not exists macd_signal numeric;
alter table signals add column if not exists bb_upper numeric;
alter table signals add column if not exists bb_lower numeric;

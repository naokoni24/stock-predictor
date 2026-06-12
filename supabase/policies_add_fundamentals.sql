-- ファンダメンタル指標(PER/PBR/アナリスト目標株価/予想EPS)用のカラムを追加
alter table stocks add column if not exists per numeric;
alter table stocks add column if not exists pbr numeric;
alter table stocks add column if not exists target_price numeric;
alter table stocks add column if not exists forecast_eps numeric;

-- signalsテーブルの重複行(同じticker・同じdate)を解消し、再発防止のためユニーク制約を追加する
-- Supabase SQL Editorで実行してください。

-- 各ticker・dateごとに1行だけ残す
delete from signals a
using signals b
where a.ticker = b.ticker
  and a.date = b.date
  and a.ctid < b.ctid;

-- 今後の重複を防ぐためユニーク制約を追加
alter table signals add constraint signals_ticker_date_key unique (ticker, date);

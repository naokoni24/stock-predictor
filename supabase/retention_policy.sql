-- データ保持期間ルール
-- prices / signals / news: 1年
-- Supabase SQL Editor で手動実行する
-- 定期実行は不要（GitHub Actions の daily-signals.yml から呼び出す想定）

delete from prices
  where date < current_date - interval '1 year';

delete from signals
  where date < current_date - interval '1 year';

delete from news
  where published_at < now() - interval '1 year';

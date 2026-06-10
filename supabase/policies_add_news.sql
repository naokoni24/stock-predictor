-- 銘柄ニュース(タイトル・センチメント)
create table if not exists news (
  id bigserial primary key,
  ticker text references stocks(ticker) on delete cascade,
  title text not null,
  url text not null,
  source text,
  published_at timestamptz,
  sentiment text,          -- 'positive' | 'negative' | 'neutral'
  sentiment_score numeric, -- -1.0 〜 1.0
  created_at timestamptz default now(),
  unique (ticker, url)
);

create index if not exists idx_news_published on news(published_at desc);
create index if not exists idx_news_ticker_published on news(ticker, published_at desc);

alter table news enable row level security;
create policy "public read news" on news for select using (true);

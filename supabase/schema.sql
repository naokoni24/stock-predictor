-- 銘柄マスタ
create table if not exists stocks (
  ticker text primary key,        -- 例: 7203.T
  name text not null
);

-- 日次株価
create table if not exists prices (
  ticker text references stocks(ticker) on delete cascade,
  date date not null,
  open numeric,
  high numeric,
  low numeric,
  close numeric,
  volume bigint,
  primary key (ticker, date)
);

-- シグナル/おすすめ（バッチ処理の結果）
create table if not exists signals (
  ticker text references stocks(ticker) on delete cascade,
  date date not null,
  close numeric,
  sma25 numeric,
  sma75 numeric,
  rsi14 numeric,
  macd numeric,
  macd_signal numeric,
  bb_upper numeric,
  bb_lower numeric,
  signal text,           -- 'buy_candidate' | 'sell_candidate' | 'hold' | null
  score numeric,         -- おすすめ度ランキング用スコア
  primary key (ticker, date)
);

-- 保有株（認証なし簡易版・単一ユーザー想定）
create table if not exists holdings (
  id bigserial primary key,
  ticker text references stocks(ticker) on delete cascade,
  shares numeric not null,
  cost_price numeric not null,
  created_at timestamptz default now()
);

create index if not exists idx_prices_ticker_date on prices(ticker, date desc);
create index if not exists idx_signals_date on signals(date desc);

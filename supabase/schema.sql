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
  ml_signal text,        -- MLによる買い候補/様子見
  ml_score numeric,      -- 予測確率ではなく、モデル内での相対スコア(0〜1)
  ml_threshold numeric,  -- 当日に業種・相場環境を反映して適用したAI買いしきい値
  ml_block_reasons text[], -- AI買いを見送った理由
  model_version text,    -- 推論に使ったモデル世代(特徴量版+モデルファイルハッシュ)
  primary key (ticker, date)
);

-- 本番AI買い候補の確定実績(シグナル日終値から5営業日後終値)
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
create index if not exists idx_signal_outcomes_outcome_date on signal_outcomes(outcome_date desc);

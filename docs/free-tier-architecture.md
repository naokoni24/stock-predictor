# 無料枠を前提にした設計見直し

このアプリは「精度を落とさず、無料枠で毎日運用する」ことを優先する。
方針は、予測精度に効く計算は維持し、保存量・表示クエリ・実行頻度だけを絞ること。

## 現在の無料枠前提

- Vercel Hobby: 個人プロジェクト向けの無料プラン。目安として Edge Requests 100万/月、Fast Data Transfer 100GB/月、Functions は Active CPU 4時間/月、Invocations 100万/月の枠がある。
- Supabase Free: Nano compute、DB推奨サイズ500MB、Egress 5GB/月、Free projectは2つまで。
- GitHub Actions: public repository の標準GitHub-hosted runnerは無料。private repositoryの場合はGitHub Freeで2,000分/月が目安。

上限は変わることがあるため、大きな機能追加前に公式料金ページを確認する。

## 精度を落とさないために維持するもの

- 対象銘柄の幅はむやみに削らない。固定の主力銘柄に加え、Yahoo Finance screenerで日々動く銘柄を拾う構成は維持する。
- ML特徴量は維持する。SMA、RSI、MACD、ボリンジャーバンド、出来高比率、出来高を伴う上昇/下落、日経平均/業種平均に対する相対強弱、52週高安値位置、日経平均・TOPIX・ドル円・NASDAQ・SOXの市場環境、業種one-hotは削らない。
- モデル再学習は月1回を維持する。毎日は不要だが、月1回の再学習は市場変化への追従に効く。
- 日次シグナルは市場データの最新日付で保存する。土日・休場日に同じ価格を別日付で増やさない。
- ニュース取得は無料のGoogle News RSSを維持する。有料APIは追加しない。

## 無料枠のために削ってよいもの

- DBに残す古い価格データ。フロントのチャートは直近データ中心で、ML学習はyfinanceから直接取得しているため、DBに何年分も残す必要はない。
- 古いニュース。画面では最新数件だけ使うため、90日より古いニュースは原則削除してよい。
- 古いhold/sell/buyの全履歴表示。履歴分析機能を作るまでは、画面用には銘柄ごとの最新シグナルを優先する。
- 画面表示時の全件読み込み。Supabase FreeのDB/egressを守るため、最新行だけを返すview/RPCへ寄せる。

## 推奨アーキテクチャ

### 1. バッチ処理はGitHub Actionsに集約

Vercel Functionsで株価取得や学習をしない。yfinance、JPX一覧、Google News RSSへのアクセスはGitHub Actionsで実行し、結果だけSupabaseに保存する。

- daily-signals: 1日1回、取引終了後に株価・指標・ニュースを更新
- monthly-retrain: 月1回、モデル再学習
- maintenance: 週1回、古いDB行の削除とサイズ確認

この構成なら、Vercelは表示だけを担当し、無料枠を消費しにくい。

### 1.5. 日次分析対象は優先度順に絞る

JPX上場銘柄一覧で候補範囲は広げるが、無料枠を守るため、毎日フル分析する銘柄数には上限を設ける。
現在は `MAX_DAILY_TICKERS = 150`。

優先順位:

1. 固定の主力銘柄 `TICKERS`
2. 保有株
3. 前回の買い候補/売り候補
4. Yahoo Finance screenerの値上がり/値下がり上位
5. JPX上場銘柄一覧からの補充

これにより、監視候補は広く持ちながら、毎日のyfinance取得回数・Supabase保存量・GitHub Actions実行時間を制御する。

### 2. DB保存量を制限する

目安:

- prices: 直近180営業日
- signals: 直近400日、または銘柄ごと最新 + バックテスト確認用の必要期間
- news: 直近90日
- stocks: 削除しない
- holdings: ユーザー入力なので削除しない

精度面では、モデル学習はDBではなくyfinanceから2年分を取得しているため、DB側の古いprices削除で予測精度は落ちない。

### 3. 最新シグナル取得をDB側に寄せる

現在の画面は `signals` を日付降順で取得し、アプリ側で銘柄ごとの最新行を残している。
データが増えるとSupabaseから余計な行を読むため、以下のviewを追加するのが望ましい。

```sql
create or replace view latest_signals as
select distinct on (ticker)
  *
from signals
order by ticker, date desc;
```

将来、ホーム・銘柄一覧・保有株ページは `signals` ではなく `latest_signals` を読む。
これにより表示速度とegressを抑えられる。

### 4. フロントはキャッシュしすぎない

シグナルは1日1回更新なので、公開ページは5〜15分程度キャッシュしても精度体感は落ちにくい。
ただし保有株ページは個人データを含むため、ユーザー共通キャッシュには載せない。

優先度:

1. ホームの買い/売り候補とニュースを短時間キャッシュ
2. 銘柄一覧を短時間キャッシュ
3. 保有株はキャッシュしない

### 5. 監視は無料の範囲でログ中心

外部監視サービスは追加しない。
GitHub Actionsのログに以下を出す。

- 処理対象銘柄数
- 取得失敗銘柄数
- Supabaseへ保存したprices/signals/news件数
- DB削除件数
- model.pkl更新有無

失敗時はGitHub Actionsの通知で検知する。

## 実装優先順位

1. 休場日の重複シグナル日付を防ぐ。
2. holdingsを認証ユーザー限定にする。
3. DBメンテナンスSQLを追加し、古いprices/news/signalsを削除する。
4. `latest_signals` viewを追加し、画面の読み込みを最新行中心にする。
5. 公開ページだけ短時間キャッシュする。
6. READMEに無料枠運用ルールを追記する。
7. 日次分析対象を優先度順に最大150銘柄へ制限する。

## 避けること

- 有料APIの導入。
- 銘柄数を大きく削ること。
- ML特徴量を削ること。
- Vercel Functionsで重いPython処理を実行すること。
- DB容量対策として、保有株や銘柄マスタの必要データを削ること。

## 無料で精度改善しやすい追加特徴量

有料APIを使わずに精度改善を狙う場合は、個別銘柄の指標だけでなく、市場全体の地合いを入れる。
日経平均・TOPIX・ドル円・NASDAQ・SOXはyfinanceから無料で取得でき、既存の月次再学習・日次推論に組み込める。

追加済みの市場環境データ:

- 日経平均: `^N225`
- TOPIX: `^TOPX`、取得できない場合はTOPIX連動ETFの `1306.T`
- ドル円: `JPY=X`
- NASDAQ: `^IXIC`
- SOX指数: `^SOX`

各データから作る特徴量:

- `return_1d`
- `return_5d`
- `return_20d`
- `sma25_ratio`
- `sma75_ratio`
- `rsi14`
- `volatility_20d`

これにより、個別銘柄が強く見えても市場全体が下落局面かどうかをモデルが判断しやすくなる。
既存の `model.pkl` は旧特徴量のまま動作し、次回 `scripts/train_model.py` を実行して再学習した時点で新特徴量が有効になる。

## 業種別の相対強弱

同じ業種の平均リターンと個別銘柄のリターンを比較する特徴量も追加済み。
強い業種の中でもさらに強い銘柄か、業種全体の上昇に乗っているだけかをモデルが判断しやすくなる。

追加済みの特徴量:

- `sector_return_5d`
- `sector_return_20d`
- `sector_relative_strength_5d`
- `sector_relative_strength_20d`

業種情報はJPX上場銘柄一覧の33業種区分を使うため、追加API費用はかからない。

## 出来高を伴う上昇/下落

価格の上昇や下落が、出来高を伴っているかを特徴量化済み。
同じ5日上昇でも、薄い出来高で上がった銘柄と、出来高を伴って上がった銘柄をモデルが区別しやすくなる。

追加済みの特徴量:

- `volume_price_momentum_5d`
- `volume_price_momentum_20d`
- `volume_up_pressure_5d`
- `volume_down_pressure_5d`

既存のyfinance株価・出来高だけで計算するため、追加API費用はかからない。

## ML買いしきい値の自動最適化

固定値だけで買い候補を判定すると、市場環境やモデル更新後のスコア分布に合わないことがある。
そのため、`scripts/train_model.py` の再学習時にテストデータでバックテストし、買い判定しきい値を自動選択する。

現在の設計:

- 候補しきい値は `0.40` 〜 `0.80`
- 5営業日後リターン、勝率、+2%以上の的中率を評価
- 取引数が少なすぎるしきい値は除外
- 採用した値を `model.pkl` の `ml_buy_threshold` に保存
- 日次推論では `model.pkl` 内のしきい値を使う

これにより、有料データを増やさず、既存モデルのスコアをより実運用に合う形で使える。

## 参考リンク

- Vercel Pricing: https://vercel.com/pricing
- Supabase Billing: https://supabase.com/docs/guides/platform/billing-on-supabase
- Supabase Compute and Disk: https://supabase.com/docs/guides/platform/compute-and-disk
- GitHub Actions Billing: https://docs.github.com/en/billing/concepts/product-billing/github-actions

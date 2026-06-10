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
- ML特徴量は維持する。SMA、RSI、MACD、ボリンジャーバンド、出来高比率、相対強弱、52週高安値位置、業種one-hotは削らない。
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

## 避けること

- 有料APIの導入。
- 銘柄数を大きく削ること。
- ML特徴量を削ること。
- Vercel Functionsで重いPython処理を実行すること。
- DB容量対策として、保有株や銘柄マスタの必要データを削ること。

## 参考リンク

- Vercel Pricing: https://vercel.com/pricing
- Supabase Billing: https://supabase.com/docs/guides/platform/billing-on-supabase
- Supabase Compute and Disk: https://supabase.com/docs/guides/platform/compute-and-disk
- GitHub Actions Billing: https://docs.github.com/en/billing/concepts/product-billing/github-actions

# AI Stock Signal (stock-predictor)

日本株(`.T`ティッカー)向けの株価シグナル予測・ニュース確認・保有株管理を行うWebアプリ。
完全無料運用(Vercel Hobby / Supabase Free / GitHub Actions無料枠)を前提に設計している。

## 画面構成

- `/`: 本日のおすすめ(買い候補/売り候補タブ)、AI注目銘柄、マーケットニュース。
- `/holdings`: 保有株のCRUD、損益・リスク表示、推奨損切り価格、資産配分グラフ。認証必須。
- `/stocks`: 登録銘柄一覧、検索。
- `/stock/[ticker]`: 銘柄詳細(ローソク足チャート、テクニカル指標、AI分析、AIスコア履歴、ファンダメンタル指標)。
- `/login`、`/forgot-password`、`/reset-password`: Supabase Authによる認証。

## 技術構成

- フロントエンド: Next.js (App Router) + TypeScript、shadcn/ui、Tailwind CSS、next-themes。
- DB / Auth: Supabase Postgres + Auth + RLS。
- バッチ / ML: Python(yfinance、pandas、scikit-learn、LightGBM、joblib、Optuna)。
- ホスティング: Vercel Hobby。
- 定期実行: GitHub Actions(`daily-signals.yml`、`monthly-retrain.yml`)。
- スケジュール失敗時の自動修復: Vercel Cron(`/api/cron/repair-check`)。

無料枠を維持するための設計方針は [docs/free-tier-architecture.md](docs/free-tier-architecture.md) を参照。

## セットアップ(フロントエンド)

```bash
npm install
npm run dev
```

[http://localhost:3010](http://localhost:3010) で確認できる(`package.json` の `dev` スクリプトでポート3010を指定)。

`.env.local` に以下を設定する。

```
NEXT_PUBLIC_SUPABASE_URL=...
NEXT_PUBLIC_SUPABASE_ANON_KEY=...
```

## セットアップ(バッチ/ML・Python)

```bash
python3 -m venv scripts/venv
scripts/venv/bin/pip install -r scripts/requirements.txt
```

環境変数(バッチ実行時に必要):

```
SUPABASE_URL=...
SUPABASE_SERVICE_KEY=...
```

主なスクリプト:

- `scripts/fetch_and_signal.py`: 日次の株価取得・テクニカル指標計算・シグナル生成・ML推論。
- `scripts/fetch_news.py`: Google News RSSからニュース取得・簡易センチメント分析。
- `scripts/train_model.py`: MLモデルの月次再学習(RandomForest / GradientBoosting / LightGBMのVotingClassifier)。
- `scripts/backtest_ml.py`: 月次walk-forward方式のバックテスト。
- `scripts/evaluate_signal_outcomes.py`: AI買い候補を翌営業日始値で約定し、8%損切りまたは5営業日後始値で決済して、業種/TOPIX超過リターン（往復コスト0.2%控除後）を本番実績として保存。
- `scripts/apply_retention.py`: prices/signals/newsの保持期間ルールに基づく古いデータの削除。

### macOSでLightGBMがロードできない場合

macOS用の`lightgbm`標準wheelはHomebrew版`libomp`(OpenMPランタイム)の存在を前提にしている。
Homebrewが無い環境では`import lightgbm`が`Library not loaded: @rpath/libomp.dylib`で失敗するため、
OpenMPを無効にしたソースビルドに切り替える。

```bash
scripts/venv/bin/pip install cmake
scripts/venv/bin/pip uninstall -y lightgbm
scripts/venv/bin/pip install lightgbm --no-binary lightgbm \
  --config-settings=cmake.define.USE_OPENMP=OFF
```

シングルスレッド動作になるが、日次/月次バッチの規模では実用上問題ない。

## GitHub Actions

- **daily-signals**: 毎日15:30 JSTに実行。株価・テクニカル指標・シグナルを更新し、5営業日後に確定したAI買い候補の本番実績を保存してから、ニュース更新・データ保持期間ルールを適用する。終値が欠損・未更新の銘柄だけを対象にした修復実行が17:00 JSTにも走る(`REPAIR_MISSING_CLOSES_ONLY=1`)。
- **monthly-retrain**: 月1回実行。MLモデルを再学習し、`scripts/model.pkl` に差分があればbotがcommitする。

いずれも `workflow_dispatch` で手動実行できる。`daily-signals`は`repair_only`入力(`'1'`で修復モード)を指定できる。必要なSecrets: `SUPABASE_URL`、`SUPABASE_SERVICE_KEY`。

## Vercel Cron(スケジュール失敗時の自動修復)

GitHub Actionsの`schedule`イベント自体が高負荷等で大幅遅延・未発火になるケースへの
フェイルセーフとして、GitHub ActionsとVercelという別々の実行基盤にまたがる監視を行う。

- `vercel.json`で1日2回(17:45 JST頃・19:00 JST頃)、`src/app/api/cron/repair-check`を呼び出す。17:45は17:00修復実行の想定遅延を見込んだ早期検知、19:00は17:45のVercel Cron自体が飛んだ場合の最終保険(判定ロジックが冪等なので2本立てても正規の実行と競合しない)。
- このAPIは`daily-signals`の本日(JST)分の実行履歴をGitHub REST APIで確認し、
  実行中・完了済みの実行が1件も無い場合だけ、`repair_only=1`で`workflow_dispatch`を起動する。
- 必要なVercel環境変数:
  - `CRON_SECRET`: Vercel CronからのリクエストであることをAuthorizationヘッダーで検証する。
  - `GITHUB_ACTIONS_TOKEN`: このリポジトリ限定・Actions読み書き権限のfine-grained PAT。
- 詳細は [docs/free-tier-architecture.md](docs/free-tier-architecture.md) の「スケジュール未発火に対するフェイルセーフ」を参照。

## Supabaseスキーマ変更

スキーマ変更は自動実行せず、`supabase/` 配下にSQLを追加してSQL Editorで手動実行する運用にしている。

## 検証コマンド

```bash
python3 -m py_compile scripts/train_model.py scripts/fetch_and_signal.py scripts/backtest_ml.py scripts/fetch_news.py
npx tsc --noEmit
git diff --check
```

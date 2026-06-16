# CLAUDE.md — stock-predictor 作業ルール

## 作業前後の必須手順

1. **作業前**: `/Users/nao/Documents/Obsidian Vault/stock-predictor/stock-predictor.md` を読む。
2. **作業後**: 同ファイルに作業内容・検証結果・コミットハッシュを追記し、`最終更新` 日付を更新する。
3. **変更後**: 検証を実行し、問題なければ `main` へ push する。

## 基本方針

- 完全無料運用を維持する。Vercel Hobby、Supabase Free、GitHub Actions 無料枠の範囲で設計する。
- 有料 API、常時稼働サーバー、新しい有料サービスは追加しない。
- 説明・コメント・ドキュメントは日本語中心。
- Supabase のスキーマ変更は `supabase/` 配下に SQL を追加し、ユーザーが SQL Editor で手動実行する。
- `.claude/` が未追跡で存在していても勝手に削除・コミットしない。

## よく使う確認コマンド

```bash
python3 -m py_compile scripts/train_model.py scripts/fetch_and_signal.py scripts/backtest_ml.py
npx tsc --noEmit
git diff --check
```

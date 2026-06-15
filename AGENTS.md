# 開発引き継ぎルール

このリポジトリで作業するエージェントは、毎回以下を守る。

1. 作業前に `/Users/nao/Documents/Obsidian Vault/stock-predictor/stock-predictor.md` を読む。
2. 作業後に同ファイルへ作業内容・検証結果・pushしたコミットを追記する。
3. 変更後は必要な検証を実行し、問題なければ `main` にpushする。

## 基本方針

- ユーザーへの説明、コメント、ドキュメントは日本語で書く。
- 完全無料運用を維持する。Vercel Hobby、Supabase Free、GitHub Actions無料枠の範囲で設計する。
- 有料API、常時稼働サーバー、新しい有料サービスは追加しない。
- Supabaseのスキーマ変更は `supabase/` 配下にSQLを追加し、ユーザーにSQL Editorで手動実行してもらう。
- 既存のユーザー変更を勝手に戻さない。
- `.claude/` が未追跡で存在していても勝手に削除・コミットしない。

## よく使う確認コマンド

- `python3 -m py_compile scripts/train_model.py scripts/fetch_and_signal.py scripts/backtest_ml.py`
- `npx tsc --noEmit`
- `git diff --check`


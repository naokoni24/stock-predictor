-- AIシグナルの判定根拠表示用カラムを追加
-- Supabase SQL Editorで手動実行してください。
-- ml_score は上昇確率ではなく、モデル内での相対スコア(0〜1)です。

alter table signals add column if not exists ml_threshold numeric;
alter table signals add column if not exists ml_block_reasons text[];

"""古いデータを削除する保持期間ルール: prices/signals/news/outcomes=1年"""
import os
from supabase import create_client
from datetime import date, timedelta

url = os.environ["SUPABASE_URL"]
key = os.environ["SUPABASE_SERVICE_KEY"]
supabase = create_client(url, key)

one_year_ago = (date.today() - timedelta(days=365)).isoformat()

r = supabase.table("prices").delete().lt("date", one_year_ago).execute()
print(f"prices 削除: {len(r.data)}件 (< {one_year_ago})")

r = supabase.table("signals").delete().lt("date", one_year_ago).execute()
print(f"signals 削除: {len(r.data)}件 (< {one_year_ago})")

try:
    r = supabase.table("signal_outcomes").delete().lt("outcome_date", one_year_ago).execute()
    print(f"signal_outcomes 削除: {len(r.data)}件 (< {one_year_ago})")
except Exception as e:
    # 手動SQL未適用の間も、既存テーブルの保持期間処理は継続する。
    if "signal_outcomes" not in str(e):
        raise
    print("signal_outcomesテーブルが未作成のため、実績台帳の保持期間処理をスキップします。")

r = supabase.table("news").delete().lt("published_at", one_year_ago + "T00:00:00").execute()
print(f"news 削除: {len(r.data)}件 (< {one_year_ago})")

"""本番AI買い候補を、シグナル日終値から5営業日後終値で確定評価して保存する。"""

import os
from collections import defaultdict
from datetime import date, timedelta

from supabase import create_client

OUTCOME_HORIZON_DAYS = 5
TRANSACTION_COST = 0.002
LOOKBACK_CALENDAR_DAYS = 30
PAGE_SIZE = 1000


def _sector_from_joined_stock(value) -> str | None:
    if isinstance(value, list):
        value = value[0] if value else None
    return value.get("sector") if isinstance(value, dict) else None


def build_outcome_rows(signal_rows: list[dict], price_rows: list[dict]) -> list[dict]:
    """候補と価格履歴から、確定した5営業日後の実績行を作る(外部I/Oなし)。"""
    prices_by_ticker: dict[str, list[dict]] = defaultdict(list)
    for price in price_rows:
        if price.get("close") is not None:
            prices_by_ticker[price["ticker"]].append(price)
    for prices in prices_by_ticker.values():
        prices.sort(key=lambda row: row["date"])

    outcomes = []
    for signal in signal_rows:
        entry_close = signal.get("close")
        signal_date = signal.get("date")
        if entry_close is None or not signal_date or entry_close <= 0:
            continue
        future_prices = [
            price for price in prices_by_ticker.get(signal["ticker"], [])
            if price["date"] > signal_date
        ]
        if len(future_prices) < OUTCOME_HORIZON_DAYS:
            continue
        outcome_price = future_prices[OUTCOME_HORIZON_DAYS - 1]
        exit_close = outcome_price["close"]
        gross_return = exit_close / entry_close - 1
        outcomes.append(
            {
                "ticker": signal["ticker"],
                "signal_date": signal_date,
                "outcome_date": outcome_price["date"],
                "entry_close": float(entry_close),
                "exit_close": float(exit_close),
                "gross_return": round(float(gross_return), 8),
                "net_return": round(float(gross_return - TRANSACTION_COST), 8),
                "ml_score": signal.get("ml_score"),
                "ml_threshold": signal.get("ml_threshold"),
                "model_version": signal.get("model_version") or "legacy",
                "sector": _sector_from_joined_stock(signal.get("stocks")),
            }
        )
    return outcomes


def fetch_all_prices(sb, tickers: list[str], since: str, until: str) -> list[dict]:
    """Supabaseの既定取得上限を越えても価格行を取り切る。"""
    rows = []
    for offset in range(0, 10_000, PAGE_SIZE):
        response = (
            sb.table("prices")
            .select("ticker, date, close")
            .in_("ticker", tickers)
            .gte("date", since)
            .lte("date", until)
            .order("date", desc=False)
            .range(offset, offset + PAGE_SIZE - 1)
            .execute()
        )
        page = response.data or []
        rows.extend(page)
        if len(page) < PAGE_SIZE:
            break
    return rows


def main():
    sb = create_client(os.environ["SUPABASE_URL"], os.environ["SUPABASE_SERVICE_KEY"])
    today = date.today()
    since = (today - timedelta(days=LOOKBACK_CALENDAR_DAYS)).isoformat()
    try:
        signal_response = (
            sb.table("signals")
            .select("ticker, date, close, ml_score, ml_threshold, model_version, stocks(sector)")
            .eq("ml_signal", "buy_candidate")
            .gte("date", since)
            .lte("date", today.isoformat())
            .order("date", desc=False)
            .limit(500)
            .execute()
        )
    except Exception as exc:
        # 手動SQLが未適用の状態では、日次バッチ全体を止めずに次回へ持ち越す。
        if "model_version" in str(exc):
            print("モデル世代カラムが未追加のため、本番実績評価をスキップします。")
            return
        raise

    signal_rows = signal_response.data or []
    if not signal_rows:
        print("確定待ちを含むAI買い候補はありません。")
        return
    tickers = sorted({row["ticker"] for row in signal_rows})
    price_rows = fetch_all_prices(sb, tickers, since, today.isoformat())
    outcome_rows = build_outcome_rows(signal_rows, price_rows)
    if not outcome_rows:
        print("5営業日後の終値が未確定のため、本番実績の追加はありません。")
        return
    sb.table("signal_outcomes").upsert(outcome_rows, on_conflict="ticker,signal_date").execute()
    wins = sum(1 for row in outcome_rows if row["net_return"] > 0)
    average = sum(row["net_return"] for row in outcome_rows) / len(outcome_rows)
    print(
        f"本番実績を保存: {len(outcome_rows)}件 / "
        f"勝率 {wins / len(outcome_rows) * 100:.1f}% / "
        f"平均ネットリターン {average * 100:+.2f}%"
    )


if __name__ == "__main__":
    main()

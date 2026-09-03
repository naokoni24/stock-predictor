"""本番AI買い候補を、学習・バックテストと同じ約定条件で確定評価して保存する。"""

import os
from collections import defaultdict
from datetime import date, timedelta

import pandas as pd
import yfinance as yf
from supabase import create_client

OUTCOME_HORIZON_DAYS = 5
TRANSACTION_COST = 0.002
STOP_LOSS_PCT = 0.08
# シグナル日から翌営業日約定、5営業日保有後の始値決済までを評価するため、余裕を持たせる。
LOOKBACK_CALENDAR_DAYS = 45
PAGE_SIZE = 1000
# 取得ループの安全弁。45日窓の価格が3万行程度なので十分な余裕を持たせている。
MAX_FETCH_PAGES = 200
# 1回のupsertが大きくなりすぎないように分割して保存する。
UPSERT_CHUNK_SIZE = 500
EVALUATION_VERSION = "next_open_stop_excess_v1"


def _sector_from_joined_stock(value) -> str | None:
    if isinstance(value, list):
        value = value[0] if value else None
    return value.get("sector") if isinstance(value, dict) else None


def _valid_price(value) -> bool:
    return value is not None and pd.notna(value) and float(value) > 0


def simulate_trade(prices: list[dict], signal_date: str) -> dict | None:
    """翌営業日始値で約定し、損切りまたは5営業日後始値で決済する。"""
    future = [price for price in prices if price["date"] > signal_date and _valid_price(price.get("open"))]
    if len(future) < OUTCOME_HORIZON_DAYS + 1:
        return None

    entry = future[0]
    entry_open = float(entry["open"])
    # 学習時のcompute_barrier_outcomeと同じく、entry日を含む5営業日の間だけ損切りを判定する。
    for price in future[:OUTCOME_HORIZON_DAYS]:
        if not _valid_price(price.get("low")):
            return None
        if float(price["open"]) <= entry_open * (1 - STOP_LOSS_PCT):
            exit_open = float(price["open"])
            return {
                "entry_date": entry["date"], "entry_open": entry_open,
                "outcome_date": price["date"], "exit_open": exit_open,
                "gross_return": exit_open / entry_open - 1, "exit_reason": "stop_gap",
            }
        if float(price["low"]) <= entry_open * (1 - STOP_LOSS_PCT):
            exit_open = entry_open * (1 - STOP_LOSS_PCT)
            return {
                "entry_date": entry["date"], "entry_open": entry_open,
                "outcome_date": price["date"], "exit_open": exit_open,
                "gross_return": -STOP_LOSS_PCT, "exit_reason": "stop_loss",
            }

    exit_price = future[OUTCOME_HORIZON_DAYS]
    exit_open = float(exit_price["open"])
    return {
        "entry_date": entry["date"], "entry_open": entry_open,
        "outcome_date": exit_price["date"], "exit_open": exit_open,
        "gross_return": exit_open / entry_open - 1, "exit_reason": "time_exit",
    }


def topix_return(prices: list[dict], signal_date: str) -> float | None:
    """TOPIX連動ETFの始値リターンを返す。ベンチマークには損切りを適用しない。"""
    future = [price for price in prices if price["date"] > signal_date and _valid_price(price.get("open"))]
    if len(future) < OUTCOME_HORIZON_DAYS + 1:
        return None
    return float(future[OUTCOME_HORIZON_DAYS]["open"]) / float(future[0]["open"]) - 1


def build_outcome_rows(
    signal_rows: list[dict], price_rows: list[dict], sector_by_ticker: dict[str, str | None],
    topix_prices: list[dict],
) -> list[dict]:
    """候補と価格履歴から、学習と同一条件の超過リターン実績を作る(外部I/Oなし)。"""
    prices_by_ticker: dict[str, list[dict]] = defaultdict(list)
    for price in price_rows:
        if _valid_price(price.get("open")):
            prices_by_ticker[price["ticker"]].append(price)
    for prices in prices_by_ticker.values():
        prices.sort(key=lambda row: row["date"])

    simulations: dict[tuple[str, str], dict | None] = {}
    outcomes = []
    for signal in signal_rows:
        signal_date = signal.get("date")
        ticker = signal.get("ticker")
        if not ticker or not signal_date:
            continue
        own = simulate_trade(prices_by_ticker.get(ticker, []), signal_date)
        if own is None:
            continue

        returns_by_ticker = {}
        for peer_ticker, prices in prices_by_ticker.items():
            key = (peer_ticker, signal_date)
            if key not in simulations:
                simulations[key] = simulate_trade(prices, signal_date)
            simulated = simulations[key]
            if simulated is not None:
                returns_by_ticker[peer_ticker] = float(simulated["gross_return"])

        sector = sector_by_ticker.get(ticker)
        sector_returns = [
            value for peer_ticker, value in returns_by_ticker.items()
            if peer_ticker != ticker and sector and sector_by_ticker.get(peer_ticker) == sector
        ]
        # 学習時と同じく、対象を含めて同業種3銘柄に満たない場合はTOPIX、取得不可時は市場平均へ退避する。
        if len(sector_returns) >= 2:
            benchmark_return = sum(sector_returns) / len(sector_returns)
        else:
            benchmark_return = topix_return(topix_prices, signal_date)
            if benchmark_return is None:
                market_returns = [value for peer_ticker, value in returns_by_ticker.items() if peer_ticker != ticker]
                if not market_returns:
                    continue
                benchmark_return = sum(market_returns) / len(market_returns)

        excess_return = float(own["gross_return"]) - benchmark_return
        outcomes.append(
            {
                "ticker": ticker,
                "signal_date": signal_date,
                "outcome_date": own["outcome_date"],
                # 旧カラムは後方互換のため始値を保存する。新カラムを正式な評価値として使う。
                "entry_close": round(own["entry_open"], 8),
                "exit_close": round(own["exit_open"], 8),
                "entry_date": own["entry_date"],
                "entry_open": round(own["entry_open"], 8),
                "exit_open": round(own["exit_open"], 8),
                "exit_reason": own["exit_reason"],
                "gross_return": round(float(own["gross_return"]), 8),
                "benchmark_return": round(float(benchmark_return), 8),
                "excess_return": round(float(excess_return), 8),
                "net_return": round(float(excess_return - TRANSACTION_COST), 8),
                "ml_score": signal.get("ml_score"),
                "ml_threshold": signal.get("ml_threshold"),
                "model_version": signal.get("model_version") or "legacy",
                "sector": sector,
                "evaluation_version": EVALUATION_VERSION,
            }
        )
    return outcomes


def fetch_all_rows(build_query, label: str) -> list[dict]:
    """PostgRESTの1リクエスト最大1000行の制限を超えて、対象を全件取得する。

    build_queryは`.range()`を付ける前のクエリを毎回新しく組み立てて返す関数。
    行数の上限を設けると、上限を超えた時点で「データが存在しない」のと区別が付かず、
    黙って一部だけを処理してしまうため、ページが埋まらなくなるまで読み切る。
    暴走防止の安全弁として`MAX_FETCH_PAGES`で打ち切り、その場合は明示的に失敗させる。
    ページ境界での取りこぼし・重複を避けるため、build_query側で主キー相当の
    一意な並び順を指定すること。
    """
    rows: list[dict] = []
    for page_index in range(MAX_FETCH_PAGES):
        offset = page_index * PAGE_SIZE
        page = build_query().range(offset, offset + PAGE_SIZE - 1).execute().data or []
        rows.extend(page)
        if len(page) < PAGE_SIZE:
            return rows
    raise RuntimeError(
        f"{label}の取得が{MAX_FETCH_PAGES}ページ({MAX_FETCH_PAGES * PAGE_SIZE}行)を超えました。"
        "取得条件かMAX_FETCH_PAGESを見直してください。"
    )


def fetch_all_prices(sb, since: str, until: str) -> list[dict]:
    """評価対象ユニバース全体のOHLCを取得する。

    以前は最大10,000行で打ち切っていたため、45日窓の`prices`が2万行を超える本番では
    古い十数営業日分しか届かず、それ以降のシグナルが「翌営業日始値から5営業日後始値まで
    の価格が足りない」と判定されて実績台帳に入らないままだった。
    """
    return fetch_all_rows(
        lambda: (
            sb.table("prices")
            .select("ticker, date, open, low")
            .gte("date", since)
            .lte("date", until)
            .order("date", desc=False)
            .order("ticker", desc=False)
        ),
        "価格履歴",
    )


def fetch_topix_prices(since: str, today: date) -> list[dict]:
    """TOPIX連動ETFを無料のyfinanceから取得し、取得失敗時は市場平均へフォールバックする。"""
    try:
        history = yf.Ticker("1306.T").history(start=since, end=(today + timedelta(days=1)).isoformat())
    except Exception as exc:
        print(f"TOPIX benchmark unavailable: {exc}")
        return []
    if history.empty:
        print("TOPIX benchmark unavailable: 1306.T history is empty")
        return []
    history = history.reset_index()
    return [
        {
            "date": pd.to_datetime(row["Date"]).date().isoformat(),
            "open": None if pd.isna(row["Open"]) else float(row["Open"]),
        }
        for _, row in history.iterrows()
    ]


def main():
    sb = create_client(os.environ["SUPABASE_URL"], os.environ["SUPABASE_SERVICE_KEY"])
    today = date.today()
    since = (today - timedelta(days=LOOKBACK_CALENDAR_DAYS)).isoformat()
    try:
        # 評価対象の買い候補も打ち切らずに全件取る(45日窓で400件を超える日がある)。
        signal_rows = fetch_all_rows(
            lambda: (
                sb.table("signals")
                .select("ticker, date, ml_score, ml_threshold, model_version, stocks(sector)")
                .eq("ml_signal", "buy_candidate")
                .gte("date", since)
                .lte("date", today.isoformat())
                .order("date", desc=False)
                .order("ticker", desc=False)
            ),
            "AI買い候補",
        )
    except Exception as exc:
        # 手動SQLが未適用の状態では、日次バッチ全体を止めずに次回へ持ち越す。
        if "model_version" in str(exc):
            print("モデル世代カラムが未追加のため、本番実績評価をスキップします。")
            return
        raise

    if not signal_rows:
        print("確定待ちを含むAI買い候補はありません。")
        return
    # 銘柄マスタは1800件を超えており、単発クエリだと先頭1000件で切れて
    # 業種が引けない銘柄が生まれ、業種ベンチマークが誤ってTOPIXへ退避してしまう。
    stock_rows = fetch_all_rows(
        lambda: sb.table("stocks").select("ticker, sector").order("ticker", desc=False),
        "銘柄マスタ",
    )
    sector_by_ticker = {row["ticker"]: row.get("sector") for row in stock_rows}
    for signal in signal_rows:
        sector_by_ticker.setdefault(signal["ticker"], _sector_from_joined_stock(signal.get("stocks")))
    price_rows = fetch_all_prices(sb, since, today.isoformat())
    outcome_rows = build_outcome_rows(
        signal_rows, price_rows, sector_by_ticker, fetch_topix_prices(since, today)
    )
    if not outcome_rows:
        print("翌営業日始値から5営業日後始値までの評価期間が未確定のため、本番実績の追加はありません。")
        return
    try:
        for start in range(0, len(outcome_rows), UPSERT_CHUNK_SIZE):
            chunk = outcome_rows[start : start + UPSERT_CHUNK_SIZE]
            sb.table("signal_outcomes").upsert(chunk, on_conflict="ticker,signal_date").execute()
    except Exception as exc:
        if any(column in str(exc) for column in ("entry_open", "benchmark_return", "evaluation_version")):
            print(
                "本番評価の新しいカラムが未追加のため保存をスキップします。"
                "Supabase SQL Editorでsupabase/align_signal_outcomes_with_training.sqlを実行してください。"
            )
            return
        raise
    wins = sum(1 for row in outcome_rows if row["net_return"] > 0)
    average = sum(row["net_return"] for row in outcome_rows) / len(outcome_rows)
    print(
        f"本番実績を保存: {len(outcome_rows)}件 / "
        f"勝率 {wins / len(outcome_rows) * 100:.1f}% / "
        f"平均ネット超過リターン {average * 100:+.2f}% ({EVALUATION_VERSION})"
    )


if __name__ == "__main__":
    main()

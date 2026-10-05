"""本番AI買い候補を、学習・バックテストと同じ約定条件で確定評価して保存する。"""

import os
import time
from collections import defaultdict
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

import pandas as pd
import yfinance as yf
from supabase import create_client
from market_calendar import get_market_cutoff, next_trading_dates

OUTCOME_HORIZON_DAYS = 5
TRANSACTION_COST = 0.002
STOP_LOSS_PCT = 0.08
# 画面の90日集計(決済日基準)を現行定義の実績で埋められるよう、シグナル日を100日さかのぼる。
LOOKBACK_CALENDAR_DAYS = 100
# 1回の実行で確定させるシグナル日数。比較銘柄の価格補完でyfinanceの取得制限に当たらないよう、
# 過去分の再計算は新しい日から数日ずつ進める(通常は1日1シグナル日が確定するだけ)。
MAX_DATES_PER_RUN = 8
# 一部の候補だけ確定済みのシグナル日を再試行する期間(評価期間終了からの暦日数)。
RETRY_PARTIAL_DAYS = 14
# 学習(add_excess_return_targets)と同じ外れ値の打ち切り幅。比較銘柄のリターンに適用する。
RETURN_WINSOR_LIMIT = 0.30
# 比較銘柄のうち価格を取得できた割合がこれ未満の日は確定しない。
MIN_PEER_COVERAGE = 0.8
YF_DOWNLOAD_CHUNK_SIZE = 40
# 前日始値比がこの範囲外なら株式分割の未反映とみなす(東証の値幅制限では通常起きない)。
ADJUSTMENT_STEP_MIN_RATIO = 0.6
ADJUSTMENT_STEP_MAX_RATIO = 1.7
PAGE_SIZE = 1000
# 取得ループの安全弁。100日窓の価格でも2万行程度なので十分な余裕を持たせている。
MAX_FETCH_PAGES = 200
# 1回のupsertが大きくなりすぎないように分割して保存する。
UPSERT_CHUNK_SIZE = 500
# v2(2026-10-05): 比較銘柄をシグナル日の分析対象に固定し±30%で打ち切る。v1は分析対象に
# 残り続けた急騰銘柄に比較銘柄が偏り、業種平均が水増しされていた。
EVALUATION_VERSION = "next_open_stop_excess_v2"


def _sector_from_joined_stock(value) -> str | None:
    if isinstance(value, list):
        value = value[0] if value else None
    return value.get("sector") if isinstance(value, dict) else None


def _valid_price(value) -> bool:
    return value is not None and pd.notna(value) and 0 < float(value) < float("inf")


def trading_window(prices: list[dict], signal_date: str) -> list[dict] | None:
    """約定・決済日に欠損がある場合、別の日の価格で期間を延長せず確定を待つ。"""
    by_date = {price["date"]: price for price in prices}
    window = []
    for trading_date in next_trading_dates(signal_date, OUTCOME_HORIZON_DAYS + 1):
        price = by_date.get(trading_date)
        if price is None or not _valid_price(price.get("open")):
            return None
        window.append(price)
    return window


def simulate_trade(prices: list[dict], signal_date: str) -> dict | None:
    """翌営業日始値で約定し、損切りまたは5営業日後始値で決済する。"""
    future = trading_window(prices, signal_date)
    if future is None:
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
    future = trading_window(prices, signal_date)
    if future is None:
        return None
    return float(future[OUTCOME_HORIZON_DAYS]["open"]) / float(future[0]["open"]) - 1


def _group_prices_by_ticker(price_rows: list[dict]) -> dict[str, list[dict]]:
    prices_by_ticker: dict[str, list[dict]] = defaultdict(list)
    for price in price_rows:
        if _valid_price(price.get("open")):
            prices_by_ticker[price["ticker"]].append(price)
    for prices in prices_by_ticker.values():
        prices.sort(key=lambda row: row["date"])
    return prices_by_ticker


def _clip(value: float) -> float:
    return max(-RETURN_WINSOR_LIMIT, min(RETURN_WINSOR_LIMIT, float(value)))


def select_dates_to_settle(
    signal_rows: list[dict], settled_keys: set[tuple[str, str]], cutoff_date: date,
    max_dates: int = MAX_DATES_PER_RUN,
) -> list[str]:
    """評価期間が終わり、まだ現行定義で確定していないシグナル日を新しい順に返す。

    取得できない候補(上場廃止等)が残る古い日で毎回の処理枠を占有しないよう、
    一部確定済みの日はRETRY_PARTIAL_DAYS以内に評価期間が終わった日だけ再試行する。
    """
    candidates_by_date: dict[str, set[str]] = defaultdict(set)
    for signal in signal_rows:
        if signal.get("ticker") and signal.get("date"):
            candidates_by_date[signal["date"]].add(signal["ticker"])
    retry_since = (cutoff_date - timedelta(days=RETRY_PARTIAL_DAYS)).isoformat()
    dates = []
    for signal_date, tickers in candidates_by_date.items():
        window_end = next_trading_dates(signal_date, OUTCOME_HORIZON_DAYS + 1)[-1]
        if window_end > cutoff_date.isoformat():
            continue
        settled = {ticker for ticker in tickers if (ticker, signal_date) in settled_keys}
        if settled == tickers or (settled and window_end < retry_since):
            continue
        dates.append(signal_date)
    return sorted(dates, reverse=True)[:max_dates]


def has_adjustment_step(window: list[dict]) -> bool:
    """評価期間内に株式分割の未反映とみられる段差(前日始値比)があるかを返す。

    日次取得はpricesの直近30行だけを上書きするため、分割後もそれより古い行は分割前の
    価格のまま残り、約30営業日前に段差ができる(2026-09-29の8035.Tの1:5分割で8/13→8/14に
    59,470円→11,423円)。東証の値幅制限内の値動きでは起きない比率を段差とみなす。
    """
    for previous, current in zip(window, window[1:]):
        ratio = float(current["open"]) / float(previous["open"])
        if ratio < ADJUSTMENT_STEP_MIN_RATIO or ratio > ADJUSTMENT_STEP_MAX_RATIO:
            return True
    return False


def tickers_missing_prices(
    price_rows: list[dict], tickers_by_date: dict[str, set[str]]
) -> dict[str, str]:
    """DBの価格では評価期間を正しく計算できない銘柄を、銘柄→最古シグナル日で返す。

    AI買い候補や比較銘柄が翌日以降の日次分析対象(150銘柄)から外れると、pricesの
    保存が止まる。候補は実績台帳に入らず(2026-09は約3割)、比較銘柄は「分析対象に
    残り続けた=急騰が続いた銘柄」に偏っていた。株式分割の未反映で段差がある期間も、
    yfinanceの一貫した調整済み価格で取り直す。
    """
    prices_by_ticker = _group_prices_by_ticker(price_rows)
    since_by_ticker: dict[str, str] = {}
    for signal_date, tickers in tickers_by_date.items():
        for ticker in tickers:
            window = trading_window(prices_by_ticker.get(ticker, []), signal_date)
            if window is None or has_adjustment_step(window):
                since_by_ticker[ticker] = min(since_by_ticker.get(ticker, signal_date), signal_date)
    return since_by_ticker


def build_outcome_rows(
    signal_rows: list[dict], price_rows: list[dict], sector_by_ticker: dict[str, str | None],
    topix_prices: list[dict], universe_by_date: dict[str, set[str]],
    min_peer_coverage: float = MIN_PEER_COVERAGE,
) -> list[dict]:
    """候補と価格履歴から、学習と同一条件の超過リターン実績を作る(外部I/Oなし)。

    比較銘柄はシグナル日の分析対象(universe_by_date)に固定する。以前はDBに評価期間の
    価格がそろった全銘柄を比較対象にしており、分析対象に残り続けた急騰銘柄に偏って
    業種平均が水増しされていた(2026-08〜09の平均ベンチマーク+2.09%、固定後+0.38%)。
    学習時と同じく比較銘柄のリターンは±30%で打ち切る。候補自身のリターンは実際の値を記録する。
    価格を取得できた比較銘柄がmin_peer_coverage未満の日は、偏った平均で確定させず次回へ持ち越す。
    """
    prices_by_ticker = _group_prices_by_ticker(price_rows)

    simulations: dict[tuple[str, str], dict | None] = {}

    def simulated(ticker: str, signal_date: str) -> dict | None:
        key = (ticker, signal_date)
        if key not in simulations:
            simulations[key] = simulate_trade(prices_by_ticker.get(ticker, []), signal_date)
        return simulations[key]

    coverage_ok: dict[str, bool] = {}
    outcomes = []
    for signal in signal_rows:
        signal_date = signal.get("date")
        ticker = signal.get("ticker")
        if not ticker or not signal_date:
            continue
        own = simulated(ticker, signal_date)
        if own is None:
            continue

        universe = universe_by_date.get(signal_date, set()) | {ticker}
        returns_by_ticker = {}
        for peer_ticker in universe:
            result = simulated(peer_ticker, signal_date)
            if result is not None:
                returns_by_ticker[peer_ticker] = _clip(result["gross_return"])
        if signal_date not in coverage_ok:
            coverage = len(returns_by_ticker) / len(universe)
            coverage_ok[signal_date] = coverage >= min_peer_coverage
            if not coverage_ok[signal_date]:
                print(f"{signal_date}: 比較銘柄の価格取得率{coverage:.0%}のため確定を次回へ持ち越します")
        if not coverage_ok[signal_date]:
            continue

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
            if benchmark_return is not None:
                benchmark_return = _clip(benchmark_return)
            else:
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


def fetch_missing_prices(since_by_ticker: dict[str, str], cutoff_date: date) -> list[dict]:
    """分析対象から外れた候補・比較銘柄の始値・安値を無料のyfinanceから取得する(DBには保存しない)。

    日次取得と同じ調整済み価格・桁ずれ補修を使い、未確定のcutoff_date後は除外する。
    """
    from train_model import repair_price_glitches

    tickers = sorted(since_by_ticker)
    end = (cutoff_date + timedelta(days=1)).isoformat()
    rows = []
    for start in range(0, len(tickers), YF_DOWNLOAD_CHUNK_SIZE):
        chunk = tickers[start : start + YF_DOWNLOAD_CHUNK_SIZE]
        since = min(since_by_ticker[ticker] for ticker in chunk)
        for attempt in range(2):
            try:
                data = yf.download(
                    chunk, start=since, end=end, group_by="ticker", auto_adjust=True,
                    progress=False, threads=True,
                )
            except Exception as exc:
                print(f"価格補完に失敗 ({chunk[0]}〜): {exc}")
                data = pd.DataFrame()
            fetched = 0
            for ticker in chunk:
                try:
                    history = data[ticker].dropna(subset=["Open"])
                except (KeyError, TypeError):
                    continue
                if history.empty:
                    continue
                fetched += 1
                history = repair_price_glitches(history.rename_axis("Date").reset_index())
                for _, row in history.iterrows():
                    trading_date = pd.to_datetime(row["Date"]).date()
                    if trading_date > cutoff_date:
                        continue
                    rows.append({
                        "ticker": ticker,
                        "date": trading_date.isoformat(),
                        "open": None if pd.isna(row["Open"]) else float(row["Open"]),
                        "low": None if pd.isna(row["Low"]) else float(row["Low"]),
                    })
            if fetched or attempt:
                break
            time.sleep(30)  # 取得制限時は少し待って1回だけ再試行する
        time.sleep(2)
    return rows


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
    settled_rows = fetch_all_rows(
        lambda: (
            sb.table("signal_outcomes")
            .select("ticker, signal_date")
            .eq("evaluation_version", EVALUATION_VERSION)
            .gte("signal_date", since)
            .order("signal_date", desc=False)
            .order("ticker", desc=False)
        ),
        "確定済み実績",
    )
    cutoff_date, _ = get_market_cutoff(datetime.now(ZoneInfo("Asia/Tokyo")))
    dates = select_dates_to_settle(
        signal_rows, {(row["ticker"], row["signal_date"]) for row in settled_rows}, cutoff_date
    )
    if not dates:
        print("翌営業日始値から5営業日後始値までの評価期間が未確定のため、本番実績の追加はありません。")
        return
    print(f"確定対象のシグナル日: {', '.join(sorted(dates))}")
    target_signals = [signal for signal in signal_rows if signal["date"] in dates]

    # 比較銘柄はシグナル日に分析した銘柄(=その日のsignals)に固定する。
    universe_rows = fetch_all_rows(
        lambda: (
            sb.table("signals").select("ticker, date").in_("date", dates)
            .order("date", desc=False).order("ticker", desc=False)
        ),
        "分析対象",
    )
    universe_by_date: dict[str, set[str]] = defaultdict(set)
    for row in universe_rows:
        universe_by_date[row["date"]].add(row["ticker"])
    for signal in target_signals:
        universe_by_date[signal["date"]].add(signal["ticker"])

    price_rows = fetch_all_prices(sb, min(dates), today.isoformat())
    missing = tickers_missing_prices(price_rows, universe_by_date)
    if missing:
        print(f"分析対象から外れた銘柄の価格を補完: {len(missing)}銘柄")
        supplement = fetch_missing_prices(missing, cutoff_date)
        supplemented = {row["ticker"] for row in supplement}
        price_rows = [row for row in price_rows if row["ticker"] not in supplemented] + supplement
    outcome_rows = build_outcome_rows(
        target_signals, price_rows, sector_by_ticker, fetch_topix_prices(min(dates), today),
        universe_by_date,
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

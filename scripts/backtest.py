"""
過去データを使ったシグナルロジックのバックテスト。

主力銘柄(TICKERS)について過去2年分の株価を取得し、
fetch_and_signal.py と同じロジックでシグナルを計算。
buy_candidateで翌日始値で購入 → sell_candidateで翌日始値で売却、
というシンプルな売買シミュレーションを行い、
各種パラメータ(RSI閾値など)を変えながら成績を比較する。

実行: python scripts/backtest.py
"""

import pandas as pd
import yfinance as yf

from fetch_and_signal import TICKERS, calc_rsi, calc_macd, calc_bollinger


def make_signal_param(row, rsi_buy_max: float, rsi_sell_min: float) -> str | None:
    """rsi_buy_max / rsi_sell_min を変えられるバージョンのシグナル判定"""
    if (
        pd.isna(row["sma25"])
        or pd.isna(row["sma75"])
        or pd.isna(row["rsi14"])
        or pd.isna(row["macd"])
        or pd.isna(row["macd_signal"])
        or pd.isna(row["bb_upper"])
        or pd.isna(row["bb_lower"])
    ):
        return None

    macd_diff = row["macd"] - row["macd_signal"]
    signal = "hold"

    if row["sma25"] > row["sma75"] and row["rsi14"] < rsi_buy_max:
        signal = "buy_candidate"

    if (
        row["sma25"] < row["sma75"]
        or row["rsi14"] > rsi_sell_min
        or macd_diff < 0
        or row["Close"] > row["bb_upper"]
    ):
        signal = "sell_candidate"

    return signal


def load_history() -> dict[str, pd.DataFrame]:
    histories = {}
    for ticker in TICKERS:
        hist = yf.Ticker(ticker).history(period="2y")
        if hist.empty:
            continue
        hist = hist.reset_index()
        hist["sma25"] = hist["Close"].rolling(25).mean()
        hist["sma75"] = hist["Close"].rolling(75).mean()
        hist["rsi14"] = calc_rsi(hist["Close"], 14)
        hist["macd"], hist["macd_signal"] = calc_macd(hist["Close"])
        hist["bb_upper"], hist["bb_lower"] = calc_bollinger(hist["Close"])
        histories[ticker] = hist
    return histories


def simulate(hist: pd.DataFrame, rsi_buy_max: float, rsi_sell_min: float) -> list[float]:
    """1銘柄分の売買シミュレーション。各トレードのリターン(%)のリストを返す"""
    returns = []
    holding = False
    buy_price = None

    for i in range(len(hist) - 1):
        row = hist.iloc[i]
        signal = make_signal_param(row, rsi_buy_max, rsi_sell_min)
        next_open = hist.iloc[i + 1]["Open"]

        if not holding and signal == "buy_candidate":
            holding = True
            buy_price = next_open
        elif holding and signal == "sell_candidate":
            returns.append((next_open - buy_price) / buy_price * 100)
            holding = False
            buy_price = None

    return returns


def evaluate(histories: dict[str, pd.DataFrame], rsi_buy_max: float, rsi_sell_min: float):
    all_returns = []
    for hist in histories.values():
        all_returns.extend(simulate(hist, rsi_buy_max, rsi_sell_min))

    if not all_returns:
        return {"trades": 0, "win_rate": 0.0, "avg_return": 0.0, "total_return": 0.0}

    all_returns = [r for r in all_returns if pd.notna(r)]
    if not all_returns:
        return {"trades": 0, "win_rate": 0.0, "avg_return": 0.0, "total_return": 0.0}
    wins = [r for r in all_returns if r > 0]
    return {
        "trades": len(all_returns),
        "win_rate": len(wins) / len(all_returns) * 100,
        "avg_return": sum(all_returns) / len(all_returns),
        "total_return": sum(all_returns),
    }


def main():
    print("過去2年分の株価を取得中...")
    histories = load_history()
    print(f"{len(histories)}銘柄のデータを取得しました")

    print("\n現在の設定 (RSI買い<70, 売り>70):")
    result = evaluate(histories, 70, 70)
    print(result)

    print("\nパラメータグリッドサーチ:")
    print(f"{'rsi_buy_max':>12} {'rsi_sell_min':>13} {'trades':>7} {'win_rate':>9} {'avg_return':>11} {'total_return':>13}")
    best = None
    for rsi_buy_max in [60, 65, 70]:
        for rsi_sell_min in [70, 75, 80]:
            result = evaluate(histories, rsi_buy_max, rsi_sell_min)
            print(
                f"{rsi_buy_max:>12} {rsi_sell_min:>13} {result['trades']:>7} "
                f"{result['win_rate']:>8.1f}% {result['avg_return']:>10.2f}% {result['total_return']:>12.1f}%"
            )
            if result["trades"] >= 10 and (best is None or result["avg_return"] > best[1]["avg_return"]):
                best = ((rsi_buy_max, rsi_sell_min), result)

    if best:
        print(f"\n最良パラメータ: rsi_buy_max={best[0][0]}, rsi_sell_min={best[0][1]}")
        print(best[1])


if __name__ == "__main__":
    main()

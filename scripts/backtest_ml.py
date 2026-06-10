"""
ルールベースシグナル と MLモデル予測 のバックテスト成績比較。

ルールベース: fetch_and_signal.py の make_signal (buy_candidate/sell_candidate)
MLモデル: scripts/model.pkl の予測確率が閾値以上なら買い、
          一定日数保有 (HOLD_DAYS) して売却

実行: scripts/venv/bin/python scripts/backtest_ml.py
"""

import joblib
import pandas as pd
import yfinance as yf

from fetch_and_signal import TICKERS, calc_rsi, calc_macd, calc_bollinger
from train_model import build_features, FEATURE_COLUMNS, MODEL_PATH

ML_BUY_THRESHOLD = 0.5
HOLD_DAYS = 5


def make_signal_param(row, rsi_buy_max: float = 60, rsi_sell_min: float = 75) -> str | None:
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


def simulate_rule(hist: pd.DataFrame) -> list[float]:
    """ルールベース: buy_candidateで翌日始値で購入 -> sell_candidateで翌日始値で売却"""
    returns = []
    holding = False
    buy_price = None

    for i in range(len(hist) - 1):
        row = hist.iloc[i]
        signal = make_signal_param(row)
        next_open = hist.iloc[i + 1]["Open"]

        if not holding and signal == "buy_candidate":
            holding = True
            buy_price = next_open
        elif holding and signal == "sell_candidate":
            returns.append((next_open - buy_price) / buy_price * 100)
            holding = False
            buy_price = None

    return returns


def simulate_ml(hist: pd.DataFrame, model, features: list[str]) -> list[float]:
    """MLモデル: 上昇確率がML_BUY_THRESHOLD以上で翌日始値で購入 -> HOLD_DAYS後の始値で売却"""
    df = build_features(hist)
    valid = df.dropna(subset=features)
    if valid.empty:
        return []

    probs = model.predict_proba(valid[features])[:, 1]
    df.loc[valid.index, "ml_score"] = probs

    returns = []
    i = 0
    n = len(hist)
    while i < n - 1 - HOLD_DAYS:
        score = df.iloc[i]["ml_score"]
        if pd.notna(score) and score >= ML_BUY_THRESHOLD:
            buy_price = hist.iloc[i + 1]["Open"]
            sell_price = hist.iloc[i + 1 + HOLD_DAYS]["Open"]
            returns.append((sell_price - buy_price) / buy_price * 100)
            i += 1 + HOLD_DAYS
        else:
            i += 1

    return returns


def evaluate(all_returns: list[float]) -> dict:
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
    print(f"{len(histories)}銘柄のデータを取得しました\n")

    bundle = joblib.load(MODEL_PATH)
    model, features = bundle["model"], bundle["features"]

    rule_returns = []
    ml_returns = []
    for hist in histories.values():
        rule_returns.extend(simulate_rule(hist))
        ml_returns.extend(simulate_ml(hist, model, features))

    print("ルールベース (RSI買い<60, 売り>75):")
    print(evaluate(rule_returns))

    print(f"\nMLモデル (上昇確率>={ML_BUY_THRESHOLD}, {HOLD_DAYS}日後に売却):")
    print(evaluate(ml_returns))


if __name__ == "__main__":
    main()

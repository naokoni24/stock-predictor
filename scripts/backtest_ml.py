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

from fetch_and_signal import TICKERS, calc_rsi, calc_macd, calc_bollinger, get_jp_sector_map
from train_model import (
    add_sector_relative_features,
    build_features,
    calibrate_scores,
    get_nikkei_returns,
    FEATURE_COLUMNS,
    MODEL_PATH,
    THRESHOLD_GRID,
)

DEFAULT_ML_BUY_THRESHOLD = 0.55
HOLD_DAYS = 5

# train_model.pyの学習/検証/テスト分割(70%/15%/15%)に合わせ、
# 直近15%(テスト期間相当)のみをout-of-sample評価の対象とする。
# こうしないと学習に使った期間でバックテストしてしまい、成績が楽観的に出てしまう。
TEST_SPLIT_RATIO = 0.85


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


def simulate_rule(hist: pd.DataFrame, start_idx: int = 0) -> list[float]:
    """ルールベース: buy_candidateで翌日始値で購入 -> sell_candidateで翌日始値で売却

    start_idx以降(out-of-sample期間)のみを評価対象とする。
    """
    returns = []
    holding = False
    buy_price = None

    for i in range(start_idx, len(hist) - 1):
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


def simulate_ml(
    hist: pd.DataFrame,
    model,
    features: list[str],
    nikkei: pd.DataFrame,
    require_rule_buy: bool = False,
    threshold: float = DEFAULT_ML_BUY_THRESHOLD,
    sector_columns: list[str] | None = None,
    sector: str | None = None,
    feature_df: pd.DataFrame | None = None,
    score_calibration: list[float] | None = None,
    start_idx: int = 0,
) -> list[float]:
    """MLモデル: 上昇確率がthreshold以上で翌日始値で購入 -> HOLD_DAYS後の始値で売却

    require_rule_buy=Trueの場合、ルールベースもbuy_candidateの日のみ購入対象とする
    (両シグナル一致フィルタ)
    start_idx以降(out-of-sample期間)のみを評価対象とする。
    """
    df = feature_df.copy() if feature_df is not None else build_features(hist, nikkei)
    for col in sector_columns or []:
        df[col] = 1 if col == f"sector_{sector}" else 0
    valid = df.dropna(subset=features)
    if valid.empty:
        return []

    probs = model.predict_proba(valid[features])[:, 1]
    df.loc[valid.index, "ml_score"] = calibrate_scores(probs, score_calibration)

    returns = []
    i = start_idx
    n = len(hist)
    while i < n - 1 - HOLD_DAYS:
        score = df.iloc[i]["ml_score"]
        ml_buy = pd.notna(score) and score >= threshold
        if ml_buy and require_rule_buy:
            ml_buy = make_signal_param(hist.iloc[i]) == "buy_candidate"

        if ml_buy:
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
        "avg_return": float(sum(all_returns) / len(all_returns)),
        "total_return": float(sum(all_returns)),
    }


def main():
    print("過去2年分の株価を取得中...")
    histories = load_history()
    print(f"{len(histories)}銘柄のデータを取得しました\n")

    bundle = joblib.load(MODEL_PATH)
    nikkei = get_nikkei_returns()
    model, features = bundle["model"], bundle["features"]
    sector_columns = bundle.get("sector_columns", [])
    score_calibration = bundle.get("score_calibration")
    ml_buy_threshold = float(bundle.get("ml_buy_threshold", DEFAULT_ML_BUY_THRESHOLD))
    jp_sectors = get_jp_sector_map()
    feature_frames = {
        ticker: build_features(hist, nikkei)
        for ticker, hist in histories.items()
    }
    feature_frames = add_sector_relative_features(feature_frames, jp_sectors)

    rule_returns = []
    ml_returns = []
    consensus_returns = []
    for ticker, hist in histories.items():
        sector = jp_sectors.get(ticker)
        start_idx = int(len(hist) * TEST_SPLIT_RATIO)
        rule_returns.extend(simulate_rule(hist, start_idx=start_idx))
        ml_returns.extend(
            simulate_ml(
                hist,
                model,
                features,
                nikkei,
                threshold=ml_buy_threshold,
                sector_columns=sector_columns,
                sector=sector,
                feature_df=feature_frames.get(ticker),
                score_calibration=score_calibration,
                start_idx=start_idx,
            )
        )
        consensus_returns.extend(
            simulate_ml(
                hist,
                model,
                features,
                nikkei,
                require_rule_buy=True,
                threshold=ml_buy_threshold,
                sector_columns=sector_columns,
                sector=sector,
                feature_df=feature_frames.get(ticker),
                score_calibration=score_calibration,
                start_idx=start_idx,
            )
        )

    print("ルールベース (RSI買い<60, 売り>75):")
    print(evaluate(rule_returns))

    print(f"\nMLモデル単独 (較正後スコア>={ml_buy_threshold}, {HOLD_DAYS}日後に売却):")
    print(evaluate(ml_returns))

    print(f"\n両シグナル一致 (ルール買い候補 かつ ML較正後スコア>={ml_buy_threshold}):")
    print(evaluate(consensus_returns))

    print("\nML_BUY_THRESHOLD グリッドサーチ:")
    print(f"{'threshold':>10} {'trades':>7} {'win_rate':>9} {'avg_return':>11} {'total_return':>13}")
    for threshold in THRESHOLD_GRID:
        returns = []
        for ticker, hist in histories.items():
            sector = jp_sectors.get(ticker)
            start_idx = int(len(hist) * TEST_SPLIT_RATIO)
            returns.extend(
                simulate_ml(
                    hist,
                    model,
                    features,
                    nikkei,
                    threshold=threshold,
                    sector_columns=sector_columns,
                    sector=sector,
                    feature_df=feature_frames.get(ticker),
                    score_calibration=score_calibration,
                    start_idx=start_idx,
                )
            )
        result = evaluate(returns)
        print(
            f"{threshold:>10} {result['trades']:>7} "
            f"{result['win_rate']:>8.1f}% {result['avg_return']:>10.2f}% {result['total_return']:>12.1f}%"
        )


if __name__ == "__main__":
    main()

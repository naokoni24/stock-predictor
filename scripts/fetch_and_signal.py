"""
毎朝実行するバッチ:
1. 対象銘柄の株価をyfinanceで取得
2. テクニカル指標(SMA25/75, RSI14, MACD, ボリンジャーバンド)を計算
3. シグナル(おすすめ/売り時候補)を判定
4. Supabaseに保存

実行: python scripts/fetch_and_signal.py
必要な環境変数: SUPABASE_URL, SUPABASE_SERVICE_KEY
"""

import os
import datetime
import pandas as pd
import yfinance as yf
from supabase import create_client

# 対象銘柄(ティッカー: 名称)。必要に応じて追加・holdingsテーブルと連動させる
TICKERS = {
    "7203.T": "トヨタ自動車",
    "6758.T": "ソニーグループ",
    "9984.T": "ソフトバンクグループ",
    "8306.T": "三菱UFJフィナンシャル・グループ",
    "9432.T": "日本電信電話",
}


def calc_rsi(close: pd.Series, period: int = 14) -> pd.Series:
    delta = close.diff()
    gain = delta.clip(lower=0)
    loss = -delta.clip(upper=0)
    avg_gain = gain.rolling(period).mean()
    avg_loss = loss.rolling(period).mean()
    rs = avg_gain / avg_loss
    return 100 - (100 / (1 + rs))


def calc_macd(close: pd.Series) -> tuple[pd.Series, pd.Series]:
    ema12 = close.ewm(span=12, adjust=False).mean()
    ema26 = close.ewm(span=26, adjust=False).mean()
    macd = ema12 - ema26
    macd_signal = macd.ewm(span=9, adjust=False).mean()
    return macd, macd_signal


def calc_bollinger(close: pd.Series, period: int = 20, num_std: float = 2.0) -> tuple[pd.Series, pd.Series]:
    sma = close.rolling(period).mean()
    std = close.rolling(period).std()
    return sma + num_std * std, sma - num_std * std


def make_signal(row) -> tuple[str | None, float]:
    """ルールベースでシグナルとスコアを決定"""
    if (
        pd.isna(row["sma25"])
        or pd.isna(row["sma75"])
        or pd.isna(row["rsi14"])
        or pd.isna(row["macd"])
        or pd.isna(row["macd_signal"])
        or pd.isna(row["bb_upper"])
        or pd.isna(row["bb_lower"])
    ):
        return None, 0.0

    score = 0.0
    signal = "hold"
    macd_diff = row["macd"] - row["macd_signal"]

    # ゴールデンクロス気味（短期線が長期線の上）+ RSIが過熱でない -> 買い候補
    if row["sma25"] > row["sma75"] and row["rsi14"] < 70:
        signal = "buy_candidate"
        score += (row["sma25"] / row["sma75"] - 1) * 100
        score += max(0, 50 - row["rsi14"]) * 0.1

        # MACDがシグナルを上回っている(上昇モメンタム)ほど加点
        if macd_diff > 0:
            score += macd_diff * 2

        # ボリンジャーバンド下限近くは押し目買いとして加点
        bb_width = row["bb_upper"] - row["bb_lower"]
        if bb_width > 0:
            position = (row["Close"] - row["bb_lower"]) / bb_width
            if position < 0.3:
                score += (0.3 - position) * 10

    # デッドクロス気味、RSI過熱、MACDデッドクロス、バンド上限超え -> 売り候補
    if (
        row["sma25"] < row["sma75"]
        or row["rsi14"] > 70
        or macd_diff < 0
        or row["Close"] > row["bb_upper"]
    ):
        signal = "sell_candidate"

    return signal, round(score, 4)


def main():
    url = os.environ["SUPABASE_URL"]
    key = os.environ["SUPABASE_SERVICE_KEY"]
    sb = create_client(url, key)

    # 銘柄マスタをupsert
    sb.table("stocks").upsert(
        [{"ticker": t, "name": n} for t, n in TICKERS.items()]
    ).execute()

    today = datetime.date.today()

    for ticker in TICKERS:
        hist = yf.Ticker(ticker).history(period="6mo")
        if hist.empty:
            print(f"skip {ticker}: no data")
            continue

        hist = hist.reset_index()
        hist["date"] = hist["Date"].dt.date

        hist["sma25"] = hist["Close"].rolling(25).mean()
        hist["sma75"] = hist["Close"].rolling(75).mean()
        hist["rsi14"] = calc_rsi(hist["Close"], 14)
        hist["macd"], hist["macd_signal"] = calc_macd(hist["Close"])
        hist["bb_upper"], hist["bb_lower"] = calc_bollinger(hist["Close"])

        # 価格履歴を保存
        price_rows = [
            {
                "ticker": ticker,
                "date": r["date"].isoformat(),
                "open": float(r["Open"]),
                "high": float(r["High"]),
                "low": float(r["Low"]),
                "close": float(r["Close"]),
                "volume": int(r["Volume"]),
            }
            for _, r in hist.tail(30).iterrows()
        ]
        sb.table("prices").upsert(price_rows).execute()

        # 最新日のシグナルを保存
        latest = hist.iloc[-1]
        signal, score = make_signal(latest)
        sb.table("signals").upsert(
            {
                "ticker": ticker,
                "date": today.isoformat(),
                "close": float(latest["Close"]),
                "sma25": None if pd.isna(latest["sma25"]) else float(latest["sma25"]),
                "sma75": None if pd.isna(latest["sma75"]) else float(latest["sma75"]),
                "rsi14": None if pd.isna(latest["rsi14"]) else float(latest["rsi14"]),
                "macd": None if pd.isna(latest["macd"]) else float(latest["macd"]),
                "macd_signal": None if pd.isna(latest["macd_signal"]) else float(latest["macd_signal"]),
                "bb_upper": None if pd.isna(latest["bb_upper"]) else float(latest["bb_upper"]),
                "bb_lower": None if pd.isna(latest["bb_lower"]) else float(latest["bb_lower"]),
                "signal": signal,
                "score": score,
            }
        ).execute()

        print(f"{ticker}: signal={signal} score={score}")


if __name__ == "__main__":
    main()

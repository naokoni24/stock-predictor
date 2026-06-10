"""
機械学習モデルの学習スクリプト。

主力銘柄(TICKERS)について過去2年分の株価を取得し、
テクニカル指標を特徴量として、
「N日後に株価が一定%以上上昇したか」をラベルとした
2値分類モデル(RandomForest)を学習する。

学習済みモデルは scripts/model.pkl に保存し、
fetch_and_signal.py から読み込んで日次推論に利用する。

実行: scripts/venv/bin/python scripts/train_model.py
"""

import joblib
import pandas as pd
import yfinance as yf

from fetch_and_signal import TICKERS, calc_rsi, calc_macd, calc_bollinger, get_screener_tickers
from sklearn.ensemble import RandomForestClassifier, GradientBoostingClassifier, VotingClassifier
from sklearn.model_selection import train_test_split
from sklearn.metrics import accuracy_score, classification_report

# N日後に株価がこの%以上上昇していたら「上昇」ラベル(1)とする
HORIZON_DAYS = 5
TARGET_RETURN = 0.02

FEATURE_COLUMNS = [
    "sma25_ratio",
    "sma75_ratio",
    "rsi14",
    "macd",
    "macd_signal",
    "macd_diff",
    "bb_position",
    "return_1d",
    "return_5d",
    "return_20d",
    "volume_ratio",
]

import os

MODEL_PATH = os.path.join(os.path.dirname(__file__), "model.pkl")


def build_features(hist: pd.DataFrame) -> pd.DataFrame:
    """株価履歴(Close, sma25, sma75, rsi14, macd, macd_signal, bb_upper, bb_lower)から特徴量を作成"""
    df = hist.copy()
    df["sma25_ratio"] = df["Close"] / df["sma25"] - 1
    df["sma75_ratio"] = df["Close"] / df["sma75"] - 1
    df["macd_diff"] = df["macd"] - df["macd_signal"]
    bb_width = df["bb_upper"] - df["bb_lower"]
    df["bb_position"] = (df["Close"] - df["bb_lower"]) / bb_width

    # 騰落率(過去N日間のリターン)
    df["return_1d"] = df["Close"] / df["Close"].shift(1) - 1
    df["return_5d"] = df["Close"] / df["Close"].shift(5) - 1
    df["return_20d"] = df["Close"] / df["Close"].shift(20) - 1

    # 出来高比率(直近出来高 / 過去20日平均出来高)
    df["volume_ratio"] = df["Volume"] / df["Volume"].rolling(20).mean()

    return df


def build_dataset() -> pd.DataFrame:
    rows = []

    # 主力銘柄 + スクリーニング銘柄(値上がり/値下がり上位)を学習データに含めて母数を増やす
    all_tickers = dict(TICKERS)
    screener_tickers = get_screener_tickers()
    print(f"screener found {len(screener_tickers)} tickers")
    for t, n in screener_tickers.items():
        all_tickers.setdefault(t, n)

    for ticker in all_tickers:
        hist = yf.Ticker(ticker).history(period="2y")
        if hist.empty:
            continue
        hist = hist.reset_index()
        hist["sma25"] = hist["Close"].rolling(25).mean()
        hist["sma75"] = hist["Close"].rolling(75).mean()
        hist["rsi14"] = calc_rsi(hist["Close"], 14)
        hist["macd"], hist["macd_signal"] = calc_macd(hist["Close"])
        hist["bb_upper"], hist["bb_lower"] = calc_bollinger(hist["Close"])

        df = build_features(hist)

        # N日後の終値の変化率からラベルを作成
        future_close = df["Close"].shift(-HORIZON_DAYS)
        future_return = future_close / df["Close"] - 1
        df["label"] = (future_return >= TARGET_RETURN).astype(int)

        # 特徴量・ラベルが揃っている行のみ使用(末尾HORIZON_DAYS行は未来データがないため除外)
        df = df.dropna(subset=FEATURE_COLUMNS + ["label"])
        df = df.iloc[:-HORIZON_DAYS] if len(df) > HORIZON_DAYS else df.iloc[0:0]

        rows.append(df[FEATURE_COLUMNS + ["label"]])
        print(f"{ticker}: {len(df)} rows")

    return pd.concat(rows, ignore_index=True)


def main():
    print("学習データを作成中...")
    dataset = build_dataset()
    print(f"\n合計 {len(dataset)} 行 (上昇ラベル比率: {dataset['label'].mean():.3f})")

    X = dataset[FEATURE_COLUMNS]
    y = dataset["label"]

    X_train, X_test, y_train, y_test = train_test_split(
        X, y, test_size=0.2, random_state=42, shuffle=True
    )

    # RandomForestとGradientBoostingの予測確率を平均するアンサンブル(過学習を抑え、予測を安定化)
    rf = RandomForestClassifier(
        n_estimators=100,
        max_depth=5,
        min_samples_leaf=20,
        random_state=42,
        n_jobs=-1,
    )
    gb = GradientBoostingClassifier(
        n_estimators=100,
        max_depth=3,
        min_samples_leaf=20,
        random_state=42,
    )
    model = VotingClassifier(
        estimators=[("rf", rf), ("gb", gb)], voting="soft"
    )
    model.fit(X_train, y_train)

    pred = model.predict(X_test)
    print(f"\nテストデータ正解率: {accuracy_score(y_test, pred):.3f}")
    print(classification_report(y_test, pred))

    print("特徴量重要度 (RandomForest):")
    rf_fitted = model.named_estimators_["rf"]
    for col, importance in sorted(
        zip(FEATURE_COLUMNS, rf_fitted.feature_importances_), key=lambda x: -x[1]
    ):
        print(f"  {col}: {importance:.3f}")

    joblib.dump({"model": model, "features": FEATURE_COLUMNS}, MODEL_PATH)
    print(f"\nモデルを {MODEL_PATH} に保存しました")


if __name__ == "__main__":
    main()

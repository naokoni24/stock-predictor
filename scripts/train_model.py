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

from fetch_and_signal import TICKERS, calc_rsi, calc_macd, calc_bollinger, get_screener_tickers, get_jp_sector_map
from sklearn.ensemble import RandomForestClassifier, GradientBoostingClassifier, VotingClassifier
from sklearn.metrics import accuracy_score, classification_report

# N日後に株価がこの%以上上昇していたら「上昇」ラベル(1)とする
HORIZON_DAYS = 5
TARGET_RETURN = 0.02

MARKET_INDICES = {
    "nikkei": "^N225",
    "topix": "^TOPX",
    "usdjpy": "JPY=X",
    "nasdaq": "^IXIC",
    "sox": "^SOX",
}

MARKET_METRICS = [
    "return_1d",
    "return_5d",
    "return_20d",
    "sma25_ratio",
    "sma75_ratio",
    "rsi14",
    "volatility_20d",
]

MARKET_FEATURE_COLUMNS = [
    f"{prefix}_{metric}"
    for prefix in MARKET_INDICES
    for metric in MARKET_METRICS
]

SECTOR_FEATURE_COLUMNS = [
    "sector_return_5d",
    "sector_return_20d",
    "sector_relative_strength_5d",
    "sector_relative_strength_20d",
]

BASE_FEATURE_COLUMNS = [
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
    "volume_price_momentum_5d",
    "volume_price_momentum_20d",
    "volume_up_pressure_5d",
    "volume_down_pressure_5d",
    "relative_strength_5d",
    "price_position_52w",
]

FEATURE_COLUMNS = BASE_FEATURE_COLUMNS + MARKET_FEATURE_COLUMNS + SECTOR_FEATURE_COLUMNS

import os

MODEL_PATH = os.path.join(os.path.dirname(__file__), "model.pkl")


def market_default_value(column: str) -> float:
    """市場環境データが欠けた時に使う中立値"""
    if column.endswith("_rsi14"):
        return 50.0
    return 0.0


def sector_default_value() -> float:
    """業種別データが欠けた時に使う中立値"""
    return 0.0


def build_market_features(symbol: str, prefix: str) -> pd.DataFrame:
    """市場指数・為替データを同じ形式の特徴量へ変換"""
    hist = yf.Ticker(symbol).history(period="2y")
    if hist.empty:
        print(f"market data empty: {symbol}")
        return pd.DataFrame(columns=["date"] + [f"{prefix}_{m}" for m in MARKET_METRICS])

    hist = hist.reset_index()
    hist["date"] = pd.to_datetime(hist["Date"]).dt.date
    hist[f"{prefix}_return_1d"] = hist["Close"] / hist["Close"].shift(1) - 1
    hist[f"{prefix}_return_5d"] = hist["Close"] / hist["Close"].shift(5) - 1
    hist[f"{prefix}_return_20d"] = hist["Close"] / hist["Close"].shift(20) - 1
    hist[f"{prefix}_sma25"] = hist["Close"].rolling(25).mean()
    hist[f"{prefix}_sma75"] = hist["Close"].rolling(75).mean()
    hist[f"{prefix}_sma25_ratio"] = hist["Close"] / hist[f"{prefix}_sma25"] - 1
    hist[f"{prefix}_sma75_ratio"] = hist["Close"] / hist[f"{prefix}_sma75"] - 1
    hist[f"{prefix}_rsi14"] = calc_rsi(hist["Close"], 14)
    hist[f"{prefix}_volatility_20d"] = hist[f"{prefix}_return_1d"].rolling(20).std()

    return hist[["date"] + [f"{prefix}_{m}" for m in MARKET_METRICS]]


def get_nikkei_returns() -> pd.DataFrame:
    """市場環境特徴量を取得。既存呼び出しとの互換性のため関数名は維持する"""
    market = None
    for prefix, symbol in MARKET_INDICES.items():
        features = build_market_features(symbol, prefix)
        if market is None:
            market = features
        else:
            market = market.merge(features, on="date", how="outer")

    if market is None or market.empty:
        return pd.DataFrame(columns=["date"] + MARKET_FEATURE_COLUMNS)

    market = market.sort_values("date").reset_index(drop=True)
    market[MARKET_FEATURE_COLUMNS] = market[MARKET_FEATURE_COLUMNS].ffill()
    for column in MARKET_FEATURE_COLUMNS:
        market[column] = market[column].fillna(market_default_value(column))

    return market[["date"] + MARKET_FEATURE_COLUMNS]


def build_features(hist: pd.DataFrame, nikkei: pd.DataFrame | None = None) -> pd.DataFrame:
    """株価履歴(Close, sma25, sma75, rsi14, macd, macd_signal, bb_upper, bb_lower)から特徴量を作成"""
    df = hist.copy()
    df["date"] = pd.to_datetime(df["Date"]).dt.date
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
    df["volume_ratio_5d"] = df["Volume"] / df["Volume"].rolling(5).mean()

    # 出来高を伴う上昇/下落の勢い。値動きだけでなく、市場参加者の厚みも見る。
    df["volume_price_momentum_5d"] = df["return_5d"] * df["volume_ratio_5d"]
    df["volume_price_momentum_20d"] = df["return_20d"] * df["volume_ratio"]
    df["volume_up_pressure_5d"] = df["volume_price_momentum_5d"].clip(lower=0)
    df["volume_down_pressure_5d"] = (-df["volume_price_momentum_5d"]).clip(lower=0)

    # 52週(252営業日)高値・安値の中での現在値の位置(0=安値, 1=高値)
    low_52w = df["Close"].rolling(252, min_periods=60).min()
    high_52w = df["Close"].rolling(252, min_periods=60).max()
    df["price_position_52w"] = (df["Close"] - low_52w) / (high_52w - low_52w)

    # 市場環境データを結合し、日経平均に対する相対強弱も算出する
    if nikkei is not None:
        df = df.merge(nikkei, on="date", how="left")
        # 市場データは休場日のずれで最新日が欠けることがあるため、直前値で埋める
        for column in MARKET_FEATURE_COLUMNS:
            if column not in df.columns:
                df[column] = market_default_value(column)
        df[MARKET_FEATURE_COLUMNS] = df[MARKET_FEATURE_COLUMNS].ffill()
        for column in MARKET_FEATURE_COLUMNS:
            df[column] = df[column].fillna(market_default_value(column))
        df["relative_strength_5d"] = df["return_5d"] - df["nikkei_return_5d"]
    else:
        df["relative_strength_5d"] = df["return_5d"]
        for column in MARKET_FEATURE_COLUMNS:
            df[column] = market_default_value(column)

    for column in SECTOR_FEATURE_COLUMNS:
        if column not in df.columns:
            df[column] = sector_default_value()

    return df


def add_sector_relative_features(
    feature_frames: dict[str, pd.DataFrame],
    sectors: dict[str, str],
) -> dict[str, pd.DataFrame]:
    """同業種平均リターンと、個別銘柄の業種平均との差分を追加する"""
    rows = []
    for ticker, df in feature_frames.items():
        if df.empty or "date" not in df.columns:
            continue
        sector = sectors.get(ticker, "不明")
        rows.append(
            df[["date", "return_5d", "return_20d"]]
            .assign(ticker=ticker, sector=sector)
        )

    if not rows:
        return feature_frames

    all_returns = pd.concat(rows, ignore_index=True)
    sector_returns = (
        all_returns
        .groupby(["date", "sector"], as_index=False)[["return_5d", "return_20d"]]
        .mean()
        .rename(
            columns={
                "return_5d": "sector_return_5d",
                "return_20d": "sector_return_20d",
            }
        )
    )

    result = {}
    for ticker, df in feature_frames.items():
        sector = sectors.get(ticker, "不明")
        enriched = df.copy()
        sector_like_columns = [
            column for column in enriched.columns
            if column in SECTOR_FEATURE_COLUMNS
            or column.startswith("sector_return_")
            or column.startswith("sector_relative_strength_")
        ]
        enriched = enriched.drop(columns=sector_like_columns, errors="ignore")
        enriched["sector"] = sector
        enriched = enriched.merge(sector_returns, on=["date", "sector"], how="left")
        enriched["sector_return_5d"] = enriched["sector_return_5d"].fillna(sector_default_value())
        enriched["sector_return_20d"] = enriched["sector_return_20d"].fillna(sector_default_value())
        enriched["sector_relative_strength_5d"] = enriched["return_5d"] - enriched["sector_return_5d"]
        enriched["sector_relative_strength_20d"] = enriched["return_20d"] - enriched["sector_return_20d"]
        for column in SECTOR_FEATURE_COLUMNS:
            enriched[column] = enriched[column].fillna(sector_default_value())
        result[ticker] = enriched.drop(columns=["sector"])

    return result


def build_dataset() -> pd.DataFrame:
    rows = []

    # 主力銘柄 + スクリーニング銘柄(値上がり/値下がり上位)を学習データに含めて母数を増やす
    all_tickers = dict(TICKERS)
    screener_tickers = get_screener_tickers()
    print(f"screener found {len(screener_tickers)} tickers")
    for t, n in screener_tickers.items():
        all_tickers.setdefault(t, n)

    nikkei = get_nikkei_returns()
    sectors = get_jp_sector_map()

    feature_frames = {}
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

        df = build_features(hist, nikkei)
        feature_frames[ticker] = df

    feature_frames = add_sector_relative_features(feature_frames, sectors)

    for ticker, df in feature_frames.items():

        # N日後の終値の変化率からラベルを作成
        future_close = df["Close"].shift(-HORIZON_DAYS)
        future_return = future_close / df["Close"] - 1
        df["label"] = (future_return >= TARGET_RETURN).astype(int)

        # 特徴量・ラベルが揃っている行のみ使用(末尾HORIZON_DAYS行は未来データがないため除外)
        df = df.dropna(subset=FEATURE_COLUMNS + ["label"])
        df = df.iloc[:-HORIZON_DAYS] if len(df) > HORIZON_DAYS else df.iloc[0:0]

        df = df[["date"] + FEATURE_COLUMNS + ["label"]].copy()
        df["sector"] = sectors.get(ticker, "不明")
        rows.append(df)
        print(f"{ticker}: {len(df)} rows")

    dataset = pd.concat(rows, ignore_index=True)
    dataset = pd.get_dummies(dataset, columns=["sector"], prefix="sector")
    return dataset


def main():
    print("学習データを作成中...")
    dataset = build_dataset()
    print(f"\n合計 {len(dataset)} 行 (上昇ラベル比率: {dataset['label'].mean():.3f})")

    # 業種one-hot列のみを抽出する。sector_return_* などの数値特徴量は除外する。
    sector_columns = [
        c for c in dataset.columns
        if c.startswith("sector_") and c not in FEATURE_COLUMNS
    ]
    feature_columns = FEATURE_COLUMNS + sector_columns

    # walk-forward検証: 日付でソートし、直近20%をテストデータにする
    # (ランダム分割だと未来のデータが学習に混ざり精度が甘く出るため)
    dataset = dataset.sort_values("date").reset_index(drop=True)
    split_idx = int(len(dataset) * 0.8)
    train_df = dataset.iloc[:split_idx]
    test_df = dataset.iloc[split_idx:]
    print(f"学習データ: {train_df['date'].min()} 〜 {train_df['date'].max()} ({len(train_df)}行)")
    print(f"テストデータ: {test_df['date'].min()} 〜 {test_df['date'].max()} ({len(test_df)}行)")

    X_train, y_train = train_df[feature_columns], train_df["label"]
    X_test, y_test = test_df[feature_columns], test_df["label"]

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
        zip(feature_columns, rf_fitted.feature_importances_), key=lambda x: -x[1]
    ):
        print(f"  {col}: {importance:.3f}")

    # predict_probaの出力分布が偏っている(ラベル陽性率が低い)ため、
    # 全データでの予測確率の分位点を保存し、推論時に0〜1へ較正し直す。
    # これにより「50%」が平均的な銘柄、両端が相対的に強気/弱気な銘柄を表すようになる。
    import numpy as np

    all_proba = model.predict_proba(dataset[feature_columns])[:, 1]
    calibration_percentiles = np.linspace(0, 100, 21)
    calibration_values = np.percentile(all_proba, calibration_percentiles).tolist()
    print(f"\nスコア較正テーブル(0/25/50/75/100%点): "
          f"{calibration_values[0]:.3f} / {calibration_values[5]:.3f} / "
          f"{calibration_values[10]:.3f} / {calibration_values[15]:.3f} / {calibration_values[-1]:.3f}")

    joblib.dump(
        {
            "model": model,
            "features": feature_columns,
            "sector_columns": sector_columns,
            "feature_version": "sector_relative_strength_v1",
            "score_calibration": calibration_values,
        },
        MODEL_PATH,
    )
    print(f"\nモデルを {MODEL_PATH} に保存しました")


if __name__ == "__main__":
    main()

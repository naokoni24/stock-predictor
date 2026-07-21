"""
ルールベースシグナル と MLモデル予測 のバックテスト成績比較。

ルールベース: fetch_and_signal.py の make_signal (buy_candidate/sell_candidate)
MLモデル: scripts/model.pkl の予測確率が閾値以上なら買い、
          一定日数保有 (HOLD_DAYS) して売却

実行: scripts/venv/bin/python scripts/backtest_ml.py
"""

import joblib
import numpy as np
import os
import pandas as pd
import yfinance as yf

from fetch_and_signal import TICKERS, calc_rsi, calc_macd, calc_bollinger, get_jp_sector_map
from sklearn.utils.class_weight import compute_sample_weight
from train_model import (
    add_breadth_features,
    add_excess_return_targets,
    add_sector_relative_features,
    adjusted_ml_buy_threshold,
    build_features,
    build_voting_model,
    calibrate_scores,
    evaluate_threshold,
    get_nikkei_returns,
    is_ml_buy_blocked,
    optimize_ml_buy_threshold,
    optimize_sector_thresholds,
    sector_base_threshold,
    FEATURE_COLUMNS,
    HORIZON_DAYS,
    LABEL_LOOKAHEAD_DAYS,
    MODEL_PATH,
    RECENCY_HALFLIFE_DAYS,
    TRAIN_HISTORY_PERIOD,
    THRESHOLD_GRID,
)

DEFAULT_ML_BUY_THRESHOLD = 0.55
HOLD_DAYS = 5

# train_model.pyの学習/検証/テスト分割(70%/15%/15%)に合わせ、
# 直近15%(テスト期間相当)のみをout-of-sample評価の対象とする。
# こうしないと学習に使った期間でバックテストしてしまい、成績が楽観的に出てしまう。
TEST_SPLIT_RATIO = 0.85

# 月次walk-forward評価では、評価月の直前3か月をしきい値最適化に使い、
# それより前だけをモデル学習に使う。未来データの混入を避けるため。
WALK_FORWARD_VALIDATION_MONTHS = 3
WALK_FORWARD_MIN_TRAIN_ROWS = 1000
WALK_FORWARD_MIN_VAL_ROWS = 200
WALK_FORWARD_MAX_FOLDS = int(os.getenv("WALK_FORWARD_MAX_FOLDS", "6"))


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
        hist = yf.Ticker(ticker).history(period=TRAIN_HISTORY_PERIOD)
        if hist.empty:
            continue
        hist = hist.reset_index()
        hist["sma25"] = hist["Close"].rolling(25).mean()
        hist["sma75"] = hist["Close"].rolling(75).mean()
        hist["rsi14"] = calc_rsi(hist["Close"], 14)
        hist["macd"], hist["macd_signal"] = calc_macd(hist["Close"])
        hist["bb_upper"], hist["bb_lower"] = calc_bollinger(hist["Close"])
        # ATR(14): ATR連動ストップの算出に使う
        prev_close = hist["Close"].shift(1)
        true_range = pd.concat(
            [
                hist["High"] - hist["Low"],
                (hist["High"] - prev_close).abs(),
                (hist["Low"] - prev_close).abs(),
            ],
            axis=1,
        ).max(axis=1)
        hist["atr14"] = true_range.rolling(14).mean()
        histories[ticker] = hist
    return histories


def simulate_trade_exit(
    hist: pd.DataFrame,
    entry_idx: int,
    hold_days: int,
    stop_pct: float | None = None,
    tp_pct: float | None = None,
    atr_mult: float | None = None,
) -> tuple[float, int]:
    """エントリー翌営業日始値で買い、保有期間中に損切り/利確/時間で決済したリターン(%)と決済indexを返す。

    - 損切り: atr_mult指定時はATR連動(買値 - atr_mult*ATR)、なければstop_pct(固定%)
    - 利確: tp_pct(固定%)
    - 時間決済: hold_days経過で翌営業日始値
    - 同日に損切り/利確が両方ヒットした場合は保守的に損切り優先(日足では順序不明のため)
    """
    buy_price = hist.iloc[entry_idx + 1]["Open"]

    stop_price = None
    if atr_mult is not None:
        atr = hist.iloc[entry_idx].get("atr14", float("nan"))
        if pd.notna(atr):
            stop_price = buy_price - atr_mult * atr
    elif stop_pct is not None:
        stop_price = buy_price * (1 - stop_pct)
    tp_price = buy_price * (1 + tp_pct) if tp_pct is not None else None

    time_exit_idx = entry_idx + 1 + hold_days
    for j in range(entry_idx + 1, time_exit_idx):
        day = hist.iloc[j]
        # 寄り付きで損切り水準を下回った場合、損切り価格で約定できたとは仮定しない。
        if stop_price is not None and day["Open"] <= stop_price:
            return (day["Open"] - buy_price) / buy_price * 100, j
        if stop_price is not None and day["Low"] <= stop_price:
            return (stop_price - buy_price) / buy_price * 100, j
        if tp_price is not None and day["High"] >= tp_price:
            return (tp_price - buy_price) / buy_price * 100, j

    exit_price = hist.iloc[time_exit_idx]["Open"]
    return (exit_price - buy_price) / buy_price * 100, time_exit_idx


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
    sector_thresholds: dict[str, float] | None = None,
    start_idx: int = 0,
    hold_days: int = HOLD_DAYS,
    stop_pct: float | None = None,
    tp_pct: float | None = None,
    atr_mult: float | None = None,
) -> list[float]:
    """MLモデル: 上昇確率がthreshold以上で翌日始値で購入 -> 損切り/利確/時間決済で売却

    require_rule_buy=Trueの場合、ルールベースもbuy_candidateの日のみ購入対象とする
    (両シグナル一致フィルタ)
    stop_pct/tp_pct/atr_mult を指定すると保有期間中に損切り・利確を行う(simulate_trade_exit参照)。
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
    base_threshold = sector_base_threshold(threshold, sector_thresholds, sector)
    while i < n - 1 - hold_days:
        score = df.iloc[i]["ml_score"]
        effective_threshold = adjusted_ml_buy_threshold(base_threshold, df.iloc[i])
        ml_buy = pd.notna(score) and score >= effective_threshold and not is_ml_buy_blocked(df.iloc[i])
        if ml_buy and require_rule_buy:
            ml_buy = make_signal_param(hist.iloc[i]) == "buy_candidate"

        if ml_buy:
            ret, exit_idx = simulate_trade_exit(hist, i, hold_days, stop_pct, tp_pct, atr_mult)
            returns.append(ret)
            i = exit_idx + 1
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


def build_backtest_dataset(
    histories: dict[str, pd.DataFrame],
    feature_frames: dict[str, pd.DataFrame],
    sectors: dict[str, str],
) -> tuple[pd.DataFrame, list[str]]:
    """取得済み履歴からwalk-forward評価用の学習テーブルを作る"""
    rows = []
    labeled_frames = add_excess_return_targets(feature_frames, sectors)
    for ticker, df in labeled_frames.items():
        if ticker not in histories or df.empty:
            continue

        source = df.copy()
        source["rule_buy"] = source.apply(lambda row: make_signal_param(row) == "buy_candidate", axis=1)
        source = source.dropna(subset=FEATURE_COLUMNS + ["future_return", "future_excess_return", "label"])
        if source.empty:
            continue
        source["label"] = source["label"].astype(int)

        source = source[["date"] + FEATURE_COLUMNS + ["future_return", "benchmark_return", "future_excess_return", "label", "rule_buy"]].copy()
        source["ticker"] = ticker
        source["sector"] = sectors.get(ticker, "不明")
        rows.append(source)

    if not rows:
        return pd.DataFrame(), []

    dataset = pd.concat(rows, ignore_index=True)
    dataset["date"] = pd.to_datetime(dataset["date"])
    dataset["sector_label"] = dataset["sector"]
    dataset = pd.get_dummies(dataset, columns=["sector"], prefix="sector")
    sector_columns = [
        c for c in dataset.columns
        if c.startswith("sector_") and c not in FEATURE_COLUMNS and c != "sector_label"
    ]
    return dataset.sort_values("date").reset_index(drop=True), sector_columns


def make_walk_forward_model():
    """train_model.pyと同じ構成(シード平均アンサンブル)の一時モデルを作る"""
    return build_voting_model(
        rf_params={"n_estimators": 100, "max_depth": 5, "min_samples_leaf": 20},
        gb_params={"n_estimators": 100, "max_depth": 3, "min_samples_leaf": 20},
        lgbm_params={"n_estimators": 200, "max_depth": 5, "min_child_samples": 20},
    )


def selected_walk_forward_returns(
    scores: np.ndarray,
    fold_df: pd.DataFrame,
    feature_columns: list[str],
    threshold: float,
    sector_thresholds: dict[str, float] | None = None,
    require_rule_buy: bool = False,
) -> list[float]:
    """評価月で買い判定になった行の翌営業日始値約定ベース実現リターン(%)を返す"""
    returns = []
    for score, (_, row) in zip(scores, fold_df.iterrows()):
        sector = str(row.get("sector_label", "不明"))
        feature_row = row[feature_columns]
        base_threshold = sector_base_threshold(threshold, sector_thresholds, sector)
        effective_threshold = adjusted_ml_buy_threshold(base_threshold, feature_row)
        if pd.isna(score) or score < effective_threshold or is_ml_buy_blocked(feature_row):
            continue
        if require_rule_buy and not bool(row.get("rule_buy", False)):
            continue
        returns.append(float(row["future_return"]) * 100)
    return returns


def run_walk_forward_evaluation(dataset: pd.DataFrame, sector_columns: list[str]) -> None:
    """月次walk-forwardで、評価月より未来のデータを使わずに成績を見る"""
    if dataset.empty:
        print("\n月次walk-forward評価: データがないためスキップ")
        return

    feature_columns = FEATURE_COLUMNS + sector_columns
    for column in feature_columns:
        if column not in dataset.columns:
            dataset[column] = 0

    periods = sorted(dataset["date"].dt.to_period("M").unique())
    if WALK_FORWARD_MAX_FOLDS > 0:
        periods = periods[-WALK_FORWARD_MAX_FOLDS:]
    fold_results = []
    ml_returns = []
    consensus_returns = []

    if WALK_FORWARD_MAX_FOLDS > 0:
        print(f"\n月次walk-forward評価 (直近{WALK_FORWARD_MAX_FOLDS}評価月):")
    else:
        print("\n月次walk-forward評価 (全評価月):")
    print(
        f"{'評価月':>8} {'train':>7} {'val':>6} {'test':>6} "
        f"{'thr':>5} {'ML件数':>7} {'ML勝率':>7} {'ML平均':>8} {'一致件数':>8} {'一致平均':>9}"
    )

    embargo = pd.offsets.BDay(LABEL_LOOKAHEAD_DAYS)
    for period in periods:
        test_start = period.to_timestamp()
        test_end = (period + 1).to_timestamp()
        val_start = test_start - pd.DateOffset(months=WALK_FORWARD_VALIDATION_MONTHS)

        # エンバーゴ: 5営業日先ラベルが境界をまたいで漏れるのを防ぐため、
        # train/val の各末尾を翌日約定+時間決済に必要な営業日分除外する(train_model.pyと同じ思想)。
        train_df = dataset[dataset["date"] < (val_start - embargo)]
        val_df = dataset[(dataset["date"] >= val_start) & (dataset["date"] < (test_start - embargo))]
        test_df = dataset[(dataset["date"] >= test_start) & (dataset["date"] < test_end)]
        if (
            len(train_df) < WALK_FORWARD_MIN_TRAIN_ROWS
            or len(val_df) < WALK_FORWARD_MIN_VAL_ROWS
            or test_df.empty
            or train_df["label"].nunique() < 2
        ):
            continue

        model = make_walk_forward_model()
        # 本番(train_model.py)と同じく直近データを重視するサンプル重みを掛ける
        train_age_days = (train_df["date"].max() - train_df["date"]).dt.days.to_numpy()
        recency_weight = 0.5 ** (train_age_days / RECENCY_HALFLIFE_DAYS)
        sample_weight = (
            compute_sample_weight(class_weight="balanced", y=train_df["label"]) * recency_weight
        )
        model.fit(train_df[feature_columns], train_df["label"], sample_weight=sample_weight)

        train_proba = model.predict_proba(train_df[feature_columns])[:, 1]
        calibration_values = np.percentile(train_proba, np.linspace(0, 100, 21)).tolist()

        val_raw_proba = model.predict_proba(val_df[feature_columns])[:, 1]
        val_scores = calibrate_scores(val_raw_proba, calibration_values)
        threshold, _ = optimize_ml_buy_threshold(
            val_scores,
            val_df["future_excess_return"].to_numpy(),
            val_df[feature_columns],
            dates=val_df["date"],
        )
        sector_thresholds, _ = optimize_sector_thresholds(
            threshold,
            val_scores,
            val_df["future_excess_return"].to_numpy(),
            val_df[feature_columns],
            val_df["sector_label"],
            dates=val_df["date"],
        )

        test_raw_proba = model.predict_proba(test_df[feature_columns])[:, 1]
        test_scores = calibrate_scores(test_raw_proba, calibration_values)
        test_eval = evaluate_threshold(
            test_scores,
            test_df["future_excess_return"].to_numpy(),
            threshold,
            test_df[feature_columns],
            test_df["sector_label"],
            sector_thresholds,
        )

        fold_ml_returns = selected_walk_forward_returns(
            test_scores,
            test_df,
            feature_columns,
            threshold,
            sector_thresholds,
        )
        fold_consensus_returns = selected_walk_forward_returns(
            test_scores,
            test_df,
            feature_columns,
            threshold,
            sector_thresholds,
            require_rule_buy=True,
        )
        ml_returns.extend(fold_ml_returns)
        consensus_returns.extend(fold_consensus_returns)
        fold_results.append(test_eval)

        ml_avg = sum(fold_ml_returns) / len(fold_ml_returns) if fold_ml_returns else 0.0
        ml_win = (
            sum(1 for r in fold_ml_returns if r > 0) / len(fold_ml_returns) * 100
            if fold_ml_returns
            else 0.0
        )
        consensus_avg = (
            sum(fold_consensus_returns) / len(fold_consensus_returns)
            if fold_consensus_returns
            else 0.0
        )
        print(
            f"{period} {len(train_df):>7} {len(val_df):>6} {len(test_df):>6} "
            f"{threshold:>5.2f} {len(fold_ml_returns):>7} {ml_win:>6.1f}% {ml_avg:>7.2f}% "
            f"{len(fold_consensus_returns):>8} {consensus_avg:>8.2f}%"
        )

    if not fold_results:
        print("評価可能な月がありませんでした。取得期間を延ばすか、最小行数を調整してください。")
        return

    print("\n月次walk-forward集計 (評価月より未来のデータは学習・しきい値最適化に未使用):")
    print(f"MLモデル単独: {evaluate(ml_returns)}")
    print(f"両シグナル一致: {evaluate(consensus_returns)}")


def evaluate_with_risk(returns: list[float]) -> dict:
    """評価指標に標準偏差・最悪トレード・最大ドローダウン(累積リターン%ベース)を追加する"""
    returns = [r for r in returns if pd.notna(r)]
    base = evaluate(returns)
    if not returns:
        base.update({"std": 0.0, "worst": 0.0, "max_drawdown": 0.0})
        return base
    arr = np.array(returns)
    equity = np.cumsum(arr)
    running_max = np.maximum.accumulate(equity)
    base.update(
        {
            "std": float(arr.std()),
            "worst": float(arr.min()),
            "max_drawdown": float((equity - running_max).min()),
        }
    )
    return base


def run_ml_risk_config(
    histories, model, features, nikkei, jp_sectors, feature_frames,
    ml_buy_threshold, sector_columns, score_calibration, sector_thresholds,
    **exit_kwargs,
) -> dict:
    """指定した損切り/利確設定でテスト期間のMLトレードを集計する"""
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
                threshold=ml_buy_threshold,
                sector_columns=sector_columns,
                sector=sector,
                feature_df=feature_frames.get(ticker),
                score_calibration=score_calibration,
                sector_thresholds=sector_thresholds,
                start_idx=start_idx,
                **exit_kwargs,
            )
        )
    return evaluate_with_risk(returns)


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
    sector_thresholds = bundle.get("sector_ml_buy_thresholds", {})
    jp_sectors = get_jp_sector_map()
    feature_frames = {
        ticker: build_features(hist, nikkei)
        for ticker, hist in histories.items()
    }
    feature_frames = add_sector_relative_features(feature_frames, jp_sectors)
    # 学習・日次推論と同じ計算でブレッドス特徴量を付与する
    # (対象がTICKERS約33銘柄のためユニバースは本番より狭いが、比率・百分位なので比較可能)
    feature_frames = add_breadth_features(feature_frames)
    walk_forward_dataset, walk_forward_sector_columns = build_backtest_dataset(
        histories,
        feature_frames,
        jp_sectors,
    )

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
                sector_thresholds=sector_thresholds,
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
                sector_thresholds=sector_thresholds,
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

    print("\nリスク管理(損切り/利確/時間決済)の比較 [テスト期間 / MLモデル単独]:")
    print(
        f"{'設定':<24} {'trades':>7} {'win%':>6} {'avg%':>7} "
        f"{'total%':>9} {'std%':>6} {'worst%':>7} {'maxDD%':>8}"
    )
    risk_configs = [
        ("ベースライン(5日保有)", {}),
        ("利確+2%", {"tp_pct": 0.02}),
        ("損切りATR×2", {"atr_mult": 2.0}),
        ("損切り-8%固定", {"stop_pct": 0.08}),
        ("利確+2% & 損切りATR×2", {"tp_pct": 0.02, "atr_mult": 2.0}),
        ("利確+2% & 損切り-8%", {"tp_pct": 0.02, "stop_pct": 0.08}),
        ("利確+3% & 損切りATR×2.5", {"tp_pct": 0.03, "atr_mult": 2.5}),
    ]
    for label, kw in risk_configs:
        r = run_ml_risk_config(
            histories, model, features, nikkei, jp_sectors, feature_frames,
            ml_buy_threshold, sector_columns, score_calibration, sector_thresholds, **kw,
        )
        print(
            f"{label:<24} {r['trades']:>7} {r['win_rate']:>5.1f}% {r['avg_return']:>6.2f}% "
            f"{r['total_return']:>8.1f}% {r['std']:>5.2f}% {r['worst']:>6.2f}% {r['max_drawdown']:>7.1f}%"
        )

    run_walk_forward_evaluation(walk_forward_dataset, walk_forward_sector_columns)


if __name__ == "__main__":
    main()

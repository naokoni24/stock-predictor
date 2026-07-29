"""
機械学習モデルの学習スクリプト。

主力銘柄(TICKERS)についてTRAIN_HISTORY_PERIOD分(現在2年)の株価を取得し、
テクニカル指標を特徴量として、
「N日後に株価が一定%以上上昇したか」をラベルとした
2値分類モデル(RandomForest)を学習する。

学習済みモデルは scripts/model.pkl に保存し、
fetch_and_signal.py から読み込んで日次推論に利用する。

実行: scripts/venv/bin/python scripts/train_model.py
"""

import bisect

import joblib
import numpy as np
import pandas as pd
import yfinance as yf
import optuna

from fetch_and_signal import TICKERS, calc_rsi, calc_macd, calc_bollinger, calc_adx, get_screener_tickers, get_jp_sector_map
from sklearn.ensemble import RandomForestClassifier, GradientBoostingClassifier, VotingClassifier
from sklearn.metrics import accuracy_score, classification_report
from sklearn.utils.class_weight import compute_sample_weight
from lightgbm import LGBMClassifier

optuna.logging.set_verbosity(optuna.logging.WARNING)

# Optunaの試行回数。月次再学習はGitHub Actions上(2コア)で動くため、実行時間を抑える値にする。
OPTUNA_N_TRIALS = 20

# シグナル日の翌営業日始値で約定し、N営業日保有後の始値で時間決済する。
# ラベルは約定日までを見るため、情報リークを防ぐエンバーゴは N+1 営業日必要になる。
HORIZON_DAYS = 5
LABEL_LOOKAHEAD_DAYS = HORIZON_DAYS + 1
TARGET_RETURN = 0.02

# 市場・同業種を上回る候補を選ぶための超過リターン目標。
# 同日・同業種の他銘柄の平均実現リターンをベンチマークにし、0.5%以上上回った場合を正例とする。
# 業種内の比較対象が少ない日は、同日の学習ユニバース全体（自銘柄を除く）を代替ベンチマークに使う。
EXCESS_RETURN_TARGET = 0.005
MIN_SECTOR_BENCHMARK_MEMBERS = 3
MAX_DAILY_ML_BUY_CANDIDATES = 10

# 推奨損切り幅(現在値からの下落率)。フロント(ホーム/保有株画面)の推奨損切り表示と同じ値。
# ラベル作成時、実運用ルール(利確なし・この幅で損切り・HORIZON_DAYS日で時間決済)に合わせる。
STOP_LOSS_PCT = 0.08

# 学習・walk-forward評価に使う株価履歴の期間。
# 3年に伸ばす検証を2026-07に実施したが、テスト期間(2026-02〜06)の成績が
# 2年版(net+1.36%/取引)から明確に悪化(+0.46%、しきい値安定化後も+0.03%)したため
# 2年へ戻した。直近重み付けだけでは古い地合いの混入を相殺できなかったと判断。
TRAIN_HISTORY_PERIOD = "2y"

# 直近データを重視するサンプル重みの半減期(日)。小さいほど直近を重視する。
# 半減期365日なら、1年前のデータは重み0.5、2年前は0.25、3年前は0.125になる。
RECENCY_HALFLIFE_DAYS = 365

# 1取引あたりの想定コスト(往復の売買手数料+スリッページ、リターン比)。
# しきい値最適化とOptunaの目的関数はコスト控除後(net)のリターンで評価する。
# 紙の上では僅かにプラスでも、実際は手数料負けする取引を選ばないようにするため。
TRANSACTION_COST = 0.002

# シード平均アンサンブル: 乱数シードを変えたRF/GB/LGBMのセットを複数学習し、
# soft votingで予測確率を平均する。単一シードの当たり外れによる月次成績のブレを抑える。
# Optunaの試行は速度優先で先頭シードのみ、最終モデルとwalk-forward評価は全シードを使う。
ENSEMBLE_SEEDS = [42, 202, 777]

# soft votingを構成する個別推定器の確率の標準偏差。値が大きい候補は、
# モデル間で見解が割れているため、検証期間で選んだ上限を超えた場合は見送る。
# None はフィルターなしで、既存モデルとの後方互換にも使う。
ENSEMBLE_DISAGREEMENT_GRID = [None, 0.04, 0.06, 0.08, 0.10, 0.12]

# 買い判定のしきい値候補。再学習時にテストデータのバックテスト成績で最適値を選ぶ。
THRESHOLD_GRID = [round(x, 3) for x in [0.40, 0.45, 0.50, 0.55, 0.60, 0.65, 0.70, 0.75, 0.80]]

# しきい値の安定性評価: 検証期間をサブ期間に分割し、
# 「サブ期間objectiveの平均 − ペナルティ×標準偏差」が最大のしきい値を選ぶ。
# 単一の検証期間全体の成績だけで選ぶと、その期間の地合いに過適合したしきい値
# (あるサブ期間だけ極端に良い)が選ばれることがあるため(2026-07の0.80過適合の教訓)。
# サブ期間の取引数が下限未満のしきい値は評価が不安定として選考から除外する。
THRESHOLD_STABILITY_SPLITS = 3
THRESHOLD_STABILITY_STD_PENALTY = 1.0
DEFAULT_ML_BUY_THRESHOLD = 0.55
MIN_ADJUSTED_ML_BUY_THRESHOLD = 0.50
MAX_ADJUSTED_ML_BUY_THRESHOLD = 0.80
MIN_SECTOR_THRESHOLD_ROWS = 120
MIN_SECTOR_THRESHOLD_TRADES = 10

# 月次再学習の自動昇格条件。候補モデルは、直近の未使用テスト期間で既存モデルより
# 目的関数をこの値以上改善し、勝率を大きく落とさず、十分な取引数がある場合だけ本番化する。
PROMOTION_MIN_TRADES = 30
PROMOTION_MIN_OBJECTIVE_IMPROVEMENT = 0.001  # 1取引あたり0.10%相当
PROMOTION_MAX_WIN_RATE_DECLINE = 0.02

# 特徴量選択: 正規化gain重要度がこの割合未満の特徴量を除外する(過学習・ノイズ削減)。
# 環境変数 SELECT_FEATURES=0 で無効化できる(A/B比較用)。
MIN_FEATURE_IMPORTANCE = 0.001

MARKET_INDICES = {
    "nikkei": ["^N225"],
    # yfinanceではTOPIX指数が空になることがあるため、無料で取得できるTOPIX連動ETFを代替に使う。
    "topix": ["^TOPX", "1306.T"],
    "usdjpy": ["JPY=X"],
    "nasdaq": ["^IXIC"],
    "sox": ["^SOX"],
    "vix": ["^VIX"],
}

# 米国指数・USD/JPYの日足終値は日本市場の取引時間後に確定するため、
# 日本株の特徴量としては次の日本の営業日から利用する。同日付で結合すると未来情報になる。
MARKET_DATA_AVAILABLE_NEXT_JP_BUSINESS_DAY = {"usdjpy", "nasdaq", "sox", "vix"}

MARKET_METRICS = [
    "return_1d",
    "return_5d",
    "return_20d",
    "sma25_ratio",
    "sma75_ratio",
    "rsi14",
    "volatility_20d",
]
TOPIX_OPEN_COLUMN = "topix_open"

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

# 市場ブレッドス(全銘柄共通)とクロスセクショナル順位(銘柄別)の特徴量。
# 日経・TOPIXなどの指数とは別に、処理対象ユニバース内部の強さと
# その日の全銘柄の中での相対的な位置を表す。add_breadth_features で算出する。
BREADTH_FEATURE_COLUMNS = [
    "breadth_above_sma25",         # 25日線を上回る銘柄の比率(0〜1)
    "breadth_advance_ratio",       # 前日比プラスの銘柄比率(0〜1)
    "breadth_above_sma25_chg_5d",  # 25日線超え比率の5日変化(-1〜1)
    "cs_rank_return_5d",           # 5日リターンの当日ユニバース内百分位(0〜1)
    "cs_rank_return_20d",          # 20日リターンの当日ユニバース内百分位(0〜1)
    "cs_rank_volume_ratio",        # 出来高比率の当日ユニバース内百分位(0〜1)
]

# ブレッドス・順位を計算する最低銘柄数。これ未満の日は比率・順位が不安定なため
# デフォルト値(中立)のままにする。
MIN_BREADTH_UNIVERSE = 30

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
    "volatility_20d",
    "volatility_60d",
    "atr_ratio_14d",
    "max_drawdown_20d",
    "trend_consistency_20d",
    "return_risk_ratio_20d",
    "open_gap_1d",
    "intraday_return",
    "daily_range_ratio",
    "close_location",
    "upper_shadow_ratio",
    "lower_shadow_ratio",
    "range_expansion_20d",
    "relative_strength_5d",
    "price_position_52w",
    "adx_14",
    "di_diff_14",
]

FEATURE_COLUMNS = (
    BASE_FEATURE_COLUMNS
    + MARKET_FEATURE_COLUMNS
    + SECTOR_FEATURE_COLUMNS
    + BREADTH_FEATURE_COLUMNS
)

import os

MODEL_PATH = os.path.join(os.path.dirname(__file__), "model.pkl")


def build_voting_model(
    rf_params: dict,
    gb_params: dict,
    lgbm_params: dict,
    seeds: list[int] | None = None,
) -> VotingClassifier:
    """RF/GB/LGBM×各シードのsoft voting分類器を作る(シード平均アンサンブル)。

    soft votingは全推定器のpredict_probaを平均するため、シードごとの
    アンサンブルを別々に学習して平均するのと等価で、保存物は素のsklearn
    オブジェクトのまま(fetch_and_signal.py側の変更が不要)。
    random_state / n_jobs / class_weight / verbose はここで付与するので
    params側には含めないこと。
    """
    seeds = ENSEMBLE_SEEDS if seeds is None else seeds
    estimators = []
    for seed in seeds:
        estimators.append((
            f"rf_{seed}",
            RandomForestClassifier(
                **rf_params, random_state=seed, n_jobs=-1, class_weight="balanced"
            ),
        ))
        estimators.append((
            f"gb_{seed}",
            GradientBoostingClassifier(**gb_params, random_state=seed),
        ))
        estimators.append((
            f"lgbm_{seed}",
            LGBMClassifier(
                **lgbm_params, random_state=seed, class_weight="balanced", verbose=-1
            ),
        ))
    return VotingClassifier(estimators=estimators, voting="soft")


def ensemble_disagreement(model, X) -> np.ndarray:
    """soft voting内の個別推定器の予測確率の標準偏差を返す。

    保存済みの旧モデルなどで個別推定器を取得できない場合は0を返し、
    後方互換を保つ。値が高いほど推定器間の見解が割れている。
    """
    estimators = getattr(model, "estimators_", None)
    if not estimators:
        return np.zeros(len(X), dtype=float)
    probabilities = [
        estimator.predict_proba(X)[:, 1]
        for estimator in estimators
        if hasattr(estimator, "predict_proba")
    ]
    if len(probabilities) < 2:
        return np.zeros(len(X), dtype=float)
    return np.std(np.vstack(probabilities), axis=0)


def market_default_value(column: str) -> float:
    """市場環境データが欠けた時に使う中立値"""
    if column.endswith("_rsi14"):
        return 50.0
    return 0.0


def sector_default_value() -> float:
    """業種別データが欠けた時に使う中立値"""
    return 0.0


def breadth_default_value(column: str) -> float:
    """ブレッドス・クロスセクショナル特徴量が欠けた時に使う中立値。
    比率・百分位は0.5(どちらでもない)、変化量は0.0を中立とする。"""
    if column.endswith("_chg_5d"):
        return 0.0
    return 0.5


def add_breadth_features(feature_frames: dict[str, pd.DataFrame]) -> dict[str, pd.DataFrame]:
    """処理対象ユニバース全体から市場ブレッドスとクロスセクショナル順位を算出する。

    - breadth_*: その日のユニバースにおける25日線超え/値上がり銘柄の比率(全銘柄で同じ値)
    - cs_rank_*: その日のユニバース内でのリターン・出来高比率の百分位順位(銘柄ごと)
    いずれも当日までのデータしか使わないため、未来情報のリークはない。
    銘柄数がMIN_BREADTH_UNIVERSE未満の日は算出せずデフォルト値(中立)のままにする。
    学習(build_dataset)・walk-forward(backtest_ml)・日次推論(fetch_and_signal)で
    同じ計算を共有する。ユニバースの銘柄数は場面で異なるが、比率・百分位のため
    スケールには依存しない。
    """
    rows = []
    for ticker, df in feature_frames.items():
        if df.empty or "date" not in df.columns:
            continue
        rows.append(
            df[["date", "sma25_ratio", "return_1d", "return_5d", "return_20d", "volume_ratio"]]
            .assign(ticker=ticker)
        )

    if not rows:
        return feature_frames

    all_rows = pd.concat(rows, ignore_index=True)
    universe_size = all_rows.groupby("date")["ticker"].transform("size")
    valid = all_rows[universe_size >= MIN_BREADTH_UNIVERSE].copy()

    result = {}
    if valid.empty:
        breadth = pd.DataFrame(columns=["date"])
        ranks_by_ticker = {}
    else:
        # 指標が未計算(NaN)の行はTrue/Falseに数えず、比率の分母からも除外する
        valid["above_sma25"] = np.where(
            valid["sma25_ratio"].isna(), np.nan, (valid["sma25_ratio"] > 0).astype(float)
        )
        valid["advance"] = np.where(
            valid["return_1d"].isna(), np.nan, (valid["return_1d"] > 0).astype(float)
        )
        breadth = (
            valid.groupby("date", as_index=False)
            .agg(
                breadth_above_sma25=("above_sma25", "mean"),
                breadth_advance_ratio=("advance", "mean"),
            )
            .sort_values("date")
            .reset_index(drop=True)
        )
        breadth["breadth_above_sma25_chg_5d"] = (
            breadth["breadth_above_sma25"] - breadth["breadth_above_sma25"].shift(5)
        )

        # クロスセクショナル百分位順位(その日の全銘柄中の位置、NaNはNaNのまま)
        for source_col, rank_col in [
            ("return_5d", "cs_rank_return_5d"),
            ("return_20d", "cs_rank_return_20d"),
            ("volume_ratio", "cs_rank_volume_ratio"),
        ]:
            valid[rank_col] = valid.groupby("date")[source_col].rank(pct=True)

        rank_columns = ["cs_rank_return_5d", "cs_rank_return_20d", "cs_rank_volume_ratio"]
        ranks_by_ticker = {
            ticker: group[["date"] + rank_columns]
            for ticker, group in valid.groupby("ticker")
        }

    for ticker, df in feature_frames.items():
        enriched = df.drop(
            columns=[c for c in BREADTH_FEATURE_COLUMNS if c in df.columns],
            errors="ignore",
        )
        if not breadth.empty:
            enriched = enriched.merge(breadth, on="date", how="left")
        ticker_ranks = ranks_by_ticker.get(ticker)
        if ticker_ranks is not None:
            enriched = enriched.merge(ticker_ranks, on="date", how="left")
        for column in BREADTH_FEATURE_COLUMNS:
            if column not in enriched.columns:
                enriched[column] = breadth_default_value(column)
            enriched[column] = enriched[column].fillna(breadth_default_value(column))
        result[ticker] = enriched

    return result


def select_features(X_train, y_train, candidate_columns, sample_weight=None) -> list[str]:
    """学習データのLGBM gain重要度をもとに寄与の小さい特徴量を除外する。
    テスト/検証データを使わずtrainのみで選定し、評価リークを避ける。"""
    candidate_columns = list(candidate_columns)
    selector = LGBMClassifier(
        n_estimators=200,
        max_depth=5,
        min_child_samples=20,
        class_weight="balanced",
        random_state=42,
        verbose=-1,
        importance_type="gain",
    )
    selector.fit(X_train[candidate_columns], y_train, sample_weight=sample_weight)
    importances = np.asarray(selector.feature_importances_, dtype=float)
    total = importances.sum()
    if total <= 0:
        return candidate_columns
    norm = importances / total
    selected = [c for c, imp in zip(candidate_columns, norm) if imp >= MIN_FEATURE_IMPORTANCE]
    # 安全策: 極端に少なくなった場合は重要度上位30件にフォールバックする
    if len(selected) < 10:
        top_idx = sorted(np.argsort(norm)[::-1][:30])
        selected = [candidate_columns[i] for i in top_idx]
    return selected


def calibrate_scores(raw_scores, calibration_values: list[float] | None):
    """学習済みの分位点テーブルを使い、予測確率を0〜1の相対スコアに変換する"""
    if not calibration_values:
        return raw_scores
    percentiles = [p / 100 for p in range(0, 101, 5)]
    return np.interp(raw_scores, calibration_values, percentiles)


def _feature_value(row: pd.Series, column: str, default: float = 0.0) -> float:
    """特徴量の欠損や未定義を安全に中立値へ寄せる"""
    value = row.get(column, default)
    if pd.isna(value) or not np.isfinite(value):
        return default
    return float(value)


def market_regime_adjustment(row: pd.Series) -> float:
    """市場環境に応じてML買いしきい値を微調整する"""
    adjustment = 0.0

    nikkei_5d = _feature_value(row, "nikkei_return_5d")
    topix_5d = _feature_value(row, "topix_return_5d")
    nasdaq_5d = _feature_value(row, "nasdaq_return_5d")
    sox_5d = _feature_value(row, "sox_return_5d")
    vix_5d = _feature_value(row, "vix_return_5d")
    nikkei_sma25 = _feature_value(row, "nikkei_sma25_ratio")
    topix_sma25 = _feature_value(row, "topix_sma25_ratio")

    # 地合いが悪い日は買い判定を厳しくする。無料で取れる指数だけを使う。
    if nikkei_5d < -0.02 or topix_5d < -0.02:
        adjustment += 0.04
    if nasdaq_5d < -0.03 or sox_5d < -0.04:
        adjustment += 0.03
    if vix_5d > 0.15:
        adjustment += 0.03
    if nikkei_sma25 < -0.03 or topix_sma25 < -0.03:
        adjustment += 0.03

    # 地合いが素直に強い日は、良い候補を少し拾いやすくする。
    if (
        nikkei_5d > 0.01
        and topix_5d > 0.01
        and nikkei_sma25 > 0
        and topix_sma25 > 0
        and vix_5d < 0
    ):
        adjustment -= 0.03
    if nasdaq_5d > 0.02 and sox_5d > 0.02 and vix_5d < 0:
        adjustment -= 0.02

    return adjustment


def sector_base_threshold(
    base_threshold: float,
    sector_thresholds: dict[str, float] | None = None,
    sector: str | None = None,
) -> float:
    """業種別しきい値があれば使い、なければ全体しきい値を使う"""
    if sector and sector_thresholds and sector in sector_thresholds:
        return float(sector_thresholds[sector])
    return float(base_threshold)


def adjusted_ml_buy_threshold(base_threshold: float, row: pd.Series) -> float:
    """市場環境を反映した当日用のML買いしきい値"""
    threshold = base_threshold + market_regime_adjustment(row)
    return float(np.clip(threshold, MIN_ADJUSTED_ML_BUY_THRESHOLD, MAX_ADJUSTED_ML_BUY_THRESHOLD))


def ml_buy_block_reasons(row: pd.Series) -> list[str]:
    """AIスコアが高くても買いを見送る条件を返す"""
    reasons = []

    nikkei_20d = _feature_value(row, "nikkei_return_20d")
    topix_20d = _feature_value(row, "topix_return_20d")
    nikkei_sma75 = _feature_value(row, "nikkei_sma75_ratio")
    topix_sma75 = _feature_value(row, "topix_sma75_ratio")
    vix_5d = _feature_value(row, "vix_return_5d")

    if nikkei_20d < -0.05 and topix_20d < -0.05 and (nikkei_sma75 < 0 or topix_sma75 < 0):
        reasons.append("市場全体が下落トレンド")
    if vix_5d > 0.30:
        reasons.append("VIX急上昇")

    return_5d = _feature_value(row, "return_5d")
    volume_ratio = _feature_value(row, "volume_ratio", 1.0)
    volatility_20d = _feature_value(row, "volatility_20d")
    atr_ratio_14d = _feature_value(row, "atr_ratio_14d")
    upper_shadow_ratio = _feature_value(row, "upper_shadow_ratio")
    close_location = _feature_value(row, "close_location", 0.5)
    range_expansion_20d = _feature_value(row, "range_expansion_20d", 1.0)
    intraday_return = _feature_value(row, "intraday_return")
    max_drawdown_20d = _feature_value(row, "max_drawdown_20d")

    if return_5d > 0.03 and volume_ratio < 0.60:
        reasons.append("薄商いの上昇")
    if volatility_20d > 0.06 or atr_ratio_14d > 0.08:
        reasons.append("値動きが荒すぎる")
    if upper_shadow_ratio > 0.60 and close_location < 0.45:
        reasons.append("上ヒゲで押し戻されている")
    if range_expansion_20d > 2.5 and intraday_return < 0:
        reasons.append("下落方向の値幅拡大")
    if return_5d < -0.08 or max_drawdown_20d < -0.18:
        reasons.append("短期下落が深い")

    return reasons


def is_ml_buy_blocked(row: pd.Series) -> bool:
    """買わないフィルターに該当するか"""
    return bool(ml_buy_block_reasons(row))


def evaluate_threshold(
    scores,
    future_returns,
    threshold: float,
    feature_rows: pd.DataFrame | None = None,
    sectors: pd.Series | None = None,
    sector_thresholds: dict[str, float] | None = None,
    dates=None,
    max_daily_candidates: int = 0,
    disagreements=None,
    max_ensemble_disagreement: float | None = None,
) -> dict:
    """指定しきい値で買った場合の5営業日後リターンを評価する。

    win_rate / hit_rate / avg_return / total_return / objective は
    1取引あたりTRANSACTION_COST(往復手数料+スリッページ)を控除したnetリターンで計算する。
    参考値としてコスト控除前の avg_return_gross も返す。
    """
    scores = np.asarray(scores)
    future_returns = np.asarray(future_returns)
    if feature_rows is not None:
        sector_values = sectors.reindex(feature_rows.index) if sectors is not None else None
        thresholds = [
            adjusted_ml_buy_threshold(
                sector_base_threshold(
                    threshold,
                    sector_thresholds,
                    None if sector_values is None else str(sector_values.loc[index]),
                ),
                row,
            )
            for index, row in feature_rows.iterrows()
        ]
        thresholds = np.asarray(thresholds)
        blocked = feature_rows.apply(is_ml_buy_blocked, axis=1).to_numpy(dtype=bool)
        mask = (scores >= thresholds) & ~blocked
    else:
        mask = scores >= threshold

    if max_ensemble_disagreement is not None:
        if disagreements is None:
            raise ValueError("アンサンブル不一致フィルターを使う場合はdisagreementsが必要です")
        disagreements = np.asarray(disagreements, dtype=float)
        if len(disagreements) != len(scores):
            raise ValueError("disagreementsとscoresの件数が一致しません")
        mask &= np.isfinite(disagreements) & (disagreements <= max_ensemble_disagreement)

    # 日次推論と同じく、しきい値・買わないフィルター通過後のスコア上位だけを採用する。
    # 昇格判定でこの制限を入れないと、本番では選ばれない下位候補の成績で判定してしまう。
    if max_daily_candidates > 0:
        if dates is None:
            raise ValueError("max_daily_candidatesを使う場合はdatesが必要です")
        date_values = np.asarray(pd.Series(dates).to_numpy())
        if len(date_values) != len(scores):
            raise ValueError("datesとscoresの件数が一致しません")
        eligible_positions = np.flatnonzero(mask)
        ranked = pd.DataFrame(
            {
                "position": eligible_positions,
                "date": date_values[eligible_positions],
                "score": scores[eligible_positions],
            }
        )
        selected_positions = (
            ranked.sort_values(
                ["date", "score", "position"],
                ascending=[True, False, True],
            )
            .groupby("date", sort=False)
            .head(max_daily_candidates)["position"]
            .to_numpy(dtype=int)
        )
        mask = np.zeros(len(scores), dtype=bool)
        mask[selected_positions] = True

    gross_returns = future_returns[mask]
    trades = int(mask.sum())
    if trades == 0:
        return {
            "threshold": threshold,
            "trades": 0,
            "win_rate": 0.0,
            "hit_rate": 0.0,
            "avg_return": 0.0,
            "avg_return_gross": 0.0,
            "total_return": 0.0,
            "cost_per_trade": TRANSACTION_COST,
            "max_daily_candidates": max_daily_candidates,
            "max_ensemble_disagreement": max_ensemble_disagreement,
            "objective": float("-inf"),
        }

    # 往復コスト控除後のリターンで評価する(手数料負けする取引を勝ち扱いしない)
    net_returns = gross_returns - TRANSACTION_COST
    win_rate = float((net_returns > 0).mean())
    hit_rate = float((net_returns >= EXCESS_RETURN_TARGET).mean())
    avg_return = float(net_returns.mean())
    total_return = float(net_returns.sum())

    # 平均リターンを主軸に、勝率と+2%以上の的中率を少し加味する。
    # 極端に取引数が少ないしきい値は optimize_ml_buy_threshold 側で除外する。
    objective = avg_return + win_rate * 0.005 + hit_rate * 0.005
    return {
        "threshold": threshold,
        "trades": trades,
        "win_rate": win_rate,
        "hit_rate": hit_rate,
        "avg_return": avg_return,
        "avg_return_gross": float(gross_returns.mean()),
        "total_return": total_return,
        "cost_per_trade": TRANSACTION_COST,
        "max_daily_candidates": max_daily_candidates,
        "max_ensemble_disagreement": max_ensemble_disagreement,
        "objective": objective,
    }


def evaluate_model_bundle(
    bundle: dict,
    evaluation_df: pd.DataFrame,
) -> tuple[dict | None, str | None]:
    """保存済みモデルを候補と同じ未使用期間・約定ベースのリターンで評価する。

    過去のモデルに必要な特徴量がなければ、無理に比較して昇格させない。
    """
    features = bundle.get("features", [])
    if not features:
        return None, "既存モデルの特徴量メタ情報がない"

    evaluation_df = evaluation_df.copy()
    missing = [column for column in features if column not in evaluation_df.columns]
    missing_sector_columns = [column for column in missing if column.startswith("sector_")]
    missing_non_sector_columns = [column for column in missing if not column.startswith("sector_")]
    for column in missing_sector_columns:
        # 学習時のユニバースにだけ存在した業種は、今回の評価行では全銘柄が非該当なので0が正しい。
        evaluation_df[column] = 0.0
    if missing_non_sector_columns:
        return None, (
            "既存モデルの数値特徴量が評価データにない "
            f"({', '.join(missing_non_sector_columns[:3])})"
        )

    try:
        raw_scores = bundle["model"].predict_proba(evaluation_df[features])[:, 1]
    except (KeyError, ValueError) as exc:
        return None, f"既存モデルの推論に失敗 ({exc})"

    scores = calibrate_scores(raw_scores, bundle.get("score_calibration"))
    max_daily_candidates = int(
        bundle.get("training_config", {}).get("max_daily_ml_buy_candidates", 0) or 0
    )
    max_ensemble_disagreement = bundle.get("ensemble_disagreement", {}).get("max")
    disagreements = (
        ensemble_disagreement(bundle["model"], evaluation_df[features])
        if max_ensemble_disagreement is not None
        else None
    )
    result = evaluate_threshold(
        scores,
        evaluation_df["future_excess_return"].to_numpy(),
        float(bundle.get("ml_buy_threshold", DEFAULT_ML_BUY_THRESHOLD)),
        evaluation_df,
        evaluation_df["sector_label"],
        bundle.get("sector_ml_buy_thresholds", {}),
        dates=evaluation_df["date"],
        max_daily_candidates=max_daily_candidates,
        disagreements=disagreements,
        max_ensemble_disagreement=max_ensemble_disagreement,
    )
    return result, None


def should_promote_candidate(candidate: dict, baseline: dict | None) -> tuple[bool, str]:
    """再学習候補を本番モデルへ昇格させるかを決める。"""
    if baseline is None:
        # 初回導入時だけは比較対象がないため候補を保存し、次回から厳格比較する。
        return True, "比較可能な既存モデルがないため初回モデルとして保存"
    if candidate["trades"] < PROMOTION_MIN_TRADES:
        return False, f"候補の取引数不足 ({candidate['trades']} < {PROMOTION_MIN_TRADES})"
    if baseline["trades"] < PROMOTION_MIN_TRADES:
        return True, f"既存モデルの取引数不足 ({baseline['trades']} < {PROMOTION_MIN_TRADES})"

    improvement = candidate["objective"] - baseline["objective"]
    # 浮動小数点の丸めで、ちょうど閾値の改善を誤って見送らないよう許容誤差を置く。
    if improvement + 1e-12 < PROMOTION_MIN_OBJECTIVE_IMPROVEMENT:
        return False, (
            f"目的関数の改善不足 ({improvement:+.4f} < "
            f"{PROMOTION_MIN_OBJECTIVE_IMPROVEMENT:+.4f})"
        )
    if candidate["win_rate"] < baseline["win_rate"] - PROMOTION_MAX_WIN_RATE_DECLINE:
        return False, "勝率の低下が許容範囲を超過"
    return True, f"目的関数改善 {improvement:+.4f}、勝率条件・取引数を満たしたため昇格"


def add_stability_metrics(
    result: dict,
    scores,
    future_returns,
    threshold: float,
    feature_rows: pd.DataFrame | None,
    dates,
    min_trades: int,
) -> None:
    """しきい値の成績をサブ期間ごとに評価し、resultへ安定性指標を追記する。

    - sub_periods: 各サブ期間の取引数・平均リターン・objective
    - stable: 全サブ期間で最低取引数を満たすか
    - stability_objective: 安定な場合のみ、サブ期間objectiveの平均 − ペナルティ×標準偏差
    """
    date_values = np.asarray(pd.Series(dates).to_numpy())
    unique_dates = np.array(sorted(pd.unique(date_values)))
    if len(unique_dates) < THRESHOLD_STABILITY_SPLITS * 2:
        return  # 期間が短すぎて分割評価できない

    scores = np.asarray(scores)
    future_returns = np.asarray(future_returns)
    min_sub_trades = max(5, min_trades // (THRESHOLD_STABILITY_SPLITS * 2))

    sub_periods = []
    for chunk in np.array_split(unique_dates, THRESHOLD_STABILITY_SPLITS):
        mask = np.isin(date_values, chunk)
        sub_eval = evaluate_threshold(
            scores[mask],
            future_returns[mask],
            threshold,
            None if feature_rows is None else feature_rows.iloc[mask],
        )
        sub_periods.append(
            {
                "start": str(chunk[0]),
                "end": str(chunk[-1]),
                "trades": sub_eval["trades"],
                "avg_return": sub_eval["avg_return"],
                "objective": sub_eval["objective"],
            }
        )

    result["sub_periods"] = sub_periods
    stable = all(s["trades"] >= min_sub_trades for s in sub_periods)
    result["stable"] = stable
    if stable:
        objectives = np.array([s["objective"] for s in sub_periods])
        result["stability_objective"] = float(
            objectives.mean() - THRESHOLD_STABILITY_STD_PENALTY * objectives.std()
        )


def optimize_ml_buy_threshold(
    scores,
    future_returns,
    feature_rows: pd.DataFrame | None = None,
    min_trades: int | None = None,
    dates=None,
) -> tuple[float, list[dict]]:
    """検証データで買い判定しきい値を自動最適化する。

    datesを渡すと検証期間をサブ期間に分割した安定性評価を行い、
    全サブ期間で取引数を確保でき「平均objective − ばらつきペナルティ」が
    最大のしきい値を選ぶ(単一の地合いへの過適合を防ぐ)。
    安定なしきい値が1つも無い場合は従来通り全期間objectiveで選ぶ。
    """
    min_trades = min_trades if min_trades is not None else max(30, int(len(scores) * 0.02))
    results = []
    for threshold in THRESHOLD_GRID:
        result = evaluate_threshold(scores, future_returns, threshold, feature_rows)
        if dates is not None and result["trades"] >= min_trades:
            add_stability_metrics(
                result, scores, future_returns, threshold, feature_rows, dates, min_trades
            )
        results.append(result)
    valid_results = [r for r in results if r["trades"] >= min_trades]

    if not valid_results:
        print(f"しきい値最適化: 取引数が少ないためデフォルト {DEFAULT_ML_BUY_THRESHOLD} を使用")
        return DEFAULT_ML_BUY_THRESHOLD, results

    stable_results = [r for r in valid_results if r.get("stability_objective") is not None]
    if stable_results:
        best = max(
            stable_results,
            key=lambda r: (r["stability_objective"], r["objective"], r["avg_return"], r["trades"]),
        )
    else:
        if dates is not None:
            print("しきい値最適化: 安定なしきい値が無いため全期間成績で選択")
        best = max(
            valid_results,
            key=lambda r: (r["objective"], r["avg_return"], r["win_rate"], r["trades"]),
        )
    return float(best["threshold"]), results


def optimize_sector_thresholds(
    base_threshold: float,
    scores,
    future_returns,
    feature_rows: pd.DataFrame,
    sectors: pd.Series,
    dates=None,
) -> tuple[dict[str, float], dict[str, dict]]:
    """業種ごとに、共通しきい値より良い場合だけ専用しきい値を採用する。

    datesを渡した場合はサブ期間の安定性指標で共通しきい値と比較し、
    安定性を評価できない業種は個別しきい値を採用しない(過適合防止のため厳格化)。
    """
    sector_thresholds: dict[str, float] = {}
    sector_results: dict[str, dict] = {}
    score_series = pd.Series(scores, index=feature_rows.index)
    return_series = pd.Series(future_returns, index=feature_rows.index)
    date_series = None if dates is None else pd.Series(list(dates), index=feature_rows.index)

    for sector, sector_index in sectors.groupby(sectors).groups.items():
        if sector == "不明" or len(sector_index) < MIN_SECTOR_THRESHOLD_ROWS:
            continue

        sector_features = feature_rows.loc[sector_index]
        sector_scores = score_series.loc[sector_index].to_numpy()
        sector_returns = return_series.loc[sector_index].to_numpy()
        sector_dates = None if date_series is None else date_series.loc[sector_index]
        min_trades = max(MIN_SECTOR_THRESHOLD_TRADES, int(len(sector_features) * 0.03))

        global_eval = evaluate_threshold(
            sector_scores,
            sector_returns,
            base_threshold,
            sector_features,
        )
        if sector_dates is not None and global_eval["trades"] >= min_trades:
            add_stability_metrics(
                global_eval,
                sector_scores,
                sector_returns,
                base_threshold,
                sector_features,
                sector_dates,
                min_trades,
            )
        threshold, results = optimize_ml_buy_threshold(
            sector_scores,
            sector_returns,
            sector_features,
            min_trades=min_trades,
            dates=sector_dates,
        )
        best_eval = next((r for r in results if r["threshold"] == threshold), None)
        if best_eval is None or best_eval["trades"] < min_trades:
            continue

        # 共通しきい値より検証目的関数が良い業種だけ採用し、過剰な業種別最適化を避ける。
        # 安定性指標があるときはそれで比較し、業種側の安定性が評価できない場合は不採用。
        best_stability = best_eval.get("stability_objective")
        global_stability = global_eval.get("stability_objective")
        if best_stability is not None and global_stability is not None:
            adopt = best_stability > global_stability
        elif dates is not None:
            adopt = False
        else:
            adopt = best_eval["objective"] > global_eval["objective"]
        if adopt and threshold != base_threshold:
            sector_thresholds[str(sector)] = float(threshold)
            sector_results[str(sector)] = {
                "threshold": float(threshold),
                "rows": int(len(sector_features)),
                "min_trades": int(min_trades),
                "global_eval": global_eval,
                "best_eval": best_eval,
            }

    return sector_thresholds, sector_results


def optimize_ensemble_disagreement(
    scores,
    disagreements,
    future_returns,
    threshold: float,
    feature_rows: pd.DataFrame,
    sectors: pd.Series,
    sector_thresholds: dict[str, float],
    dates,
    max_daily_candidates: int,
) -> tuple[float | None, list[dict]]:
    """検証期間だけでアンサンブル不一致の上限を選ぶ。

    取引数が少なすぎる上限は除外し、改善がなければNone（フィルターなし）を選べる。
    日次上位件数・市場/業種フィルターも本番と同じ条件で評価する。
    """
    min_trades = max(30, int(len(scores) * 0.02))
    results = []
    for limit in ENSEMBLE_DISAGREEMENT_GRID:
        result = evaluate_threshold(
            scores,
            future_returns,
            threshold,
            feature_rows,
            sectors,
            sector_thresholds,
            dates=dates,
            max_daily_candidates=max_daily_candidates,
            disagreements=disagreements if limit is not None else None,
            max_ensemble_disagreement=limit,
        )
        result["max_ensemble_disagreement"] = limit
        results.append(result)

    valid = [result for result in results if result["trades"] >= min_trades]
    if not valid:
        return None, results
    best = max(
        valid,
        key=lambda result: (
            result["objective"],
            result["avg_return"],
            result["win_rate"],
            result["trades"],
        ),
    )
    return best["max_ensemble_disagreement"], results


def build_market_features(symbols: str | list[str], prefix: str) -> pd.DataFrame:
    """市場指数・為替データを同じ形式の特徴量へ変換"""
    if isinstance(symbols, str):
        symbols = [symbols]

    hist = pd.DataFrame()
    used_symbol = None
    for symbol in symbols:
        candidate = yf.Ticker(symbol).history(period=TRAIN_HISTORY_PERIOD)
        if not candidate.empty:
            hist = candidate
            used_symbol = symbol
            if symbol != symbols[0]:
                print(f"market data fallback: {prefix} {symbols[0]} -> {symbol}")
            break
        print(f"market data empty: {symbol}")

    if hist.empty:
        print(f"market data unavailable: {prefix}")
        return pd.DataFrame(columns=["date"] + [f"{prefix}_{m}" for m in MARKET_METRICS])

    print(f"market data loaded: {prefix}={used_symbol}")
    hist = hist.reset_index()
    source_dates = pd.to_datetime(hist["Date"])
    if prefix in MARKET_DATA_AVAILABLE_NEXT_JP_BUSINESS_DAY:
        # 祝日は日本市場の行がないため、build_featuresのforward fillによって
        # 次の実際の日本取引日に初めて反映される。
        source_dates = source_dates + pd.offsets.BDay(1)
    hist["date"] = source_dates.dt.date
    hist[f"{prefix}_return_1d"] = hist["Close"] / hist["Close"].shift(1) - 1
    hist[f"{prefix}_return_5d"] = hist["Close"] / hist["Close"].shift(5) - 1
    hist[f"{prefix}_return_20d"] = hist["Close"] / hist["Close"].shift(20) - 1
    hist[f"{prefix}_sma25"] = hist["Close"].rolling(25).mean()
    hist[f"{prefix}_sma75"] = hist["Close"].rolling(75).mean()
    hist[f"{prefix}_sma25_ratio"] = hist["Close"] / hist[f"{prefix}_sma25"] - 1
    hist[f"{prefix}_sma75_ratio"] = hist["Close"] / hist[f"{prefix}_sma75"] - 1
    hist[f"{prefix}_rsi14"] = calc_rsi(hist["Close"], 14)
    hist[f"{prefix}_volatility_20d"] = hist[f"{prefix}_return_1d"].rolling(20).std()

    columns = ["date"] + [f"{prefix}_{m}" for m in MARKET_METRICS]
    # TOPIX指数が取得できない場合は1306.Tを使うため、どちらも同じ列名で扱う。
    # 始値は超過リターンのラベル作成専用であり、モデル特徴量には含めない。
    if prefix == "topix":
        hist[TOPIX_OPEN_COLUMN] = hist["Open"]
        columns.append(TOPIX_OPEN_COLUMN)
    return hist[columns]


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

    extra_columns = [TOPIX_OPEN_COLUMN] if TOPIX_OPEN_COLUMN in market.columns else []
    return market[["date"] + MARKET_FEATURE_COLUMNS + extra_columns]


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

    # 値動きの荒さと安定性。上昇していても乱高下が大きい銘柄を区別する。
    df["volatility_20d"] = df["return_1d"].rolling(20).std()
    df["volatility_60d"] = df["return_1d"].rolling(60).std()
    prev_close = df["Close"].shift(1)
    true_range = pd.concat(
        [
            df["High"] - df["Low"],
            (df["High"] - prev_close).abs(),
            (df["Low"] - prev_close).abs(),
        ],
        axis=1,
    ).max(axis=1)
    df["atr_ratio_14d"] = true_range.rolling(14).mean() / df["Close"]
    df["max_drawdown_20d"] = df["Close"] / df["Close"].rolling(20).max() - 1
    df["trend_consistency_20d"] = (df["return_1d"] > 0).rolling(20).mean()
    df["return_risk_ratio_20d"] = df["return_20d"] / df["volatility_20d"].replace(0, np.nan)

    # ローソク足・日中需給の特徴量。寄り付き後に買われたか、上値を抑えられたかを見る。
    daily_range = (df["High"] - df["Low"]).replace(0, np.nan)
    candle_body_high = df[["Open", "Close"]].max(axis=1)
    candle_body_low = df[["Open", "Close"]].min(axis=1)
    df["open_gap_1d"] = df["Open"] / prev_close - 1
    df["intraday_return"] = df["Close"] / df["Open"] - 1
    df["daily_range_ratio"] = daily_range / df["Close"]
    df["close_location"] = (df["Close"] - df["Low"]) / daily_range
    df["upper_shadow_ratio"] = (df["High"] - candle_body_high) / daily_range
    df["lower_shadow_ratio"] = (candle_body_low - df["Low"]) / daily_range
    df["range_expansion_20d"] = df["daily_range_ratio"] / df["daily_range_ratio"].rolling(20).mean()

    # 52週(252営業日)高値・安値の中での現在値の位置(0=安値, 1=高値)
    low_52w = df["Close"].rolling(252, min_periods=60).min()
    high_52w = df["Close"].rolling(252, min_periods=60).max()
    df["price_position_52w"] = (df["Close"] - low_52w) / (high_52w - low_52w)

    # ADX: トレンドの強さ(0〜100)とDI差分(正=上昇トレンド、負=下落トレンド)
    df["adx_14"], df["di_diff_14"] = calc_adx(df["High"], df["Low"], df["Close"])

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
        if TOPIX_OPEN_COLUMN in df.columns:
            df["topix_benchmark_return"] = (
                df[TOPIX_OPEN_COLUMN].shift(-LABEL_LOOKAHEAD_DAYS)
                / df[TOPIX_OPEN_COLUMN].shift(-1)
                - 1
            )
        else:
            df["topix_benchmark_return"] = np.nan
    else:
        df["relative_strength_5d"] = df["return_5d"]
        df["topix_benchmark_return"] = np.nan
        for column in MARKET_FEATURE_COLUMNS:
            df[column] = market_default_value(column)

    for column in SECTOR_FEATURE_COLUMNS:
        if column not in df.columns:
            df[column] = sector_default_value()

    # ブレッドス特徴量はユニバース全体が必要なため単一銘柄では計算できない。
    # add_breadth_features を通さない経路でも列が揃うよう中立値で埋めておく。
    for column in BREADTH_FEATURE_COLUMNS:
        if column not in df.columns:
            df[column] = breadth_default_value(column)

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


def compute_barrier_outcome(
    df: pd.DataFrame,
    horizon_days: int = HORIZON_DAYS,
    target_return: float = TARGET_RETURN,
    stop_loss_pct: float = STOP_LOSS_PCT,
) -> tuple[pd.Series, pd.Series]:
    """翌営業日始値約定の実運用ルールに合わせてラベルと実現リターンを計算する。

    シグナル日 i の翌営業日始値で買い、horizon_days 営業日の保有中に損切りへ到達したら
    決済する。寄り付きが損切り水準を下回った場合は、楽観的に損切り価格で約定したと
    仮定せず、その日の始値で決済する。損切りされなければ i+1+horizon_days の始値で
    時間決済する。これにより学習・しきい値評価・backtest_ml.py の約定前提を統一する。
    """
    open_ = df["Open"].to_numpy(dtype=float)
    low = df["Low"].to_numpy(dtype=float)
    n = len(df)

    labels = np.full(n, np.nan)
    realized = np.full(n, np.nan)

    for i in range(n - LABEL_LOOKAHEAD_DAYS):
        entry_idx = i + 1
        exit_idx = entry_idx + horizon_days
        entry = open_[entry_idx]
        if not np.isfinite(entry) or entry == 0:
            continue
        stop_price = entry * (1 - stop_loss_pct)
        for day_idx in range(entry_idx, exit_idx):
            if not np.isfinite(open_[day_idx]) or not np.isfinite(low[day_idx]):
                break
            if open_[day_idx] <= stop_price:
                realized[i] = open_[day_idx] / entry - 1
                labels[i] = 0
                break
            if low[day_idx] <= stop_price:
                realized[i] = -stop_loss_pct
                labels[i] = 0
                break
        else:
            if np.isfinite(open_[exit_idx]):
                time_return = open_[exit_idx] / entry - 1
                realized[i] = time_return
                labels[i] = 1 if time_return >= target_return else 0

    return pd.Series(labels, index=df.index), pd.Series(realized, index=df.index)


def add_excess_return_targets(
    feature_frames: dict[str, pd.DataFrame],
    sectors: dict[str, str],
) -> dict[str, pd.DataFrame]:
    """約定ベースの実現リターンから、業種・市場に対する超過リターンのラベルを作る。

    ベンチマークは同日・同業種の他銘柄の平均を優先し、十分な銘柄数がない場合は
    TOPIX（取得不可時は学習ユニバース全体の他銘柄平均）へフォールバックする。平均は自銘柄を除外するため、
    正解ラベルへ自銘柄の値動きが混ざる自己参照を避けられる。
    """
    prepared: dict[str, pd.DataFrame] = {}
    rows = []
    for ticker, frame in feature_frames.items():
        source = frame.copy()
        source["_ticker"] = ticker
        source["_sector"] = sectors.get(ticker, "不明")
        if "topix_benchmark_return" not in source.columns:
            source["topix_benchmark_return"] = np.nan
        source["future_return"] = compute_barrier_outcome(source)[1]
        prepared[ticker] = source
        rows.append(source[["date", "_ticker", "_sector", "future_return", "topix_benchmark_return"]])

    if not rows:
        return prepared

    outcomes = pd.concat(rows, ignore_index=True).dropna(subset=["future_return"])
    market = outcomes.groupby("date")["future_return"].agg(["sum", "count"])
    market.columns = ["market_sum", "market_count"]
    sector = outcomes.groupby(["date", "_sector"])["future_return"].agg(["sum", "count"])
    sector.columns = ["sector_sum", "sector_count"]
    benchmarks = outcomes.join(market, on="date").join(sector, on=["date", "_sector"])
    benchmarks["market_benchmark_return"] = (
        (benchmarks["market_sum"] - benchmarks["future_return"])
        / (benchmarks["market_count"] - 1)
    )
    benchmarks["sector_benchmark_return"] = (
        (benchmarks["sector_sum"] - benchmarks["future_return"])
        / (benchmarks["sector_count"] - 1)
    )
    benchmarks["benchmark_return"] = np.where(
        benchmarks["sector_count"] >= MIN_SECTOR_BENCHMARK_MEMBERS,
        benchmarks["sector_benchmark_return"],
        benchmarks["topix_benchmark_return"].fillna(benchmarks["market_benchmark_return"]),
    )
    benchmarks["future_excess_return"] = (
        benchmarks["future_return"] - benchmarks["benchmark_return"]
    )
    benchmarks["label"] = np.where(
        benchmarks["future_excess_return"].notna(),
        (benchmarks["future_excess_return"] >= EXCESS_RETURN_TARGET).astype(float),
        np.nan,
    )

    target_columns = [
        "date", "_ticker", "future_return", "benchmark_return", "future_excess_return", "label"
    ]
    result = {}
    for ticker, source in prepared.items():
        enriched = source.merge(
            benchmarks[target_columns], on=["date", "_ticker", "future_return"], how="left"
        )
        result[ticker] = enriched.drop(columns=["_ticker", "_sector"])
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
        hist = yf.Ticker(ticker).history(period=TRAIN_HISTORY_PERIOD)
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
    feature_frames = add_breadth_features(feature_frames)

    labeled_frames = add_excess_return_targets(feature_frames, sectors)
    for ticker, df in labeled_frames.items():

        # 特徴量・ラベルが揃っている行のみ使用(末尾は翌日約定+時間決済の未来データがないため除外)
        df = df.dropna(subset=FEATURE_COLUMNS + ["future_return", "future_excess_return", "label"])
        df["label"] = df["label"].astype(int)

        df = df[["date"] + FEATURE_COLUMNS + ["future_return", "benchmark_return", "future_excess_return", "label"]].copy()
        df["sector"] = sectors.get(ticker, "不明")
        rows.append(df)
        print(f"{ticker}: {len(df)} rows")

    dataset = pd.concat(rows, ignore_index=True)
    dataset["sector_label"] = dataset["sector"]
    dataset = pd.get_dummies(dataset, columns=["sector"], prefix="sector")
    return dataset


def main():
    print("学習データを作成中...")
    try:
        previous_bundle = joblib.load(MODEL_PATH)
        print("既存モデルを読み込み、昇格判定の比較対象にします")
    except FileNotFoundError:
        previous_bundle = None
        print("既存モデルがないため、今回の学習結果を初回モデルとして扱います")
    dataset = build_dataset()
    print(f"\n合計 {len(dataset)} 行 (上昇ラベル比率: {dataset['label'].mean():.3f})")

    # 業種one-hot列のみを抽出する。sector_return_* などの数値特徴量は除外する。
    sector_columns = [
        c for c in dataset.columns
        if c.startswith("sector_") and c not in FEATURE_COLUMNS and c != "sector_label"
    ]
    feature_columns = FEATURE_COLUMNS + sector_columns

    # walk-forward検証: 日付でソートし、学習70% / 検証15% / テスト15%に3分割する
    # (ランダム分割だと未来のデータが学習に混ざり精度が甘く出るため)
    # 検証データは「しきい値の最適化」に使い、テストデータは最終評価専用とすることで
    # しきい値最適化に未来のテストデータが漏れ込む問題(評価リーク)を防ぐ。
    dataset = dataset.sort_values("date").reset_index(drop=True)
    train_end = int(len(dataset) * 0.7)
    val_end = int(len(dataset) * 0.85)

    # エンバーゴ: ラベルが翌日約定からLABEL_LOOKAHEAD_DAYS営業日先までの値動きを使うため、単純な時系列分割では
    # 境界付近の学習行のラベルが検証/テスト期間の値動きに依存し、情報が漏れる(評価が甘くなる)。
    # 各境界の手前LABEL_LOOKAHEAD_DAYS営業日分を除外し、分割の間に空白期間を設けて漏れを防ぐ。
    unique_dates = sorted(dataset["date"].unique().tolist())

    def embargo_cutoff(boundary_date):
        """boundary_date の必要エンバーゴ日前の日付を返す"""
        idx = bisect.bisect_left(unique_dates, boundary_date)
        return unique_dates[max(idx - LABEL_LOOKAHEAD_DAYS, 0)]

    val_start_date = dataset.iloc[train_end]["date"]
    test_start_date = dataset.iloc[val_end]["date"]
    train_cutoff = embargo_cutoff(val_start_date)
    val_cutoff = embargo_cutoff(test_start_date)

    train_df = dataset.iloc[:train_end]
    train_df = train_df[train_df["date"] < train_cutoff]
    val_df = dataset.iloc[train_end:val_end]
    val_df = val_df[val_df["date"] < val_cutoff]
    test_df = dataset.iloc[val_end:]
    print(f"学習データ: {train_df['date'].min()} 〜 {train_df['date'].max()} ({len(train_df)}行)")
    print(f"検証データ: {val_df['date'].min()} 〜 {val_df['date'].max()} ({len(val_df)}行)")
    print(f"テストデータ: {test_df['date'].min()} 〜 {test_df['date'].max()} ({len(test_df)}行)")
    print(f"エンバーゴ: 学習<{train_cutoff} / 検証<{val_cutoff} (各境界 {LABEL_LOOKAHEAD_DAYS}営業日を除外)")

    X_train, y_train = train_df[feature_columns], train_df["label"]
    X_val, y_val = val_df[feature_columns], val_df["label"]
    X_test, y_test = test_df[feature_columns], test_df["label"]

    # 直近データを重視するサンプル重み(指数減衰)。地合いの変化に追従しやすくする。
    # クラス不均衡補正(balanced)に、新しいデータほど大きい係数を掛け合わせる。
    train_age_days = (
        pd.to_datetime(train_df["date"].max()) - pd.to_datetime(train_df["date"])
    ).dt.days.to_numpy()
    recency_weight = 0.5 ** (train_age_days / RECENCY_HALFLIFE_DAYS)
    sample_weight = compute_sample_weight(class_weight="balanced", y=y_train) * recency_weight
    print(f"直近重み付け: 半減期{RECENCY_HALFLIFE_DAYS}日 / 最古データ重み {recency_weight.min():.3f}")

    # 特徴量選択: 寄与の小さい特徴量を除外して過学習・ノイズを減らす(trainのみで選定)。
    # 買わないフィルターは元の全特徴量を参照するため、モデルが使う列だけを絞る。
    all_feature_columns = feature_columns
    if os.getenv("SELECT_FEATURES", "1") != "0":
        feature_columns = select_features(X_train, y_train, feature_columns, sample_weight)
        print(f"特徴量選択: {len(all_feature_columns)} -> {len(feature_columns)} 列を採用")
        X_train = train_df[feature_columns]
        X_val = val_df[feature_columns]
        X_test = test_df[feature_columns]

    # Optunaの各試行で変わるのはモデルだけ。買わないフィルターと相場別しきい値調整は
    # 特徴量だけで決まりモデルに依存しないため、ここで一度だけ計算して試行内の再計算を避ける。
    # (以前は試行ごとに行単位のpandas処理を繰り返し、再学習が極端に遅くなっていた)
    # フィルターは元の全特徴量を参照するため、選択後のX_valではなく全列のval_dfを使う。
    val_future = val_df["future_excess_return"].to_numpy()
    val_blocked = val_df.apply(is_ml_buy_blocked, axis=1).to_numpy(dtype=bool)
    val_adj_thresholds = np.array(
        [adjusted_ml_buy_threshold(DEFAULT_ML_BUY_THRESHOLD, row) for _, row in val_df.iterrows()]
    )
    cal_percentiles = np.linspace(0, 100, 21)

    def trial_params(trial: optuna.Trial) -> tuple[dict, dict, dict]:
        """Optuna試行からRF/GB/LGBMのパラメータ辞書を作る(build_voting_modelに渡す形)"""
        rf_params = {
            "n_estimators": trial.suggest_int("rf_n_estimators", 80, 200),
            "max_depth": trial.suggest_int("rf_max_depth", 3, 7),
            "min_samples_leaf": trial.suggest_int("rf_min_samples_leaf", 10, 50),
        }
        gb_params = {
            "n_estimators": trial.suggest_int("gb_n_estimators", 50, 150),
            "max_depth": trial.suggest_int("gb_max_depth", 2, 4),
            "min_samples_leaf": trial.suggest_int("gb_min_samples_leaf", 10, 50),
            "learning_rate": trial.suggest_float("gb_learning_rate", 0.02, 0.2, log=True),
        }
        lgbm_params = {
            "n_estimators": trial.suggest_int("lgbm_n_estimators", 100, 300),
            "max_depth": trial.suggest_int("lgbm_max_depth", 3, 7),
            "min_child_samples": trial.suggest_int("lgbm_min_child_samples", 10, 50),
            "learning_rate": trial.suggest_float("lgbm_learning_rate", 0.02, 0.2, log=True),
            "num_leaves": trial.suggest_int("lgbm_num_leaves", 15, 48),
        }
        return rf_params, gb_params, lgbm_params

    def objective(trial: optuna.Trial) -> float:
        """検証データのコスト控除後平均リターン(買いシグナル時)を最大化するパラメータを探索。
        モデル非依存の前計算(val_blocked / val_adj_thresholds)を使い高速に評価する。
        実行時間を抑えるため試行は先頭シードのみで学習する(最終モデルは全シードで平均)。"""
        rf_params, gb_params, lgbm_params = trial_params(trial)
        m = build_voting_model(rf_params, gb_params, lgbm_params, seeds=ENSEMBLE_SEEDS[:1])
        m.fit(X_train, y_train, sample_weight=sample_weight)

        # 学習データの予測確率分布で較正し、検証スコアを0〜1へ変換(calibrate_scoresと同等処理)
        cal_tmp = np.percentile(m.predict_proba(X_train)[:, 1], cal_percentiles)
        val_scores = np.interp(m.predict_proba(X_val)[:, 1], cal_tmp, cal_percentiles / 100)

        mask = (val_scores >= val_adj_thresholds) & ~val_blocked
        selected = val_future[mask]
        if selected.size == 0:
            return float("-inf")
        # evaluate_threshold と同じ目的関数(コスト控除後の平均リターン + 勝率/的中率の小ボーナス)
        selected_net = selected - TRANSACTION_COST
        avg_return = float(selected_net.mean())
        win_rate = float((selected_net > 0).mean())
        hit_rate = float((selected_net >= EXCESS_RETURN_TARGET).mean())
        return avg_return + win_rate * 0.005 + hit_rate * 0.005

    print(f"\nOptunaでハイパーパラメータを最適化中 ({OPTUNA_N_TRIALS}試行)...")
    study = optuna.create_study(direction="maximize")
    study.optimize(objective, n_trials=OPTUNA_N_TRIALS, show_progress_bar=False)
    best = study.best_params
    print(f"最良パラメータ: {best}")

    # 最終モデルは全シードで学習し、soft votingで予測確率を平均する(シード平均アンサンブル)
    best_rf_params = {
        "n_estimators": best["rf_n_estimators"],
        "max_depth": best["rf_max_depth"],
        "min_samples_leaf": best["rf_min_samples_leaf"],
    }
    best_gb_params = {
        "n_estimators": best["gb_n_estimators"],
        "max_depth": best["gb_max_depth"],
        "min_samples_leaf": best["gb_min_samples_leaf"],
        "learning_rate": best["gb_learning_rate"],
    }
    best_lgbm_params = {
        "n_estimators": best["lgbm_n_estimators"],
        "max_depth": best["lgbm_max_depth"],
        "min_child_samples": best["lgbm_min_child_samples"],
        "learning_rate": best["lgbm_learning_rate"],
        "num_leaves": best["lgbm_num_leaves"],
    }
    model = build_voting_model(best_rf_params, best_gb_params, best_lgbm_params)
    print(f"シード平均アンサンブル: seeds={ENSEMBLE_SEEDS} / 推定器{len(model.estimators)}本")
    # GradientBoostingはclass_weightを持たないため、sample_weightで不均衡を補正する
    model.fit(X_train, y_train, sample_weight=sample_weight)

    pred = model.predict(X_test)
    print(f"\nテストデータ正解率: {accuracy_score(y_test, pred):.3f}")
    print(classification_report(y_test, pred))

    print("特徴量重要度 (RandomForest / シード平均):")
    rf_importances = np.mean(
        [
            fitted.feature_importances_
            for name, fitted in model.named_estimators_.items()
            if name.startswith("rf_")
        ],
        axis=0,
    )
    for col, importance in sorted(
        zip(feature_columns, rf_importances), key=lambda x: -x[1]
    ):
        print(f"  {col}: {importance:.3f}")

    # predict_probaの出力分布が偏っている(ラベル陽性率が低い)ため、
    # 学習データでの予測確率の分位点を保存し、推論時に0〜1へ較正し直す。
    # これにより「50%」が平均的な銘柄、両端が相対的に強気/弱気な銘柄を表すようになる。
    # (テスト/検証データを混ぜると評価リークになるため学習データのみを使用)
    train_proba = model.predict_proba(X_train)[:, 1]
    calibration_percentiles = np.linspace(0, 100, 21)
    calibration_values = np.percentile(train_proba, calibration_percentiles).tolist()
    print(f"\nスコア較正テーブル(0/25/50/75/100%点): "
          f"{calibration_values[0]:.3f} / {calibration_values[5]:.3f} / "
          f"{calibration_values[10]:.3f} / {calibration_values[15]:.3f} / {calibration_values[-1]:.3f}")

    # しきい値の最適化は検証データで行い、テストデータは最終評価専用にする。
    # モデルのスコアは選択後の特徴量で算出し、フィルター判定は全特徴量のval_df/test_dfを渡す。
    val_raw_proba = model.predict_proba(val_df[feature_columns])[:, 1]
    val_scores = calibrate_scores(val_raw_proba, calibration_values)
    ml_buy_threshold, threshold_results = optimize_ml_buy_threshold(
        val_scores,
        val_df["future_excess_return"].to_numpy(),
        val_df,
        dates=val_df["date"],
    )
    sector_ml_buy_thresholds, sector_threshold_results = optimize_sector_thresholds(
        ml_buy_threshold,
        val_scores,
        val_df["future_excess_return"].to_numpy(),
        val_df,
        val_df["sector_label"],
        dates=val_df["date"],
    )
    val_disagreements = ensemble_disagreement(model, val_df[feature_columns])
    max_ensemble_disagreement, disagreement_results = optimize_ensemble_disagreement(
        val_scores,
        val_disagreements,
        val_df["future_excess_return"].to_numpy(),
        ml_buy_threshold,
        val_df,
        val_df["sector_label"],
        sector_ml_buy_thresholds,
        val_df["date"],
        MAX_DAILY_ML_BUY_CANDIDATES,
    )

    # テストデータ(完全に未使用のデータ)でしきい値の最終評価を行う
    test_raw_proba = model.predict_proba(test_df[feature_columns])[:, 1]
    test_scores = calibrate_scores(test_raw_proba, calibration_values)
    test_disagreements = ensemble_disagreement(model, test_df[feature_columns])
    test_eval = evaluate_threshold(
        test_scores,
        test_df["future_excess_return"].to_numpy(),
        ml_buy_threshold,
        test_df,
        test_df["sector_label"],
        sector_ml_buy_thresholds,
        dates=test_df["date"],
        max_daily_candidates=MAX_DAILY_ML_BUY_CANDIDATES,
        disagreements=test_disagreements,
        max_ensemble_disagreement=max_ensemble_disagreement,
    )

    previous_eval = None
    previous_eval_error = None
    if previous_bundle is not None:
        previous_eval, previous_eval_error = evaluate_model_bundle(previous_bundle, test_df)
        if previous_eval is not None:
            print(
                "既存モデルの同一テスト期間評価: "
                f"trades={previous_eval['trades']} "
                f"win_rate={previous_eval['win_rate'] * 100:.1f}% "
                f"avg_return={previous_eval['avg_return'] * 100:.2f}% "
                f"objective={previous_eval['objective']:.4f}"
            )
        else:
            print(f"既存モデル比較をスキップ: {previous_eval_error}")

    promote, promotion_reason = should_promote_candidate(test_eval, previous_eval)
    print(f"モデル昇格判定: {'昇格' if promote else '見送り'} — {promotion_reason}")
    print(
        f"\nテストデータでの最終評価(市場・業種に対する超過リターン、日次上位{MAX_DAILY_ML_BUY_CANDIDATES}件、"
        f"共通しきい値{ml_buy_threshold:.2f}+業種別調整、"
        f"往復コスト{TRANSACTION_COST * 100:.1f}%控除後): "
        f"trades={test_eval['trades']} win_rate={test_eval['win_rate'] * 100:.1f}% "
        f"avg_return={test_eval['avg_return'] * 100:.2f}% total_return={test_eval['total_return'] * 100:.1f}%"
    )
    print(f"\n買い判定しきい値のバックテスト(往復コスト{TRANSACTION_COST * 100:.1f}%控除後):")
    print(f"{'threshold':>10} {'trades':>7} {'win_rate':>9} {'hit_rate':>9} {'avg_return':>11} {'total_return':>13}")
    for result in threshold_results:
        print(
            f"{result['threshold']:>10.2f} {result['trades']:>7} "
            f"{result['win_rate'] * 100:>8.1f}% {result['hit_rate'] * 100:>8.1f}% "
            f"{result['avg_return'] * 100:>10.2f}% {result['total_return'] * 100:>12.1f}%"
        )
    print(f"採用するML買いしきい値: {ml_buy_threshold:.2f}")
    print(
        "採用するアンサンブル不一致上限: "
        + (f"{max_ensemble_disagreement:.3f}" if max_ensemble_disagreement is not None else "なし")
    )
    chosen = next((r for r in threshold_results if r["threshold"] == ml_buy_threshold), None)
    if chosen and chosen.get("sub_periods"):
        print("採用しきい値のサブ期間別成績(安定性チェック):")
        for sp in chosen["sub_periods"]:
            print(
                f"  {sp['start']}〜{sp['end']}: trades={sp['trades']} "
                f"avg_return={sp['avg_return'] * 100:.2f}%"
            )
        if chosen.get("stability_objective") is not None:
            print(f"  stability_objective={chosen['stability_objective']:.4f}")
    if sector_ml_buy_thresholds:
        print("採用する業種別ML買いしきい値:")
        for sector, threshold in sorted(sector_ml_buy_thresholds.items()):
            print(f"  {sector}: {threshold:.2f}")
    else:
        print("採用する業種別ML買いしきい値: なし(全業種で共通しきい値を使用)")

    candidate_bundle = {
            "model": model,
            "features": feature_columns,
            "sector_columns": sector_columns,
            "feature_version": "candlestick_features_v1",
            "score_calibration": calibration_values,
            "ml_buy_threshold": ml_buy_threshold,
            "sector_ml_buy_thresholds": sector_ml_buy_thresholds,
            "threshold_results": threshold_results,
            "sector_threshold_results": sector_threshold_results,
            "ensemble_disagreement": {
                "max": max_ensemble_disagreement,
                "grid": ENSEMBLE_DISAGREEMENT_GRID,
                "results": disagreement_results,
                "metric": "validation_net_excess_return_objective",
            },
            "threshold_optimization": {
                "horizon_days": HORIZON_DAYS,
                "label_lookahead_days": LABEL_LOOKAHEAD_DAYS,
                "target_return": TARGET_RETURN,
                "excess_return_target": EXCESS_RETURN_TARGET,
                "grid": THRESHOLD_GRID,
                "transaction_cost": TRANSACTION_COST,
                "stability_splits": THRESHOLD_STABILITY_SPLITS,
                "stability_std_penalty": THRESHOLD_STABILITY_STD_PENALTY,
                "metric": "stable_val_net_avg_return_with_win_hit_bonus_dynamic_market_filters",
            },
            "training_config": {
                "embargo_days": LABEL_LOOKAHEAD_DAYS,
                "recency_halflife_days": RECENCY_HALFLIFE_DAYS,
                "transaction_cost": TRANSACTION_COST,
                "ensemble_seeds": ENSEMBLE_SEEDS,
                "train_history_period": TRAIN_HISTORY_PERIOD,
                "breadth_feature_count": len(BREADTH_FEATURE_COLUMNS),
                "selected_feature_count": len(feature_columns),
                "total_feature_count": len(all_feature_columns),
                "max_daily_ml_buy_candidates": MAX_DAILY_ML_BUY_CANDIDATES,
                "market_data_alignment": "us_fx_next_jp_business_day",
            },
            "optuna_best_params": best,
            "optuna_best_value": study.best_value,
            "training_end_date": str(pd.to_datetime(train_df["date"].max()).date()),
            "promotion": {
                "promoted": promote,
                "reason": promotion_reason,
                "candidate_test_eval": test_eval,
                "baseline_test_eval": previous_eval,
                "baseline_comparison_error": previous_eval_error,
            },
        }
    if promote:
        joblib.dump(candidate_bundle, MODEL_PATH)
        print(f"\n候補モデルを {MODEL_PATH} に保存しました")
    else:
        print("\n既存モデルを維持しました。候補モデルは保存しません。")


if __name__ == "__main__":
    main()

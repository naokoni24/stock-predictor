"""
毎朝実行するバッチ:
1. 主力銘柄(TICKERS) + Yahooファイナンスのスクリーニング結果(値上がり率/出来高 上位、日本株)を対象に
2. 株価をyfinanceで取得
3. テクニカル指標(SMA25/75, RSI14, MACD, ボリンジャーバンド)を計算
4. シグナル(おすすめ/売り時候補)を判定
5. Supabaseに保存

スクリーニングを使うことで、中小型株も含めて毎日対象が動的に変わる。
取得銘柄数は数十〜100程度に抑え、無料枠の範囲で運用できるようにしている。

実行: python scripts/fetch_and_signal.py
必要な環境変数: SUPABASE_URL, SUPABASE_SERVICE_KEY
"""

import hashlib
import math
import os
import signal
from collections import OrderedDict
from datetime import datetime, timedelta, timezone

import joblib
import jpholiday
import numpy as np
import pandas as pd
import yfinance as yf
from yfinance.screener.query import EquityQuery
from supabase import create_client

MODEL_PATH = os.path.join(os.path.dirname(__file__), "model.pkl")

# モデルに最適化済みしきい値がない場合の後方互換用デフォルト値
ML_BUY_THRESHOLD = 0.55

# 無料枠で毎日安定運用するため、重い株価取得・指標計算の対象数を制限する
MAX_DAILY_TICKERS = 150
SCREENER_SIZE = 50
PREVIOUS_SIGNAL_LIMIT = 50

# prices/signalsのupsertをまとめて送る際の1リクエストあたりの最大行数
UPSERT_CHUNK_SIZE = 500

# 東証の取引終了時刻(JST)。この時刻より前にバッチが実行された場合、
# yfinanceが返す当日分のデータは取引時間中の暫定値(未確定の終値)であり
# 実際の当日終値とは一致しないため、当日分を除外して前営業日までのデータを使う。
MARKET_CLOSE_HOUR_JST = 15

# 通常更新で終値が欠損した場合に、夕方の再取得対象として優先する固定銘柄。
# TICKERS全件を検証対象にすると、取引停止など一部銘柄の個別事情で日次バッチ全体を
# 不必要に失敗させうるため、流動性が高い代表4銘柄に限定する。
CLOSE_VALIDATION_TICKERS = ("7203.T", "6758.T", "9984.T", "8306.T")


def upsert_in_chunks(table, rows, *, on_conflict=None):
    """大量行を複数リクエストに分けてupsertし、銘柄ごとの個別リクエストを避ける"""
    for i in range(0, len(rows), UPSERT_CHUNK_SIZE):
        chunk = rows[i : i + UPSERT_CHUNK_SIZE]
        query = table.upsert(chunk, on_conflict=on_conflict) if on_conflict else table.upsert(chunk)
        query.execute()


def upsert_signals_with_schema_fallback(sb, rows: list[dict]):
    """説明用カラムのSQL未適用時も、日次バッチ全体を止めずに旧形式で保存する。"""
    try:
        upsert_in_chunks(sb.table("signals"), rows, on_conflict="ticker,date")
    except Exception as exc:
        message = str(exc)
        explanation_columns = ("ml_threshold", "ml_block_reasons", "model_version")
        if not any(column in message for column in explanation_columns):
            raise
        print(
            "AI判定根拠カラムが未追加のため旧形式で保存します。"
            "Supabase SQL Editorでsupabase/policies_add_ml_explanations.sqlを実行してください。"
        )
        legacy_rows = [
            {key: value for key, value in row.items() if key not in explanation_columns}
            for row in rows
        ]
        upsert_in_chunks(sb.table("signals"), legacy_rows, on_conflict="ticker,date")


def load_ml_model():
    """学習済みモデルを読み込む。存在しない場合はNoneを返す(ML推論をスキップ)"""
    try:
        return joblib.load(MODEL_PATH)
    except FileNotFoundError:
        print("model.pkl not found, skip ML prediction")
        return None


def get_model_version(model_bundle) -> str | None:
    """保存済みモデルの内容を識別する短いバージョン文字列を返す。"""
    if model_bundle is None:
        return None
    try:
        with open(MODEL_PATH, "rb") as model_file:
            digest = hashlib.sha256(model_file.read()).hexdigest()[:12]
    except OSError:
        return None
    feature_version = str(model_bundle.get("feature_version", "unknown"))
    return f"{feature_version}@{digest}"


# ニュースセンチメントによるスコア補正の重み(±この割合だけml_scoreを増減)
NEWS_SENTIMENT_WEIGHT = 0.05


def get_news_sentiment(sb, tickers: list[str], days: int = 7) -> dict[str, float]:
    """直近N日分のニュースから銘柄ごとの平均センチメントスコアを取得"""
    if not tickers:
        return {}

    since = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
    res = (
        sb.table("news")
        .select("ticker, sentiment_score")
        .in_("ticker", tickers)
        .gte("published_at", since)
        .execute()
    )

    scores: dict[str, list[float]] = {}
    for row in res.data or []:
        if row["sentiment_score"] is None:
            continue
        scores.setdefault(row["ticker"], []).append(row["sentiment_score"])

    return {ticker: sum(values) / len(values) for ticker, values in scores.items()}


def predict_ml(
    model_bundle,
    hist,
    nikkei,
    sector=None,
    feature_df=None,
    news_sentiment: float = 0.0,
) -> tuple[str | None, float | None, float | None, list[str] | None]:
    """株価履歴からML予測と、判定に使ったしきい値・見送り理由を計算する。"""
    if model_bundle is None:
        return None, None, None, None

    from train_model import (
        adjusted_ml_buy_threshold,
        build_features,
        ensemble_disagreement,
        ml_buy_block_reasons,
        regime_adjusted_base_threshold,
        sector_base_threshold,
    )

    df = feature_df if feature_df is not None else build_features(hist, nikkei)
    row = df.iloc[-1].copy()

    # 業種one-hot特徴量を学習時と同じ形式で構築
    for col in model_bundle.get("sector_columns", []):
        row[col] = 1 if col == f"sector_{sector}" else 0

    feature_values = row[model_bundle["features"]]
    if feature_values.isna().any() or not np.isfinite(feature_values.to_numpy(dtype=float)).all():
        return None, None, None, None

    features = pd.DataFrame([row[model_bundle["features"]]])

    raw_score = float(model_bundle["model"].predict_proba(features)[0, 1])
    disagreement = float(ensemble_disagreement(model_bundle["model"], features)[0])

    # 学習データ全体での予測確率の分布が偏っているため、分位点テーブルで0〜1に較正する。
    # 50%が「平均的な銘柄」、両端が相対的に強気/弱気な銘柄を表す。
    calibration = model_bundle.get("score_calibration")
    if calibration:
        percentiles = [p / 100 for p in range(0, 101, 5)]
        score = float(np.interp(raw_score, calibration, percentiles))
    else:
        score = raw_score

    # 新モデルは時系列ニュース特徴量を直接学習する。旧モデルだけは従来の
    # 単発7日平均による補正を残し、再学習・昇格までの挙動を変えない。
    if not any(column.startswith("news_") for column in model_bundle["features"]):
        score = score + news_sentiment * NEWS_SENTIMENT_WEIGHT
    score = min(max(score, 0.0), 1.0)
    base_threshold = sector_base_threshold(
        float(model_bundle.get("ml_buy_threshold", ML_BUY_THRESHOLD)),
        model_bundle.get("sector_ml_buy_thresholds"),
        sector,
    )
    threshold = adjusted_ml_buy_threshold(
        regime_adjusted_base_threshold(
            base_threshold,
            row,
            model_bundle.get("market_regime_thresholds", {}).get("offsets", {}),
        ),
        row,
    )
    block_reasons = ml_buy_block_reasons(row)
    max_disagreement = model_bundle.get("ensemble_disagreement", {}).get("max")
    if max_disagreement is not None and disagreement > float(max_disagreement):
        block_reasons.append(
            f"アンサンブル不一致が大きい ({disagreement:.3f} > {float(max_disagreement):.3f})"
        )
    if score < threshold:
        block_reasons.insert(0, "AI相対スコアが買いしきい値未満")
    signal = "buy_candidate" if score >= threshold and not block_reasons else "hold"
    if block_reasons:
        print(f"ML buy blocked: reasons={','.join(block_reasons)} score={score:.4f} threshold={threshold:.2f}")
    return signal, round(score, 4), round(threshold, 4), block_reasons


def limit_ml_buy_candidates(signal_rows: list[dict], max_candidates: int) -> int:
    """ML買い候補を超過リターンスコア順で上位件数に絞り、除外数を返す。"""
    if max_candidates <= 0:
        return 0
    candidates = sorted(
        (
            (index, row)
            for index, row in enumerate(signal_rows)
            if row["ml_signal"] == "buy_candidate" and row["ml_score"] is not None
        ),
        key=lambda item: (-item[1]["ml_score"], item[1]["ticker"]),
    )
    for index, _ in candidates[max_candidates:]:
        signal_rows[index]["ml_signal"] = "hold"
        reasons = signal_rows[index].get("ml_block_reasons") or []
        reasons.append(f"日次AI買い候補の上位{max_candidates}件を超過")
        signal_rows[index]["ml_block_reasons"] = reasons
    return max(0, len(candidates) - max_candidates)

# 対象銘柄(ティッカー: 名称)。必要に応じて追加・holdingsテーブルと連動させる
TICKERS = {
    "7203.T": "トヨタ自動車",
    "6758.T": "ソニーグループ",
    "9984.T": "ソフトバンクグループ",
    "8306.T": "三菱UFJフィナンシャル・グループ",
    "9432.T": "日本電信電話",
    "6861.T": "キーエンス",
    "9433.T": "KDDI",
    "8035.T": "東京エレクトロン",
    "6098.T": "リクルートホールディングス",
    "4063.T": "信越化学工業",
    "6501.T": "日立製作所",
    "7974.T": "任天堂",
    "8316.T": "三井住友フィナンシャルグループ",
    "4502.T": "武田薬品工業",
    "6594.T": "ニデック",
    "9983.T": "ファーストリテイリング",
    "8001.T": "伊藤忠商事",
    "7267.T": "本田技研工業",
    "6902.T": "デンソー",
    "4661.T": "オリエンタルランド",
    "285A.T": "キオクシアホールディングス",
    # IT・AI関連
    "4689.T": "LINEヤフー",
    "4755.T": "楽天グループ",
    "4385.T": "メルカリ",
    "3659.T": "ネクソン",
    # エネルギー関連
    "5020.T": "ENEOSホールディングス",
    "1605.T": "INPEX",
    "9501.T": "東京電力ホールディングス",
    "9531.T": "東京瓦斯",
    # 半導体関連
    "6920.T": "レーザーテック",
    "6857.T": "アドバンテスト",
    "6723.T": "ルネサスエレクトロニクス",
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


def calc_adx(high: pd.Series, low: pd.Series, close: pd.Series, period: int = 14) -> tuple[pd.Series, pd.Series]:
    """ADX(トレンド強度 0〜100)とDI差分(正=上昇トレンド)を返す"""
    prev_high = high.shift(1)
    prev_low = low.shift(1)
    prev_close = close.shift(1)
    up_move = high - prev_high
    down_move = prev_low - low
    dm_plus = up_move.where((up_move > down_move) & (up_move > 0), 0.0)
    dm_minus = down_move.where((down_move > up_move) & (down_move > 0), 0.0)
    tr = pd.concat([
        high - low,
        (high - prev_close).abs(),
        (low - prev_close).abs(),
    ], axis=1).max(axis=1)
    smoothed_tr = tr.ewm(span=period, adjust=False).mean()
    di_plus = 100 * dm_plus.ewm(span=period, adjust=False).mean() / smoothed_tr
    di_minus = 100 * dm_minus.ewm(span=period, adjust=False).mean() / smoothed_tr
    dx = 100 * (di_plus - di_minus).abs() / (di_plus + di_minus).replace(0, np.nan)
    adx = dx.ewm(span=period, adjust=False).mean()
    return adx, di_plus - di_minus


# 決算前後N日は誤シグナルを避けるためML買いをブロックする
EARNINGS_BLOCK_DAYS_BEFORE = 5
EARNINGS_BLOCK_DAYS_AFTER = 2


def get_next_earnings_date(ticker: str, as_of_date=None):
    """決算ブロック期間に入った直近/次回の決算日を返す。取得できない場合はNone。"""
    try:
        dates = yf.Ticker(ticker).earnings_dates
        if dates is None or dates.empty:
            return None
        as_of_date = as_of_date or datetime.now(timezone.utc).date()
        # 決算直後もEARNINGS_BLOCK_DAYS_AFTER日間は見送るため、過去側の猶予も検索する。
        earliest_relevant = as_of_date - timedelta(days=EARNINGS_BLOCK_DAYS_AFTER)
        future = [d.date() for d in dates.index if d.date() >= earliest_relevant]
        return min(future) if future else None
    except Exception:
        return None


# JPXは2026年までに一覧の配布形式を.xlsから.xlsxへ変更しており、旧URLは404を返す。
# 取得に失敗しても例外を握り潰して空マップを返す作りだったため、業種・銘柄名の更新が
# 静かに止まったまま長期間気付かれなかった。URL変更時は必ずログの警告で気付けるようにする。
JPX_LIST_URL = "https://www.jpx.co.jp/markets/statistics-equities/misc/tvdivq0000001vg2-att/data_j.xlsx"
# ETF・REITなど33業種区分を持たない銘柄は "-" で配布される。業種なしとして扱う。
PLACEHOLDER_SECTORS = {"", "-", "nan", "none", "None"}


def normalize_sector(value) -> str | None:
    """業種の空値・プレースホルダーをNoneに統一する。"""
    if value is None:
        return None
    text = str(value).strip()
    return None if text in PLACEHOLDER_SECTORS else text


def get_jpx_maps() -> tuple[dict[str, str], dict[str, str]]:
    """JPX上場銘柄一覧から銘柄名・業種のマップを取得"""
    try:
        df = pd.read_excel(JPX_LIST_URL)
        name_map = {}
        sector_map = {}
        for _, row in df.iterrows():
            ticker = f"{str(row['コード']).strip()}.T"
            name_map[ticker] = str(row['銘柄名']).strip()
            sector = normalize_sector(row['33業種区分'])
            if sector is not None:
                sector_map[ticker] = sector
        return name_map, sector_map
    except Exception as e:
        print(f"failed to load JPX list: {e}")
        return {}, {}


def get_jp_name_map() -> dict[str, str]:
    """JPX上場銘柄一覧から証券コード→日本語銘柄名のマップを取得"""
    names, _ = get_jpx_maps()
    return names


def get_jp_sector_map() -> dict[str, str]:
    """JPX上場銘柄一覧から証券コード→業種(33業種区分)のマップを取得"""
    _, sectors = get_jpx_maps()
    return sectors


# 銘柄マスタは1回のPostgRESTリクエストで返せる1000行を超えているため、
# 単発クエリだと先頭1000件で静かに切れる。
STOCK_MASTER_PAGE_SIZE = 1000
STOCK_MASTER_MAX_PAGES = 50


def fetch_stock_master(sb) -> dict[str, dict]:
    """銘柄マスタを全件取得してticker->行のマップにする。"""
    rows: dict[str, dict] = {}
    for page in range(STOCK_MASTER_MAX_PAGES):
        offset = page * STOCK_MASTER_PAGE_SIZE
        chunk = (
            sb.table("stocks")
            .select("ticker, name, sector")
            .order("ticker", desc=False)
            .range(offset, offset + STOCK_MASTER_PAGE_SIZE - 1)
            .execute()
            .data
            or []
        )
        rows.update({row["ticker"]: row for row in chunk})
        if len(chunk) < STOCK_MASTER_PAGE_SIZE:
            break
    return rows


def upsert_stock_master(sb, all_tickers: dict[str, str], jp_sectors: dict[str, str], backfill: bool):
    """銘柄マスタを更新し、業種が欠けている既存銘柄をJPX一覧から埋め直す。

    JPX一覧を引けなかった項目は既存値を維持する(ファンダメンタルと同じ方針)。
    以前はJPXのURLが404になったあとも`jp_sectors.get(t)`のNoneをそのまま書いており、
    処理した銘柄の業種が毎日nullで潰され続けていた。業種は実績評価のベンチマーク
    (同業種平均)を決めるため、欠けるとTOPIXへ退避して評価の前提が崩れる。
    """
    existing = fetch_stock_master(sb)
    rows = [
        {
            "ticker": ticker,
            "name": name or existing.get(ticker, {}).get("name") or ticker,
            "sector": jp_sectors.get(ticker) or normalize_sector(existing.get(ticker, {}).get("sector")),
        }
        for ticker, name in all_tickers.items()
    ]

    backfilled = 0
    if backfill and jp_sectors:
        # 当日ユニバース外の銘柄も対象にする。過去に取り込んだまま業種が欠けている
        # 銘柄がシグナルを出すと、その実績が業種ベンチマークで評価されなくなるため。
        for ticker, row in existing.items():
            if ticker in all_tickers or normalize_sector(row.get("sector")) is not None:
                continue
            sector = jp_sectors.get(ticker)
            if sector == row.get("sector"):
                continue
            rows.append({"ticker": ticker, "name": row.get("name") or ticker, "sector": sector})
            backfilled += 1

    upsert_in_chunks(sb.table("stocks"), rows, on_conflict="ticker")
    print(f"stock master upserted: {len(rows)} rows (sector backfilled: {backfilled})")


def get_holdings_tickers(sb) -> dict[str, str]:
    """保有株は必ず日次分析に含める"""
    try:
        res = sb.table("holdings").select("ticker, stocks(name)").execute()
        result = {}
        for row in res.data or []:
            ticker = row.get("ticker")
            if not ticker:
                continue
            stock = row.get("stocks")
            if isinstance(stock, list):
                stock = stock[0] if stock else None
            result[ticker] = (stock or {}).get("name") or ticker
        return result
    except Exception as e:
        print(f"failed to load holdings tickers: {e}")
        return {}


def get_previous_signal_tickers(sb, limit: int = PREVIOUS_SIGNAL_LIMIT) -> dict[str, str]:
    """前回強かった/弱かった銘柄は継続監視する"""
    try:
        res = (
            sb.table("signals")
            .select("ticker, date, signal, stocks(name)")
            .in_("signal", ["buy_candidate", "sell_candidate"])
            .order("date", desc=True)
            .limit(limit * 3)
            .execute()
        )
        result = {}
        for row in res.data or []:
            ticker = row.get("ticker")
            if not ticker or ticker in result:
                continue
            stock = row.get("stocks")
            if isinstance(stock, list):
                stock = stock[0] if stock else None
            result[ticker] = (stock or {}).get("name") or ticker
            if len(result) >= limit:
                break
        return result
    except Exception as e:
        print(f"failed to load previous signal tickers: {e}")
        return {}


def add_candidates(target: OrderedDict[str, str], candidates: dict[str, str], names: dict[str, str], reason: str):
    """優先度順に候補銘柄を追加する。既存候補は上書きしない"""
    before = len(target)
    for ticker, name in candidates.items():
        if len(target) >= MAX_DAILY_TICKERS:
            break
        if ticker not in target:
            target[ticker] = names.get(ticker, name or ticker)
    print(f"{reason}: added {len(target) - before}, total {len(target)}")


def select_daily_tickers(sb, jp_names: dict[str, str]) -> dict[str, str]:
    """広い候補群から、無料枠で毎日処理できる銘柄だけを優先度順に選ぶ"""
    selected: OrderedDict[str, str] = OrderedDict()

    add_candidates(selected, TICKERS, jp_names, "fixed tickers")
    add_candidates(selected, get_holdings_tickers(sb), jp_names, "holdings")

    previous_signal_tickers = get_previous_signal_tickers(sb)
    add_candidates(selected, previous_signal_tickers, jp_names, "previous signals")

    screener_tickers = get_screener_tickers(size=SCREENER_SIZE)
    print(f"screener found {len(screener_tickers)} tickers")
    add_candidates(selected, screener_tickers, jp_names, "screener")

    # 優先候補で上限に満たない日は、JPX上場銘柄一覧から補充して探索範囲を広げる
    add_candidates(selected, jp_names, jp_names, "jpx fallback")

    return dict(selected)


def get_market_cutoff(now_jst: datetime):
    """今回保存してよい市場日と、取引終了後かどうかを返す。"""
    after_market_close = now_jst.hour >= MARKET_CLOSE_HOUR_JST
    cutoff_date = now_jst.date()
    if not after_market_close:
        cutoff_date -= timedelta(days=1)
    return cutoff_date, after_market_close


def is_jpx_trading_day(target_date) -> bool:
    """JPXの通常休場日を除いて、終値が存在するはずの日かを判定する。"""
    year_end_new_year = (target_date.month == 12 and target_date.day == 31) or (
        target_date.month == 1 and target_date.day <= 3
    )
    return target_date.weekday() < 5 and not jpholiday.is_holiday(target_date) and not year_end_new_year


def select_repair_tickers(sb, jp_names: dict[str, str], target_date) -> dict[str, str]:
    """夕方の再取得では、当日終値が欠損・未更新の優先銘柄だけを対象にする。"""
    try:
        rows = (
            sb.table("prices")
            .select("ticker, close")
            .eq("date", target_date.isoformat())
            .execute()
            .data
            or []
        )
    except Exception as exc:
        # 読み取り失敗時に再取得そのものを止めない。優先銘柄を再取得する。
        print(f"failed to inspect missing prices for repair: {exc}")
        rows = []

    valid_tickers = {row["ticker"] for row in rows if row.get("close") is not None}
    null_tickers = {row["ticker"] for row in rows if row.get("close") is None}
    candidates: OrderedDict[str, str] = OrderedDict()
    add_candidates(candidates, TICKERS, jp_names, "repair fixed tickers")
    add_candidates(candidates, get_holdings_tickers(sb), jp_names, "repair holdings")
    add_candidates(candidates, get_previous_signal_tickers(sb), jp_names, "repair previous signals")
    add_candidates(
        candidates,
        {ticker: jp_names.get(ticker, ticker) for ticker in sorted(null_tickers)},
        jp_names,
        "repair null-price tickers",
    )

    repair_tickers = {
        ticker: name for ticker, name in candidates.items() if ticker not in valid_tickers
    }
    print(
        f"repair target: {len(repair_tickers)} "
        f"(valid={len(valid_tickers)}, null={len(null_tickers)}, date={target_date.isoformat()})"
    )
    return repair_tickers


def get_screener_tickers(size: int = 50) -> dict[str, str]:
    """Yahooファイナンスのスクリーニング(値上がり率/出来高 上位、日本株)から銘柄を取得"""
    queries = {
        "gainers": EquityQuery(
            "and", [EquityQuery("eq", ["region", "jp"]), EquityQuery("gt", ["intradaypricechange", 0])]
        ),
        "losers": EquityQuery(
            "and", [EquityQuery("eq", ["region", "jp"]), EquityQuery("lt", ["intradaypricechange", 0])]
        ),
    }

    result: dict[str, str] = {}
    for name, query in queries.items():
        try:
            sort_field = "percentchange"
            res = yf.screen(query, sortField=sort_field, sortAsc=(name == "losers"), size=size)
            for item in res.get("quotes", []):
                symbol = item.get("symbol")
                if not symbol:
                    continue
                result[symbol] = item.get("shortName") or item.get("longName") or symbol
        except Exception as e:
            print(f"screener {name} failed: {e}")

    return result


FUNDAMENTALS_TIMEOUT_SEC = 8


def get_fundamentals(yf_ticker: yf.Ticker) -> dict:
    """PER/PBR/アナリスト目標株価/予想EPSを取得(取得できない・タイムアウト時はNone)"""
    empty = {"per": None, "pbr": None, "target_price": None, "forecast_eps": None}

    def handler(signum, frame):
        raise TimeoutError()

    old_handler = signal.signal(signal.SIGALRM, handler)
    signal.alarm(FUNDAMENTALS_TIMEOUT_SEC)
    try:
        info = yf_ticker.info or {}
    except Exception as e:
        print(f"failed to load fundamentals for {yf_ticker.ticker}: {e}")
        return empty
    finally:
        signal.alarm(0)
        signal.signal(signal.SIGALRM, old_handler)

    def clean(value):
        # yfinanceがnanを返すことがあり、そのままだとJSONシリアライズに失敗するため除外
        if isinstance(value, float) and math.isnan(value):
            return None
        return value

    return {
        "per": clean(info.get("trailingPE")),
        "pbr": clean(info.get("priceToBook")),
        "target_price": clean(info.get("targetMeanPrice")),
        "forecast_eps": clean(info.get("forwardEps")),
    }


def make_signal(row) -> tuple[str | None, float]:
    """ルールベースでシグナルとスコアを決定

    スコアは「強気度」を表す符号付きの値。買い候補は正、売り候補は負で、
    絶対値が大きいほどシグナルが強い。トップページは買い候補を降順、売り候補を
    昇順で並べて上位を表示するため、この符号の向きに依存している。

    買い候補: ゴールデンクロス + RSIが過熱でない + MACD陽転 + バンド上限以下
    売り候補: デッドクロス または RSI過熱
    どちらにも該当しない場合は hold。

    注意(2026-08-18修正): 以前は売り判定が買い判定と独立した `if` で、かつ条件に
    MACD陰転・バンド上限超えを含んでいた。元の実装では買い/売りの条件が排他だったが、
    MACD・ボリンジャーバンドを売り条件へ追加した際に排他性が壊れ、買い候補の条件を
    満たす銘柄がMACDのわずかな陰転だけで売り候補へ上書きされていた(しかも買いロジックで
    計算した正のスコアを持ったまま)。MACD陰転・バンド上限超えは「買いから外す」条件として
    扱い、弱気条件に該当しない銘柄は hold にする。
    """
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
    bb_width = row["bb_upper"] - row["bb_lower"]
    bb_position = (row["Close"] - row["bb_lower"]) / bb_width if bb_width > 0 else None

    # ゴールデンクロス気味(短期線が長期線の上)+ RSIが過熱でない
    # + 上昇モメンタムあり + バンド上限を超えていない -> 買い候補
    if (
        row["sma25"] > row["sma75"]
        and row["rsi14"] < 60
        and macd_diff >= 0
        and row["Close"] <= row["bb_upper"]
    ):
        signal = "buy_candidate"
        score += (row["sma25"] / row["sma75"] - 1) * 100
        score += max(0, 50 - row["rsi14"]) * 0.1

        # MACDがシグナルを上回っている(上昇モメンタム)ほど加点
        score += macd_diff * 2

        # ボリンジャーバンド下限近くは押し目買いとして加点
        if bb_position is not None and bb_position < 0.3:
            score += (0.3 - bb_position) * 10

    # デッドクロス気味、またはRSI過熱 -> 売り候補
    elif row["sma25"] < row["sma75"] or row["rsi14"] > 75:
        signal = "sell_candidate"

        # 買い候補と対称に、弱気度を負のスコアで表す(絶対値が大きいほど弱気)。
        # 以前は売り候補のスコアが常に0.0で全件同点だったため、トップページの
        # 売り候補上位10件が事実上ランダムに選ばれていた(2026-08-18修正)。
        if row["sma25"] < row["sma75"]:
            score -= (1 - row["sma25"] / row["sma75"]) * 100
        score -= max(0, row["rsi14"] - 50) * 0.1

        # MACDがシグナルを下回っている(下落モメンタム)ほど減点
        if macd_diff < 0:
            score += macd_diff * 2

        # ボリンジャーバンド上限近くは過熱として減点
        if bb_position is not None and bb_position > 0.7:
            score -= (bb_position - 0.7) * 10

    return signal, round(score, 4)


def main():
    url = os.environ["SUPABASE_URL"]
    key = os.environ["SUPABASE_SERVICE_KEY"]
    sb = create_client(url, key)
    model_bundle = load_ml_model()
    model_version = get_model_version(model_bundle)
    nikkei = None
    if model_bundle is not None:
        from train_model import get_nikkei_returns
        nikkei = get_nikkei_returns()

    now_jst = datetime.now(timezone(timedelta(hours=9)))
    cutoff_date, after_market_close = get_market_cutoff(now_jst)
    jp_names, jp_sectors = get_jpx_maps()
    if not jp_names:
        # 一覧が取れないと業種・日本語銘柄名・JPXからのユニバース補充が同時に劣化する。
        # 標準出力に紛れて見落とされないよう、GitHub Actionsの警告注釈として出す。
        print("::warning::JPX上場銘柄一覧を取得できませんでした。業種・銘柄名の更新をスキップします。")
    repair_only = os.environ.get("REPAIR_MISSING_CLOSES_ONLY") == "1"
    all_tickers = (
        select_repair_tickers(sb, jp_names, cutoff_date)
        if repair_only
        else select_daily_tickers(sb, jp_names)
    )
    run_kind = "repair" if repair_only else "daily"
    print(
        f"{run_kind} analysis target: {len(all_tickers)} / max {MAX_DAILY_TICKERS} "
        f"(cutoff={cutoff_date.isoformat()}, now={now_jst.isoformat()})"
    )
    if not all_tickers:
        print("更新対象の欠損・未更新銘柄はありません。")
        return

    # 銘柄マスタをupsert(当日ユニバース外の業種欠損もJPX一覧から埋め直す)
    upsert_stock_master(sb, all_tickers, jp_sectors, backfill=not repair_only)

    histories = {}
    all_price_rows = []
    close_validation = {}
    for ticker in all_tickers:
        hist = yf.Ticker(ticker).history(period="6mo")
        if hist.empty:
            print(f"skip {ticker}: no data")
            continue

        hist = hist.reset_index()
        hist["date"] = hist["Date"].dt.date

        # yfinanceが当日分の未確定データ(取引時間中の暫定値、寄り付き前の前日値など)を
        # 返すことがあるため、日本時間の本日より先の日付の行は除外する。
        # さらに、東証の取引終了時刻(15:00 JST)より前にバッチが実行された場合は
        # 当日分そのものが未確定(まだ当日終値が確定していない)ため、当日分も除外する。
        # これを怠ると、取引時間中の暫定値が「当日終値」として保存され、
        # ポートフォリオの評価額が実際の当日終値と一致しなくなる。
        hist = hist[hist["date"] <= cutoff_date].reset_index(drop=True)
        if hist.empty:
            print(f"skip {ticker}: no valid data")
            continue

        # 終値が欠損した行をprices/signalsへ保存すると、既存の有効な終値をnullで
        # 上書きしてしまう。欠損行は保存・シグナル計算の両方から除外する。
        # 終値だけ欠損するケースではOHLC全体も不確定であるため、再取得に任せる。
        current_date_rows = hist[hist["date"] == cutoff_date]
        if after_market_close and ticker in CLOSE_VALIDATION_TICKERS and not current_date_rows.empty:
            close_validation[ticker] = current_date_rows["Close"].notna().any()
        missing_close_rows = int(hist["Close"].isna().sum())
        if missing_close_rows:
            print(f"skip {ticker}: {missing_close_rows} row(s) with missing close")
            hist = hist[hist["Close"].notna()].reset_index(drop=True)
        if hist.empty:
            print(f"skip {ticker}: no rows with valid close")
            continue

        hist["sma25"] = hist["Close"].rolling(25).mean()
        hist["sma75"] = hist["Close"].rolling(75).mean()
        hist["rsi14"] = calc_rsi(hist["Close"], 14)
        hist["macd"], hist["macd_signal"] = calc_macd(hist["Close"])
        hist["bb_upper"], hist["bb_lower"] = calc_bollinger(hist["Close"])

        # 価格履歴を保存
        # yfinanceが一部日でNaNを返すことがあり(新規上場銘柄の取引低調日など)、
        # そのままだとJSONシリアライズ(allow_nan=False)に失敗しバッチ全体が
        # 落ちるため、NaNはNoneに変換して保存する(signals/fundamentalsと同じ対処)。
        price_rows = [
            {
                "ticker": ticker,
                "date": r["date"].isoformat(),
                "open": None if pd.isna(r["Open"]) else float(r["Open"]),
                "high": None if pd.isna(r["High"]) else float(r["High"]),
                "low": None if pd.isna(r["Low"]) else float(r["Low"]),
                "close": None if pd.isna(r["Close"]) else float(r["Close"]),
                "volume": None if pd.isna(r["Volume"]) else int(r["Volume"]),
            }
            for _, r in hist.tail(30).iterrows()
        ]
        all_price_rows.extend(price_rows)
        histories[ticker] = hist

    # yfinanceが市場日を返しているのに代表銘柄の終値が欠損している場合は、
    # 「成功」と見せずにジョブを失敗させる。休日は市場日そのものの行が無いため
    # close_validationが空となり、この検証は行わない。
    missing_validation_tickers = [
        ticker for ticker, has_close in close_validation.items() if not has_close
    ]
    if after_market_close and is_jpx_trading_day(cutoff_date):
        # 市場日なのにデータ行自体が無い場合も「未更新」と判定する。
        missing_validation_tickers.extend(
            ticker
            for ticker in CLOSE_VALIDATION_TICKERS
            if ticker not in close_validation and ticker in all_tickers
        )
    missing_validation_tickers = sorted(set(missing_validation_tickers))
    print(
        f"close validation: date={cutoff_date.isoformat()} "
        f"observed={len(close_validation)} missing={len(missing_validation_tickers)}"
    )
    if missing_validation_tickers:
        raise RuntimeError(
            "終値の妥当性検証に失敗しました: "
            f"{', '.join(missing_validation_tickers)} ({cutoff_date.isoformat()})"
        )

    upsert_in_chunks(sb.table("prices"), all_price_rows)

    feature_frames = {}
    if model_bundle is not None and histories:
        from train_model import (
            add_breadth_features,
            add_sector_relative_features,
            build_features,
            load_news_feature_frames,
        )

        history_dates = [pd.to_datetime(hist["Date"]).min() for hist in histories.values()]
        latest_dates = [pd.to_datetime(hist["Date"]).max() for hist in histories.values()]
        news_feature_frames = load_news_feature_frames(
            list(histories),
            min(history_dates),
            max(latest_dates),
            sb=sb,
        )

        feature_frames = {
            ticker: build_features(hist, nikkei, news_feature_frames.get(ticker))
            for ticker, hist in histories.items()
        }
        feature_frames = add_sector_relative_features(feature_frames, jp_sectors)
        # 当日処理対象の全銘柄から市場ブレッドス・銘柄順位を算出(学習時と同じ計算)
        feature_frames = add_breadth_features(feature_frames)

    news_sentiment = get_news_sentiment(sb, list(histories.keys()))

    signal_results = []
    all_signal_rows = []
    for ticker, hist in histories.items():
        # 最新日のシグナルを保存
        latest = hist.iloc[-1]
        market_date = latest["date"]
        signal, score = make_signal(latest)
        ml_signal, ml_score, ml_threshold, ml_block_reasons = predict_ml(
            model_bundle,
            hist,
            nikkei,
            jp_sectors.get(ticker),
            feature_frames.get(ticker),
            news_sentiment.get(ticker, 0.0),
        )

        # 決算前後フィルター: 買い候補のみ決算日を確認してブロック
        if ml_signal == "buy_candidate":
            earnings_date = get_next_earnings_date(ticker, as_of_date=market_date)
            if earnings_date:
                days_to_earnings = (earnings_date - market_date).days
                if -EARNINGS_BLOCK_DAYS_AFTER <= days_to_earnings <= EARNINGS_BLOCK_DAYS_BEFORE:
                    print(f"ML buy blocked: 決算前後 {earnings_date} (D{days_to_earnings:+d}) {ticker}")
                    ml_signal = "hold"
                    ml_block_reasons = (ml_block_reasons or []) + [
                        f"決算前後のため見送り ({earnings_date.isoformat()})"
                    ]

        all_signal_rows.append(
            {
                "ticker": ticker,
                "date": market_date.isoformat(),
                "close": None if pd.isna(latest["Close"]) else float(latest["Close"]),
                "sma25": None if pd.isna(latest["sma25"]) else float(latest["sma25"]),
                "sma75": None if pd.isna(latest["sma75"]) else float(latest["sma75"]),
                "rsi14": None if pd.isna(latest["rsi14"]) else float(latest["rsi14"]),
                "macd": None if pd.isna(latest["macd"]) else float(latest["macd"]),
                "macd_signal": None if pd.isna(latest["macd_signal"]) else float(latest["macd_signal"]),
                "bb_upper": None if pd.isna(latest["bb_upper"]) else float(latest["bb_upper"]),
                "bb_lower": None if pd.isna(latest["bb_lower"]) else float(latest["bb_lower"]),
                "signal": signal,
                "score": score,
                "ml_signal": ml_signal,
                "ml_score": ml_score,
                "ml_threshold": ml_threshold,
                "ml_block_reasons": ml_block_reasons,
                "model_version": model_version,
            }
        )

        print(f"{ticker}: signal={signal} score={score} ml_signal={ml_signal} ml_score={ml_score}")
        signal_results.append({"ticker": ticker, "signal": signal, "score": score})

    # 超過リターンモデルは「市場・業種を上回る候補を相対的に選ぶ」目的のため、
    # 学習時に保存した上限まで、その日のML買い候補をスコア順で絞り込む。
    # 旧モデルには設定がないため、再学習・昇格するまでは従来の件数制限なしで動作する。
    max_ml_candidates = int(
        (model_bundle or {}).get("training_config", {}).get("max_daily_ml_buy_candidates", 0) or 0
    )
    if max_ml_candidates > 0:
        removed = limit_ml_buy_candidates(all_signal_rows, max_ml_candidates)
        if removed:
            print(
                f"ML買い候補を超過リターンスコア上位{max_ml_candidates}件へ絞り込み "
                f"({removed}件を除外)"
            )

    upsert_signals_with_schema_fallback(sb, all_signal_rows)

    update_fundamentals(sb, all_tickers, jp_sectors, signal_results)


# トップページのウォッチリスト(おすすめ)に表示される件数と同じ
WATCHLIST_SIZE = 10


FUNDAMENTAL_FIELDS = ("per", "pbr", "target_price", "forecast_eps")


def update_fundamentals(sb, all_tickers, jp_sectors, signal_results):
    """ウォッチリスト上位(買い/売り候補)+保有株に絞ってPER/PBR等を取得・保存する。
    .info取得は1銘柄あたり追加リクエストが発生し遅い・不安定なため対象を絞り、
    取得できない・タイムアウトした銘柄は既存値を保持する(以前はNoneで上書きしており、
    yfinance .infoの一時的な取得失敗だけで前日まで表示できていたPER/PBR等が
    消えてしまう不具合があった)。"""
    buy_candidates = sorted(
        (r for r in signal_results if r["signal"] == "buy_candidate"),
        key=lambda r: r["score"],
        reverse=True,
    )[:WATCHLIST_SIZE]
    sell_candidates = sorted(
        (r for r in signal_results if r["signal"] == "sell_candidate"),
        key=lambda r: r["score"],
    )[:WATCHLIST_SIZE]

    targets = {r["ticker"] for r in buy_candidates} | {r["ticker"] for r in sell_candidates}
    targets |= set(get_holdings_tickers(sb))

    if not targets:
        return

    existing_res = (
        sb.table("stocks")
        .select("ticker, name, sector, per, pbr, target_price, forecast_eps")
        .in_("ticker", list(targets))
        .execute()
    )
    existing_by_ticker = {row["ticker"]: row for row in existing_res.data or []}

    rows = []
    for ticker in targets:
        values = get_fundamentals(yf.Ticker(ticker))
        existing = existing_by_ticker.get(ticker, {})
        # 今回取得できた項目だけを上書きし、取得失敗(None)の項目は既存値を維持する
        merged = {
            field: values[field] if values[field] is not None else existing.get(field)
            for field in FUNDAMENTAL_FIELDS
        }
        rows.append({
            "ticker": ticker,
            # 銘柄名・業種もJPX一覧を引けなかった場合は既存値を維持する
            # (ここでNoneを書くとupsert_stock_masterで埋めた業種を潰してしまう)。
            "name": all_tickers.get(ticker) or existing.get("name") or ticker,
            "sector": jp_sectors.get(ticker) or normalize_sector(existing.get("sector")),
            **merged,
        })

    sb.table("stocks").upsert(rows, on_conflict="ticker").execute()
    print(f"fundamentals updated for {len(rows)} tickers")


if __name__ == "__main__":
    main()

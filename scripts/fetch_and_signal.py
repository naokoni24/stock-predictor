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

import os
import datetime
import joblib
import pandas as pd
import yfinance as yf
from yfinance.screener.query import EquityQuery
from supabase import create_client

MODEL_PATH = os.path.join(os.path.dirname(__file__), "model.pkl")


def load_ml_model():
    """学習済みモデルを読み込む。存在しない場合はNoneを返す(ML推論をスキップ)"""
    try:
        return joblib.load(MODEL_PATH)
    except FileNotFoundError:
        print("model.pkl not found, skip ML prediction")
        return None


def predict_ml(model_bundle, hist) -> tuple[str | None, float | None]:
    """株価履歴からML予測(ml_signal/ml_score)を計算"""
    if model_bundle is None:
        return None, None

    from train_model import build_features

    df = build_features(hist)
    row = df.iloc[-1]

    if row[model_bundle["features"]].isna().any():
        return None, None

    features = pd.DataFrame([row[model_bundle["features"]]])

    score = float(model_bundle["model"].predict_proba(features)[0, 1])
    signal = "buy_candidate" if score >= 0.5 else "hold"
    return signal, round(score, 4)

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


JPX_LIST_URL = "https://www.jpx.co.jp/markets/statistics-equities/misc/tvdivq0000001vg2-att/data_j.xls"


def get_jp_name_map() -> dict[str, str]:
    """JPX上場銘柄一覧から証券コード→日本語銘柄名のマップを取得"""
    try:
        df = pd.read_excel(JPX_LIST_URL)
        return {
            f"{str(row['コード']).strip()}.T": str(row['銘柄名']).strip()
            for _, row in df.iterrows()
        }
    except Exception as e:
        print(f"failed to load JPX list: {e}")
        return {}


def get_jp_sector_map() -> dict[str, str]:
    """JPX上場銘柄一覧から証券コード→業種(33業種区分)のマップを取得"""
    try:
        df = pd.read_excel(JPX_LIST_URL)
        return {
            f"{str(row['コード']).strip()}.T": str(row['33業種区分']).strip()
            for _, row in df.iterrows()
        }
    except Exception as e:
        print(f"failed to load JPX sector list: {e}")
        return {}


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
    if row["sma25"] > row["sma75"] and row["rsi14"] < 60:
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
        or row["rsi14"] > 75
        or macd_diff < 0
        or row["Close"] > row["bb_upper"]
    ):
        signal = "sell_candidate"

    return signal, round(score, 4)


def main():
    url = os.environ["SUPABASE_URL"]
    key = os.environ["SUPABASE_SERVICE_KEY"]
    sb = create_client(url, key)
    model_bundle = load_ml_model()

    # 主力銘柄 + スクリーニング結果(値上がり/値下がり上位)を結合
    all_tickers = dict(TICKERS)
    screener_tickers = get_screener_tickers()
    print(f"screener found {len(screener_tickers)} tickers")
    jp_names = get_jp_name_map()
    jp_sectors = get_jp_sector_map()
    for t, n in screener_tickers.items():
        all_tickers.setdefault(t, jp_names.get(t, n))

    # 銘柄マスタをupsert
    sb.table("stocks").upsert(
        [
            {"ticker": t, "name": n, "sector": jp_sectors.get(t)}
            for t, n in all_tickers.items()
        ]
    ).execute()

    today = datetime.date.today()

    for ticker in all_tickers:
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
        ml_signal, ml_score = predict_ml(model_bundle, hist)
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
                "ml_signal": ml_signal,
                "ml_score": ml_score,
            }
        ).execute()

        print(f"{ticker}: signal={signal} score={score} ml_signal={ml_signal} ml_score={ml_score}")


if __name__ == "__main__":
    main()

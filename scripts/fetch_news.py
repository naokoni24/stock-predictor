"""
Google News RSS から銘柄ごとのニュースを取得し、
キーワードベースの簡易センチメント分析を付与してSupabaseに保存する。

無料のGoogle News RSS(APIキー不要)を利用するため追加コストなし。

実行: scripts/venv/bin/python scripts/fetch_news.py
必要な環境変数: SUPABASE_URL, SUPABASE_SERVICE_KEY
"""

import os
import time
import xml.etree.ElementTree as ET
from collections import OrderedDict
from datetime import datetime, timezone

import requests
from supabase import create_client

from fetch_and_signal import TICKERS, get_holdings_tickers, get_previous_signal_tickers

NEWS_PER_TICKER = 3
NEWS_MAX_TICKERS = int(os.environ.get("NEWS_MAX_TICKERS", "80"))

# キーワードベースの簡易センチメント辞書
POSITIVE_WORDS = [
    "上方修正", "最高益", "増益", "黒字", "好調", "上昇", "増配", "最高値",
    "急騰", "好決算", "受注拡大", "業績拡大", "増収", "高評価", "買い", "強気",
]
NEGATIVE_WORDS = [
    "下方修正", "減益", "赤字", "不振", "下落", "減配", "最安値", "急落",
    "減収", "リコール", "不正", "売り", "弱気", "減産", "損失", "下振れ",
]


def analyze_sentiment(title: str) -> tuple[str, float]:
    """タイトル中のキーワード出現数からセンチメントを判定"""
    pos = sum(1 for w in POSITIVE_WORDS if w in title)
    neg = sum(1 for w in NEGATIVE_WORDS if w in title)
    score = pos - neg
    if score > 0:
        return "positive", min(score / 3, 1.0)
    if score < 0:
        return "negative", max(score / 3, -1.0)
    return "neutral", 0.0


def fetch_news_for(query: str) -> list[dict]:
    url = "https://news.google.com/rss/search"
    params = {"q": query, "hl": "ja", "gl": "JP", "ceid": "JP:ja"}
    res = requests.get(url, params=params, timeout=15)
    res.raise_for_status()

    root = ET.fromstring(res.content)
    items = []
    for item in root.findall("./channel/item")[:NEWS_PER_TICKER]:
        title = item.findtext("title") or ""
        link = item.findtext("link") or ""
        pub_date = item.findtext("pubDate")
        source = item.findtext("source")

        published_at = None
        if pub_date:
            try:
                published_at = datetime.strptime(
                    pub_date, "%a, %d %b %Y %H:%M:%S %Z"
                ).replace(tzinfo=timezone.utc).isoformat()
            except ValueError:
                pass

        sentiment, sentiment_score = analyze_sentiment(title)
        items.append(
            {
                "title": title,
                "url": link,
                "source": source,
                "published_at": published_at,
                "sentiment": sentiment,
                "sentiment_score": sentiment_score,
            }
        )
    return items


def add_news_targets(target: OrderedDict[str, str], candidates: dict[str, str]) -> None:
    for ticker, name in candidates.items():
        if len(target) >= NEWS_MAX_TICKERS:
            break
        target.setdefault(ticker, name or ticker)


def get_news_targets(sb) -> OrderedDict[str, str]:
    """固定銘柄に加え、保有株と直近シグナル銘柄のニュースも取得する"""
    targets: OrderedDict[str, str] = OrderedDict()
    add_news_targets(targets, TICKERS)
    add_news_targets(targets, get_holdings_tickers(sb))
    add_news_targets(targets, get_previous_signal_tickers(sb, NEWS_MAX_TICKERS))
    return targets


def main():
    url = os.environ["SUPABASE_URL"]
    key = os.environ["SUPABASE_SERVICE_KEY"]
    sb = create_client(url, key)

    targets = get_news_targets(sb)
    print(f"news targets: {len(targets)} / max {NEWS_MAX_TICKERS}")

    rows = []
    for ticker, name in targets.items():
        try:
            news_items = fetch_news_for(name)
        except Exception as e:
            print(f"skip {ticker}: {e}")
            continue

        for item in news_items:
            if not item["url"]:
                continue
            rows.append({"ticker": ticker, **item})

        print(f"{ticker} ({name}): {len(news_items)}件")
        time.sleep(0.5)  # Google Newsへの過度なリクエストを避ける

    if rows:
        sb.table("news").upsert(rows, on_conflict="ticker,url").execute()
        print(f"\n合計 {len(rows)} 件のニュースを保存しました")


if __name__ == "__main__":
    main()

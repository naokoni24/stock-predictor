"""日次取得と実績評価で共有する東証の取引日・取引終了時刻。"""

from datetime import date, datetime, timedelta

import jpholiday

MARKET_CLOSE_HOUR_JST = 15
MARKET_CLOSE_MINUTE_JST = 30


def get_market_cutoff(now_jst: datetime):
    """15:30より前の当日価格は未確定として除外する。"""
    after_market_close = (now_jst.hour, now_jst.minute) >= (
        MARKET_CLOSE_HOUR_JST, MARKET_CLOSE_MINUTE_JST
    )
    cutoff_date = now_jst.date()
    if not after_market_close:
        cutoff_date -= timedelta(days=1)
    return cutoff_date, after_market_close


def is_jpx_trading_day(target_date: date) -> bool:
    """土日、祝日、年末年始の東証休場日を除外する。"""
    year_end_new_year = (target_date.month == 12 and target_date.day == 31) or (
        target_date.month == 1 and target_date.day <= 3
    )
    return target_date.weekday() < 5 and not jpholiday.is_holiday(target_date) and not year_end_new_year


def next_trading_dates(signal_date: str, count: int) -> list[str]:
    """シグナル日の翌取引日からcount日分を返す。価格欠損を休場日と混同しない。"""
    current = date.fromisoformat(signal_date)
    dates = []
    while len(dates) < count:
        current += timedelta(days=1)
        if is_jpx_trading_day(current):
            dates.append(current.isoformat())
    return dates

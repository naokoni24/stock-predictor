"""終値時刻・欠損日・売買判定の回帰テスト。外部サービスへ接続しない。"""

import unittest
from datetime import date, datetime
from unittest.mock import MagicMock, patch

import pandas as pd

from market_calendar import get_market_cutoff, is_jpx_trading_day, next_trading_dates
from evaluate_signal_outcomes import build_outcome_rows, select_dates_to_settle, simulate_trade, tickers_missing_prices, topix_return
from fetch_and_signal import limit_ml_buy_candidates, price_rows_to_save, make_signal, repair_inference_universe, upsert_in_chunks, get_holdings_tickers, get_screener_tickers, get_watchlist_tickers, select_daily_tickers, select_repair_tickers
from train_model import add_breadth_features, bundle_out_of_sample_start, compute_barrier_outcome, should_promote_candidate


class MarketCalendarTests(unittest.TestCase):
    def test_market_close_boundary(self):
        for clock, expected_date, after_close in [
            ("15:00:00", date(2026, 9, 30), False),
            ("15:29:59", date(2026, 9, 30), False),
            ("15:30:00", date(2026, 10, 1), True),
        ]:
            with self.subTest(clock=clock):
                self.assertEqual(get_market_cutoff(datetime.fromisoformat("2026-10-01T" + clock)), (expected_date, after_close))

    def test_holidays_and_new_year(self):
        for day in ["2026-09-22", "2026-09-23", "2026-12-31", "2027-01-01", "2026-09-26"]:
            self.assertFalse(is_jpx_trading_day(date.fromisoformat(day)), day)
        self.assertTrue(is_jpx_trading_day(date(2026, 10, 1)))
        self.assertEqual(next_trading_dates("2026-09-18", 2), ["2026-09-24", "2026-09-25"])


class OutcomeTests(unittest.TestCase):
    signal_date = "2026-09-25"

    def setUp(self):
        self.prices = [
            {"date": day, "open": 100 + i, "low": 99 + i}
            for i, day in enumerate(next_trading_dates(self.signal_date, 7))
        ]

    def test_matches_training_time_exit(self):
        rows = [{"date": self.signal_date, "open": 100, "low": 99}] + self.prices
        frame = pd.DataFrame({"Open": [r["open"] for r in rows], "Low": [r["low"] for r in rows]})
        realized = compute_barrier_outcome(frame)[1].iloc[0]
        actual = simulate_trade(self.prices, self.signal_date)
        self.assertAlmostEqual(actual["gross_return"], realized)
        self.assertEqual(actual["entry_date"], "2026-09-28")
        self.assertEqual(actual["outcome_date"], "2026-10-05")
        self.assertAlmostEqual(topix_return(self.prices, self.signal_date), 0.05)

    def test_missing_trading_day_does_not_extend_horizon(self):
        for index in [0, 2, 5]:
            with self.subTest(index=index):
                gapped = [r for i, r in enumerate(self.prices) if i != index]
                self.assertIsNone(simulate_trade(gapped, self.signal_date))
                self.assertIsNone(topix_return(gapped, self.signal_date))

    def test_null_open_does_not_shift_entry(self):
        self.prices[0]["open"] = None
        self.assertIsNone(simulate_trade(self.prices, self.signal_date))

    def test_gap_stop_and_intraday_stop(self):
        self.prices[1].update(open=90, low=89)
        trade = simulate_trade(self.prices, self.signal_date)
        self.assertEqual(trade["exit_reason"], "stop_gap")
        self.assertAlmostEqual(trade["gross_return"], -0.10)
        self.prices[1].update(open=99, low=90)
        trade = simulate_trade(self.prices, self.signal_date)
        self.assertEqual(trade["exit_reason"], "stop_loss")
        self.assertAlmostEqual(trade["gross_return"], -0.08)

    def test_invalid_low_waits_for_repair(self):
        self.prices[1]["low"] = float("inf")
        self.assertIsNone(simulate_trade(self.prices, self.signal_date))

    def peer_prices(self, ticker, growth):
        """シグナル翌営業日始値100から5営業日後始値100*(1+growth)まで直線的に動く価格。"""
        return [
            {"ticker": ticker, "date": r["date"], "open": 100 * (1 + growth * i / 5), "low": 99 * (1 + growth * i / 5)}
            for i, r in enumerate(self.prices)
        ]

    def test_dates_to_settle(self):
        signals = [{"ticker": "9999.T", "date": "2026-09-25"}, {"ticker": "8888.T", "date": "2026-09-25"},
                   {"ticker": "9999.T", "date": "2026-09-01"}, {"ticker": "9999.T", "date": "2026-09-29"}]
        cutoff = date(2026, 10, 5)
        # 評価期間(9/29シグナルは10/6始値で決済)が終わっていない日は対象外。新しい順に返す。
        self.assertEqual(select_dates_to_settle(signals, set(), cutoff), ["2026-09-25", "2026-09-01"])
        self.assertEqual(select_dates_to_settle(signals, set(), cutoff, max_dates=1), ["2026-09-25"])
        # 一部確定済みの日は、評価期間終了から日が浅い間だけ再試行する。
        partial = {("9999.T", "2026-09-25")}
        self.assertEqual(select_dates_to_settle(signals, partial, cutoff), ["2026-09-25", "2026-09-01"])
        self.assertEqual(select_dates_to_settle(signals, partial, date(2026, 11, 5)), ["2026-09-29", "2026-09-01"])
        settled = {("9999.T", "2026-09-25"), ("8888.T", "2026-09-25"), ("9999.T", "2026-09-01")}
        self.assertEqual(select_dates_to_settle(signals, settled, cutoff), [])

    def test_missing_prices_are_detected_per_signal_date(self):
        rows = self.peer_prices("1111.T", 0.01) + self.peer_prices("2222.T", 0.01)[:3]
        self.assertEqual(
            tickers_missing_prices(rows, {self.signal_date: {"1111.T", "2222.T", "3333.T"}}),
            {"2222.T": self.signal_date, "3333.T": self.signal_date},
        )

    def test_split_step_in_db_window_is_refetched(self):
        normal = self.peer_prices("1111.T", 0.05)
        split = [dict(r) for r in normal]
        for r in split[:2]:
            r.update(open=r["open"] * 5, low=r["low"] * 5)  # 分割前の未調整価格が残った行
        self.assertEqual(
            tickers_missing_prices(normal + [dict(r, ticker="2222.T") for r in split],
                                   {self.signal_date: {"1111.T", "2222.T"}}),
            {"2222.T": self.signal_date},
        )

    def test_benchmark_uses_signal_date_universe_and_clips_outliers(self):
        sectors = {t: "電気機器" for t in ["9999.T", "1111.T", "2222.T", "7777.T"]}
        signals = [{"ticker": "9999.T", "date": self.signal_date}]
        prices = (self.peer_prices("9999.T", 0.05) + self.peer_prices("1111.T", 0.01)
                  + self.peer_prices("2222.T", 0.9) + self.peer_prices("7777.T", 0.5))
        # 7777.Tはシグナル日の分析対象外。後から分析対象に入った急騰銘柄を比較に混ぜない。
        rows = build_outcome_rows(signals, prices, sectors, [], {self.signal_date: {"9999.T", "1111.T", "2222.T"}})
        self.assertEqual(len(rows), 1)
        self.assertAlmostEqual(rows[0]["gross_return"], 0.05)
        # 2222.Tの+90%は学習と同じく+30%で打ち切る: (0.01 + 0.30) / 2
        self.assertAlmostEqual(rows[0]["benchmark_return"], 0.155)

    def test_low_peer_coverage_postpones_settlement(self):
        sectors = {"9999.T": "電気機器", "1111.T": "電気機器", "2222.T": "電気機器"}
        signals = [{"ticker": "9999.T", "date": self.signal_date}]
        prices = self.peer_prices("9999.T", 0.05) + self.peer_prices("1111.T", 0.01) + self.peer_prices("2222.T", 0.02)
        universe = {self.signal_date: {"9999.T", "1111.T", "2222.T"} | {f"{i}.T" for i in range(1000, 1003)}}
        self.assertEqual(build_outcome_rows(signals, prices, sectors, [], universe), [])
        self.assertEqual(len(build_outcome_rows(signals, prices, sectors, [], universe, min_peer_coverage=0.5)), 1)


class SignalTests(unittest.TestCase):
    def test_watchlists_deduplicate_and_limit(self):
        sb = MagicMock()
        sb.table.return_value.select.return_value.order.return_value.order.return_value.limit.return_value.execute.return_value.data = [
            {"ticker": "7203.T", "stocks": [{"name": "トヨタ"}]},
            {"ticker": "7203.T", "stocks": {"name": "重複"}},
        ] + [{"ticker": f"{i}.T", "stocks": None} for i in range(1000, 1040)]
        result = get_watchlist_tickers(sb)
        self.assertEqual(len(result), 30)
        self.assertEqual(result["7203.T"], "トヨタ")

    def test_recent_split_resaves_retained_history(self):
        days = pd.bdate_range("2025-09-01", "2026-10-02").date
        hist = pd.DataFrame({"date": days, "Close": 100.0, "Stock Splits": 0.0})
        cutoff = date(2026, 10, 2)
        self.assertEqual(len(price_rows_to_save(hist, cutoff)), 30)
        hist.loc[hist["date"] == date(2026, 9, 29), "Stock Splits"] = 5.0
        saved = price_rows_to_save(hist, cutoff)
        self.assertEqual(saved["date"].min(), date(2025, 10, 7))
        old_split = hist.assign(**{"Stock Splits": 0.0})
        old_split.loc[old_split["date"] == date(2026, 1, 5), "Stock Splits"] = 2.0
        self.assertEqual(len(price_rows_to_save(old_split, cutoff)), 30)
        self.assertEqual(len(price_rows_to_save(hist.drop(columns=["Stock Splits"]), cutoff)), 30)

    def test_holdings_are_capped_and_validated(self):
        sb = MagicMock()
        sb.table.return_value.select.return_value.order.return_value.limit.return_value.execute.return_value.data = [
            {"ticker": "7203.T", "stocks": {"name": "トヨタ"}}, {"ticker": "7203.T", "stocks": None},
            {"ticker": "BAD", "stocks": None}, {"ticker": "5802@F.T", "stocks": None},
        ] + [{"ticker": f"{i}.T", "stocks": None} for i in range(1000, 1100)]
        result = get_holdings_tickers(sb)
        self.assertEqual(len(result), 50)
        self.assertEqual(list(result)[:2], ["7203.T", "1000.T"])

    def test_watchlists_missing_sql_does_not_stop_daily_batch(self):
        sb = MagicMock()
        sb.table.side_effect = RuntimeError("PGRST205: watchlists missing")
        self.assertEqual(get_watchlist_tickers(sb), {})

    def test_watchlists_priority_and_daily_capacity(self):
        with patch("fetch_and_signal.TICKERS", {"7203.T": "固定"}), \
             patch("fetch_and_signal.get_holdings_tickers", return_value={"6758.T": "保有"}), \
             patch("fetch_and_signal.get_watchlist_tickers", return_value={"9984.T": "監視"}), \
             patch("fetch_and_signal.get_previous_signal_tickers", return_value={"9984.T": "重複"}), \
             patch("fetch_and_signal.get_screener_tickers", return_value={f"{i}.T": str(i) for i in range(1000, 1200)}):
            result = select_daily_tickers(MagicMock(), {})
        self.assertEqual(len(result), 150)
        self.assertEqual(list(result)[:3], ["7203.T", "6758.T", "9984.T"])

    def test_screener_skips_duplicate_regional_listings(self):
        quotes = {"quotes": [{"symbol": s, "shortName": s} for s in ["7203.T", "285A.T", "5802@F.T", "7011@S.T", "AAPL", ""]]}
        with patch("fetch_and_signal.yf.screen", return_value=quotes):
            self.assertEqual(set(get_screener_tickers()), {"7203.T", "285A.T"})

    def test_repair_includes_watchlists(self):
        sb = MagicMock()
        sb.table.return_value.select.return_value.eq.return_value.execute.return_value.data = [
            {"ticker": "7203.T", "close": 3000},
        ]
        with patch("fetch_and_signal.TICKERS", {"7203.T": "固定"}), \
             patch("fetch_and_signal.get_holdings_tickers", return_value={}), \
             patch("fetch_and_signal.get_watchlist_tickers", return_value={"9984.T": "監視"}), \
             patch("fetch_and_signal.get_previous_signal_tickers", return_value={}):
            self.assertEqual(select_repair_tickers(sb, {}, date(2026, 10, 2)), {"9984.T": "監視"})

    def test_price_scale_invariance_and_score_sign(self):
        row = {"Close": 100, "sma25": 102, "sma75": 100, "rsi14": 45, "macd": 2, "macd_signal": 1, "bb_upper": 110, "bb_lower": 90}
        signal, score = make_signal(row)
        self.assertEqual(signal, "buy_candidate")
        self.assertGreater(score, 0)
        scaled = {key: value * 100 if key != "rsi14" else value for key, value in row.items()}
        self.assertEqual(make_signal(scaled), (signal, score))
        row.update(sma25=98, macd=0)
        self.assertEqual(make_signal(row)[0], "sell_candidate")
        self.assertLess(make_signal(row)[1], 0)

    def test_zero_remaining_capacity_blocks_all_candidates(self):
        rows = [{"ticker": "7203.T", "ml_signal": "buy_candidate", "ml_score": 0.9}]
        self.assertEqual(limit_ml_buy_candidates(rows, 0), 1)
        self.assertEqual(rows[0]["ml_signal"], "hold")

    def test_repair_uses_original_comparison_universe(self):
        sb = MagicMock()
        sb.table.return_value.select.return_value.eq.return_value.limit.return_value.execute.return_value.data = [
            {"ticker": "7203.T", "stocks": {"name": "トヨタ"}},
            {"ticker": "6758.T", "stocks": [{"name": "ソニー"}]},
        ]
        targets = {"8306.T": "三菱UFJ"}
        self.assertEqual(set(repair_inference_universe(sb, targets, {}, date(2026, 10, 1))), {"7203.T", "6758.T", "8306.T"})
        self.assertEqual(targets, {"8306.T": "三菱UFJ"})

    def test_small_repair_subset_changes_cross_sectional_rank(self):
        frames = {}
        for i in range(30):
            frames[str(i)] = pd.DataFrame([{
                "date": date(2026, 10, 1), "sma25_ratio": 0.01, "return_1d": 0.01,
                "return_5d": i / 100, "return_20d": i / 100, "volume_ratio": 1,
                "rsi14": 50, "macd_diff": 1, "bb_position": 0.5,
                "volatility_20d": 0.01, "atr_ratio_14d": 0.01,
            }])
        full = add_breadth_features(frames)["0"].iloc[0]["cs_rank_return_5d"]
        subset = add_breadth_features({"0": frames["0"]})["0"].iloc[0]["cs_rank_return_5d"]
        self.assertAlmostEqual(full, 1 / 30)
        self.assertNotEqual(full, subset)

    def test_transient_upsert_retry(self):
        table = MagicMock()
        table.upsert.return_value.execute.side_effect = [RuntimeError("504 Gateway Timeout"), None]
        with patch("fetch_and_signal.time.sleep"):
            upsert_in_chunks(table, [{"ticker": "7203.T"}])
        self.assertEqual(table.upsert.return_value.execute.call_count, 2)



class PromotionTests(unittest.TestCase):
    def evaluation(self, avg_return, trades=500, win_rate=0.5):
        return {"avg_return": avg_return, "trades": trades, "win_rate": win_rate, "objective": avg_return}

    def test_out_of_sample_start(self):
        self.assertEqual(bundle_out_of_sample_start({"test_start_date": "2026-09-01"}), "2026-09-01")
        legacy = {"promotion": {"candidate_test_sub_periods": [{"start": "2026-06-02"}, {"start": "2026-06-30"}]}}
        self.assertEqual(bundle_out_of_sample_start(legacy), "2026-06-02")
        self.assertIsNone(bundle_out_of_sample_start({}))
        self.assertIsNone(bundle_out_of_sample_start(None))

    def test_relative_comparison_uses_shared_unseen_period(self):
        folds = [{"evaluation": {"trades": 100, "avg_return": 0.001}}] * 3
        periods = [{"avg_return": 0.002}] * 3
        candidate = self.evaluation(0.002)
        # 既存モデルは自分の学習期間を含む全期間だと+0.5%に見えるが、共通の未使用期間では候補が上回る。
        self.assertFalse(should_promote_candidate(candidate, self.evaluation(0.005), periods, folds)[0])
        promote, reason = should_promote_candidate(
            candidate, self.evaluation(0.001), periods, folds, self.evaluation(0.003, trades=200)
        )
        self.assertTrue(promote, reason)
        # 比較期間の取引数が少なすぎる場合は昇格させない。絶対値の基準は全テスト期間で判定する。
        self.assertFalse(should_promote_candidate(
            candidate, self.evaluation(0.001), periods, folds, self.evaluation(0.01, trades=5)
        )[0])
        self.assertFalse(should_promote_candidate(
            self.evaluation(-0.001), self.evaluation(-0.01), periods, folds, self.evaluation(0.01)
        )[0])


if __name__ == "__main__":
    unittest.main()

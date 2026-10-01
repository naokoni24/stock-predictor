"""終値時刻・欠損日・売買判定の回帰テスト。外部サービスへ接続しない。"""

import unittest
from datetime import date, datetime
from unittest.mock import MagicMock, patch

import pandas as pd

from market_calendar import get_market_cutoff, is_jpx_trading_day, next_trading_dates
from evaluate_signal_outcomes import simulate_trade, topix_return
from fetch_and_signal import limit_ml_buy_candidates, make_signal, repair_inference_universe, upsert_in_chunks
from train_model import add_breadth_features, compute_barrier_outcome


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


class SignalTests(unittest.TestCase):
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


if __name__ == "__main__":
    unittest.main()

from __future__ import annotations

import sys
import unittest
from pathlib import Path

import numpy as np


ROOT = Path(__file__).resolve().parents[1] / "app"
sys.path.insert(0, str(ROOT))

from src.perfiles import _apply_slope_anomaly_threshold, _slope_axis  # noqa: E402


class SlopeAxisTests(unittest.TestCase):
    def test_low_slope_uses_centered_two_point_five_scale(self) -> None:
        for maximum in (1.0, 2.25):
            axis = _slope_axis(np.array([-maximum, maximum, np.nan]))
            self.assertEqual(axis, {"low": -2.5, "high": 2.5, "ticks": (-2.0, -1.0, 0.0, 1.0, 2.0)})

    def test_medium_slope_uses_centered_five_scale(self) -> None:
        for maximum in (2.26, 4.5):
            axis = _slope_axis(np.array([-maximum, maximum, np.inf]))
            self.assertEqual(axis, {"low": -5.0, "high": 5.0, "ticks": (-4.0, -2.0, 0.0, 2.0, 4.0)})

    def test_high_slope_uses_real_extremes_and_includes_zero(self) -> None:
        threshold_axis = _slope_axis(np.array([4.51]))
        self.assertIsNotNone(threshold_axis)
        assert threshold_axis is not None
        self.assertIsNone(threshold_axis["ticks"])
        self.assertAlmostEqual(float(threshold_axis["low"]), -0.8118)
        self.assertAlmostEqual(float(threshold_axis["high"]), 5.3218)

        axis = _slope_axis(np.array([-10.0, 0.1, 4.51, np.nan]))
        self.assertIsNotNone(axis)
        assert axis is not None
        self.assertAlmostEqual(float(axis["low"]), -12.6118)
        self.assertAlmostEqual(float(axis["high"]), 7.1218)
        self.assertIsNone(axis["ticks"])
        self.assertLessEqual(float(axis["low"]), -10.0)
        self.assertGreaterEqual(float(axis["high"]), 4.51)
        self.assertLessEqual(float(axis["low"]), 0.0)
        self.assertGreaterEqual(float(axis["high"]), 0.0)


class SlopeAnomalyThresholdTests(unittest.TestCase):
    def test_anomalies_are_neutralized_without_altering_smoothed_values(self) -> None:
        smoothed = np.array([8.0, 12.0, -12.0, 10.0, -10.0])

        represented, anomalies = _apply_slope_anomaly_threshold(smoothed, 10.0)

        np.testing.assert_array_equal(smoothed, np.array([8.0, 12.0, -12.0, 10.0, -10.0]))
        np.testing.assert_array_equal(represented, np.array([8.0, 0.0, 0.0, 10.0, -10.0]))
        np.testing.assert_array_equal(anomalies, np.array([False, True, True, False, False]))


if __name__ == "__main__":
    unittest.main()

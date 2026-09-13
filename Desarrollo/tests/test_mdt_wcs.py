from __future__ import annotations

import sys
import unittest
from pathlib import Path
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1] / "app"
sys.path.insert(0, str(ROOT))

from src.mdt_wcs import PREFERRED_COVERAGES, _coverage_candidates, _resolution_attempts, _supported_resolutions  # noqa: E402


class MdtWcsTests(unittest.TestCase):
    def test_pixel_limit_allows_25m_when_5m_is_too_large(self) -> None:
        attempts = _resolution_attempts((0.0, 0.0, 10005.0, 10005.0), [5.0, 25.0], 4_000_000)
        self.assertFalse(attempts[0]["within_limit"])
        self.assertTrue(attempts[1]["within_limit"])
        self.assertEqual(attempts[0]["pixels"], 4_004_001)

    def test_resolution_uses_only_its_equivalent_coverage(self) -> None:
        warnings: list[str] = []
        with patch("src.mdt_wcs.WebCoverageService") as service:
            service.return_value.contents = {PREFERRED_COVERAGES[25]: object()}
            candidates = _coverage_candidates("https://example.invalid/wcs", 1, 5.0, warnings)
        self.assertEqual(candidates, [PREFERRED_COVERAGES[5]])
        self.assertTrue(any(PREFERRED_COVERAGES[5] in warning for warning in warnings))

    def test_non_native_resolution_uses_the_supported_fallbacks(self) -> None:
        warnings: list[str] = []
        resolutions = _supported_resolutions("5.9", {}, warnings)
        self.assertEqual(resolutions, [5.0, 25.0])
        self.assertTrue(any("no compatible" in warning for warning in warnings))


if __name__ == "__main__":
    unittest.main()

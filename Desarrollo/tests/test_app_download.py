from __future__ import annotations

import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1] / "app"
sys.path.insert(0, str(ROOT))

import app as web_app  # noqa: E402


class DownloadPathTests(unittest.TestCase):
    def test_output_root_membership_rejects_parent_traversal(self) -> None:
        outputs_root = Path("Resultados").resolve()
        inside = (outputs_root / "job" / "mapa.png").resolve()
        outside = (outputs_root / "job" / ".." / ".." / "secreto.txt").resolve()
        self.assertTrue(web_app._is_within_outputs_root(inside, outputs_root))
        self.assertFalse(web_app._is_within_outputs_root(outside, outputs_root))

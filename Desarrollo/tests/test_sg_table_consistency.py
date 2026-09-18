from __future__ import annotations

import ast
import re
import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1] / "app"
sys.path.insert(0, str(ROOT))

from src.perfiles import SG_TABLE  # noqa: E402


class SavitzkyGolayTableConsistencyTests(unittest.TestCase):
    def test_python_and_javascript_tables_match(self) -> None:
        js_path = ROOT / "static" / "js" / "app.js"
        source = js_path.read_text(encoding="utf-8")
        match = re.search(r"const SG_TABLE = \{(?P<body>.*?)\n\};", source, flags=re.DOTALL)
        self.assertIsNotNone(match, "No se encontro la declaracion SG_TABLE en app.js")
        js_table: dict[int, dict[str, object]] = {}
        for level, window, polyorder, label in re.findall(
            r"^\s*(\d+): \{ window: (\d+), polyorder: (\d+), label: (\"(?:[^\"\\]|\\.)*\") \},$",
            match.group("body"),
            flags=re.MULTILINE,
        ):
            js_table[int(level)] = {
                "window": int(window),
                "polyorder": int(polyorder),
                "label": ast.literal_eval(label),
            }
        self.assertEqual(set(js_table), set(range(11)))
        self.assertEqual(
            {level: {key: SG_TABLE[level][key] for key in ("window", "polyorder", "label")} for level in range(11)},
            js_table,
        )

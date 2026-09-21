from __future__ import annotations

import sys
import unittest
from datetime import datetime, timedelta
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

    def test_local_host_requires_explicit_remote_opt_in(self) -> None:
        for host in ("127.0.0.1", "::1", "localhost"):
            self.assertEqual(web_app._validated_host({"host": host}), host)
        with self.assertRaisesRegex(RuntimeError, "loopback"):
            web_app._validated_host({"host": "0.0.0.0"})
        self.assertEqual(web_app._validated_host({"host": "0.0.0.0", "allow_remote": True}), "0.0.0.0")

    def test_pruning_keeps_active_and_recent_jobs(self) -> None:
        original = dict(web_app.JOBS)
        try:
            web_app.JOBS.clear()
            now = datetime.now()
            web_app.JOBS.update({
                "active": {"estado": "ejecutando", "creado": now.isoformat()},
                "old": {"estado": "completado", "finalizado": (now - timedelta(hours=25)).isoformat()},
                "recent": {"estado": "error", "finalizado": now.isoformat()},
            })
            web_app._prune_jobs_locked(now)
            self.assertIn("active", web_app.JOBS)
            self.assertIn("recent", web_app.JOBS)
            self.assertNotIn("old", web_app.JOBS)
        finally:
            web_app.JOBS.clear(); web_app.JOBS.update(original)

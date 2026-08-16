from __future__ import annotations
import tempfile,unittest
from pathlib import Path
from db.init_db import initialize,connect
from engine.regression_engine import compare_value

class ControlPlaneSmoke(unittest.TestCase):
    def test_schema_bootstrap(self):
        with tempfile.TemporaryDirectory() as td:
            path=Path(td)/'results.db'; initialize(path)
            with connect(path) as conn:
                names={r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
            self.assertIn('executions',names); self.assertIn('execution_metrics',names); self.assertIn('audit_events',names)
    def test_regression_direction(self):
        result=compare_value(80,100,10,'lower_is_bad'); self.assertTrue(result['regression']); self.assertAlmostEqual(result['delta_percent'],-20)
        result=compare_value(105,100,10,'lower_is_bad'); self.assertFalse(result['regression'])

if __name__=='__main__':unittest.main()

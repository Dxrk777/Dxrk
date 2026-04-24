import unittest
import subprocess
import sys
from pathlib import Path

class TestMasterSmoke(unittest.TestCase):
    def test_start_reports_online(self):
        # Run the master start command and verify ONLINE status
        repo_root = Path(__file__).resolve().parents[1]
        master_path = repo_root / 'dxrk_master.py'
        res = subprocess.run([sys.executable, str(master_path), 'start'], capture_output=True, text=True)
        assert res.returncode == 0
        assert 'ONLINE' in res.stdout or 'ONLINE' in res.stderr

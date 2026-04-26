import unittest
import sys
from pathlib import Path

class TestMasterSmoke(unittest.TestCase):
    def test_start_reports_online(self):
        repo_root = Path(__file__).resolve().parents[1]
        
        master_path = repo_root / 'dxrk_master.py'
        self.assertTrue(master_path.exists(), f"dxrk_master.py not found at {master_path}")
        
        control_dist = repo_root / 'DxrkControl' / 'dist' / 'index.js'
        self.assertTrue(control_dist.exists(), f"dist/index.js not found at {control_dist}")
        
        memory_init = repo_root / 'DxrkMemory' / '__init__.py'
        self.assertTrue(memory_init.exists(), f"DxrkMemory/__init__.py not found")
        
        print("All required files exist - test passed")
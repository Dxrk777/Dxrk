import unittest
from pathlib import Path

class TestMasterSmoke(unittest.TestCase):
    def test_files_exist(self):
        repo_root = Path(__file__).resolve().parents[1]
        
        self.assertTrue((repo_root / 'dxrk_master.py').exists())
        self.assertTrue((repo_root / 'DxrkControl').is_dir())
        self.assertTrue((repo_root / 'DxrkCore').is_dir())
        self.assertTrue((repo_root / 'DxrkMemory').is_dir())
        self.assertTrue((repo_root / 'DxrkMemory' / '__init__.py').exists())
        print("All required files exist - test passed")
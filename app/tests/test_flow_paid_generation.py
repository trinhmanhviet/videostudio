import unittest
from pathlib import Path


class PaidFlowLauncherTests(unittest.TestCase):
    def test_local_launcher_enables_user_authorized_native_flow_path(self):
        script=Path(__file__).resolve().parents[1]/'scripts'/'start_local.ps1'
        source=script.read_text(encoding='utf8')
        self.assertIn("$env:VS_FLOW_REFERENCE_UI_VERIFIED='1'",source)


if __name__=='__main__':unittest.main()

"""Timeout regression with real fixture processes, without a paid agent."""
import sys
import tempfile
import time
import unittest
from pathlib import Path

from test_binder import ROOT
sys.path.insert(0, str(ROOT / "evals"))
from runner import run_command


class TestAgentProcessTree(unittest.TestCase):
    def test_timeout_stops_child_before_it_can_write_after_return(self):
        with tempfile.TemporaryDirectory() as temp:
            directory = Path(temp)
            child = "from pathlib import Path; import time; Path('child_started').touch(); time.sleep(2.5); Path('late_effect').touch()"
            parent = f"import subprocess,sys,time; subprocess.Popen([sys.executable,'-c',{child!r}]); time.sleep(10)"
            code, _, _, _ = run_command([sys.executable, "-c", parent], directory, 1)
            self.assertEqual(code, 124)
            self.assertTrue((directory / "child_started").exists())
            time.sleep(2)
            self.assertFalse((directory / "late_effect").exists())

    def test_exited_parent_cannot_leave_a_worker_running(self):
        with tempfile.TemporaryDirectory() as temp:
            directory = Path(temp)
            child = "from pathlib import Path; import time; Path('child_started').touch(); time.sleep(1); Path('late_effect').touch()"
            parent = (f"import subprocess,sys,time; from pathlib import Path; subprocess.Popen([sys.executable,'-c',{child!r}]); "
                      "\nwhile not Path('child_started').exists(): time.sleep(.01)\n")
            code, _, _, _ = run_command([sys.executable, "-c", parent], directory, 5)
            self.assertEqual(code, 0)
            time.sleep(1.2)
            self.assertFalse((directory / "late_effect").exists())

    def test_both_logs_are_drained_but_memory_and_saved_bytes_are_bounded(self):
        with tempfile.TemporaryDirectory() as temp:
            command = [sys.executable, "-c", "import os; os.write(1,b'x'*200000); os.write(2,b'\\xff'*200000)"]
            code, stdout, stderr, stats = run_command(command, Path(temp), 5, log_limit=1024)
            self.assertEqual(code, 0)
            self.assertEqual(len(stdout), 1024)
            self.assertEqual(len(stderr), 1024)
            self.assertEqual(stats["stdout"]["octets_lus"], 200000)
            self.assertTrue(stats["stdout"]["tronque"])
            self.assertTrue(stats["stderr"]["tronque"])

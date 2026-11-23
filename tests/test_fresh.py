"""A first run on a fresh computer works: nothing saved yet, no sites to
reach. Every album and artist still gets its page, from the tags alone."""
import subprocess, sys, tempfile, unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent


class FreshRun(unittest.TestCase):
    def test_fresh_run_offline(self):
        root = Path(tempfile.mkdtemp())
        r = subprocess.run([sys.executable, str(HERE / "fresh_run.py"), str(root)],
                           capture_output=True, text=True, timeout=600)
        self.assertEqual(r.returncode, 0, r.stdout[-3000:] + r.stderr[-3000:])
        notes = root / "out" / "Notes"
        self.assertTrue((notes / ".notes-wiki").exists())
        aja = (notes / "Albums" / "Steely Dan - Aja.md").read_text(encoding="utf-8")
        self.assertIn("[Steely Dan](<People/Steely Dan>)", aja)
        self.assertIn("2 tracks", aja)
        # each name by the rule on its own: "R.E.M." loses its last dot
        self.assertTrue((notes / "Albums" / "R.E.M - Murmur.md").exists())
        self.assertTrue((notes / "People" / "R.E.M.md").exists())
        self.assertNotIn("Traceback", r.stdout + r.stderr)


if __name__ == "__main__":
    unittest.main()

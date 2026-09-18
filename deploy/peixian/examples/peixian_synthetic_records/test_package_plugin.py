from __future__ import annotations

import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
import zipfile


ROOT = Path(__file__).resolve().parent


class PluginPackageTests(unittest.TestCase):
    def test_package_contains_only_the_runtime_manifest_and_entrypoint(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "peixian-synthetic-records-1.0.0.zip"
            result = subprocess.run([sys.executable, str(ROOT / "package_plugin.py"), "--output", str(output)], capture_output=True, text=True, check=False)
            self.assertEqual(result.returncode, 0, result.stderr)
            with zipfile.ZipFile(output) as archive:
                self.assertEqual(sorted(archive.namelist()), ["entry.mjs", "manifest.json"])
                manifest = json.loads(archive.read("manifest.json"))
                self.assertEqual(manifest["id"], "peixian-synthetic-records")
                self.assertEqual(manifest["version"], "1.0.0")
                self.assertEqual(len(manifest["tools"]), 7)
                self.assertEqual(set(manifest["connections"]), {"peixian_records"})
                self.assertNotIn("key", archive.read("entry.mjs").decode("utf-8").lower())


if __name__ == "__main__":
    unittest.main(verbosity=2)

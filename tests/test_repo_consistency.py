#!/usr/bin/env python3
"""Repository-wide consistency checks preventing cross-file drift."""

import json
import re
import subprocess
import sys
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent


class TestRepoConsistency(unittest.TestCase):
    """Ensure rules, installers, plugin metadata, and lint cleanliness stay in sync."""

    def test_embedded_rules_in_install_ps1_match_agents_md(self):
        agents_text = (REPO_ROOT / "rules" / "AGENTS.md").read_text(encoding="utf-8").strip()
        ps1_text = (REPO_ROOT / "install.ps1").read_text(encoding="utf-8")

        match = re.search(r"\$EmbeddedRules\s*=\s*@'\r?\n(.*?)\r?\n'@", ps1_text, re.DOTALL)
        self.assertIsNotNone(match, "Could not locate $EmbeddedRules block in install.ps1")
        embedded = match.group(1).replace("\r\n", "\n").strip()
        self.assertEqual(embedded, agents_text.replace("\r\n", "\n"))

    def test_plugin_json_valid(self):
        data = json.loads((REPO_ROOT / "plugin.json").read_text(encoding="utf-8"))
        self.assertEqual(data["name"], "antigravity-token-optimizer")
        self.assertIn("version", data)
        self.assertIn("repository", data)

    def test_repo_passes_prefix_linter(self):
        linter = str(REPO_ROOT / "tools" / "antigravity_prefix_linter.py")
        res = subprocess.run(
            [sys.executable, linter, str(REPO_ROOT), "--strict"],
            capture_output=True,
            text=True,
        )
        self.assertEqual(res.returncode, 0, f"Prefix linter failed on repo:\n{res.stdout}\n{res.stderr}")


if __name__ == "__main__":
    unittest.main()

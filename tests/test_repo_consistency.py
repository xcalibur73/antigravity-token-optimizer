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
        display_name = data.get("displayName", "")
        self.assertTrue(display_name)
        self.assertFalse(
            display_name.lower().startswith(("antigravity", "gemini", "claude", "cursor")),
            f"displayName '{display_name}' violates Antigravity Marketplace prefix rules",
        )
        prompts = data.get("suggestedPrompts", [])
        self.assertLessEqual(len(prompts), 3)
        logo = data.get("logo")
        if logo and not str(logo).startswith("http"):
            self.assertTrue((REPO_ROOT / logo).is_file(), f"Missing plugin logo asset: {logo}")
        self.assertTrue((REPO_ROOT / "agents" / "context-auditor.md").is_file())

    def test_installers_use_valid_global_agents_path(self):
        sh_text = (REPO_ROOT / "install.sh").read_text(encoding="utf-8")
        ps1_text = (REPO_ROOT / "install.ps1").read_text(encoding="utf-8")
        self.assertIn('$HOME/.gemini/config/AGENTS.md', sh_text)
        self.assertNotIn('.gemini/config/rules/AGENTS.md', sh_text)
        self.assertIn('".gemini", "config", "AGENTS.md"', ps1_text)
        self.assertNotIn('"rules", "AGENTS.md"', ps1_text)

    def test_repo_passes_prefix_linter(self):
        linter = str(REPO_ROOT / "tools" / "antigravity_prefix_linter.py")
        res = subprocess.run(
            [sys.executable, linter, str(REPO_ROOT), "--strict"],
            capture_output=True,
            text=True,
            encoding="utf-8",
        )
        self.assertEqual(res.returncode, 0, f"Prefix linter failed on repo:\n{res.stdout}\n{res.stderr}")


if __name__ == "__main__":
    unittest.main()

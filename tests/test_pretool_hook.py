#!/usr/bin/env python3
"""Unit tests for Google Antigravity PreToolUse Guardrail Hook."""

import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from tools.antigravity_pretool_hook import evaluate_tool_call


class TestPreToolHook(unittest.TestCase):
    """Test Invariant 3 and Invariant 4 guardrail behavior."""

    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        self.tmp_path = Path(self.tmpdir.name)

        self.small_file = self.tmp_path / "small.py"
        self.small_file.write_text("\n".join(f"x_{i} = {i}" for i in range(40)) + "\n", encoding="utf-8")

        self.large_file = self.tmp_path / "large.py"
        self.large_file.write_text("\n".join(f"line_{i} = {i}" for i in range(250)) + "\n", encoding="utf-8")

        self.binary_file = self.tmp_path / "diagram.png"
        self.binary_file.write_bytes(b"\x89PNG\r\n\x1a\n" + b"0" * 30000)

    def tearDown(self):
        self.tmpdir.cleanup()

    def test_allows_small_unbounded_read(self):
        res = evaluate_tool_call({
            "toolCall": {"name": "view_file", "args": {"AbsolutePath": str(self.small_file)}}
        })
        self.assertEqual(res["decision"], "allow")

    def test_allows_bounded_chunk_on_large_file(self):
        res = evaluate_tool_call({
            "toolCall": {
                "name": "view_file",
                "args": {"AbsolutePath": str(self.large_file), "StartLine": 1, "EndLine": 150},
            }
        })
        self.assertEqual(res["decision"], "allow")

    def test_denies_unbounded_read_on_large_file(self):
        res = evaluate_tool_call({
            "toolCall": {"name": "view_file", "args": {"AbsolutePath": str(self.large_file)}}
        })
        self.assertEqual(res["decision"], "deny")
        self.assertIn("Invariant 4", res["reason"])

    def test_denies_oversized_line_range(self):
        res = evaluate_tool_call({
            "toolCall": {
                "name": "view_file",
                "args": {"AbsolutePath": str(self.large_file), "StartLine": 1, "EndLine": 200},
            }
        })
        self.assertEqual(res["decision"], "deny")
        self.assertIn("200 lines", res["reason"])

    def test_allows_binary_and_upload_files(self):
        res_bin = evaluate_tool_call({
            "toolCall": {"name": "view_file", "args": {"AbsolutePath": str(self.binary_file)}}
        })
        self.assertEqual(res_bin["decision"], "allow")

        upload_dir = self.tmp_path / "upload"
        upload_dir.mkdir()
        uploaded = upload_dir / "notes.txt"
        uploaded.write_text("\n".join(f"u_{i}" for i in range(300)), encoding="utf-8")
        res_upload = evaluate_tool_call({
            "toolCall": {"name": "view_file", "args": {"AbsolutePath": str(uploaded)}}
        })
        self.assertEqual(res_upload["decision"], "allow")

    def test_denies_bare_cat_on_large_file_allows_piped(self):
        deny_res = evaluate_tool_call({
            "toolCall": {"name": "run_command", "args": {"CommandLine": f"cat {self.large_file}"}}
        })
        self.assertEqual(deny_res["decision"], "deny")
        self.assertIn("Invariant 3", deny_res["reason"])

        allow_res = evaluate_tool_call({
            "toolCall": {"name": "run_command", "args": {"CommandLine": f"cat {self.large_file} | tail -n 25"}}
        })
        self.assertEqual(allow_res["decision"], "allow")

    def test_bypass_env_and_cli_bom_stdin(self):
        script = str(REPO_ROOT / "tools" / "antigravity_pretool_hook.py")
        payload = "\ufeff" + json.dumps({
            "toolCall": {"name": "view_file", "args": {"AbsolutePath": str(self.large_file)}}
        })

        res_deny = subprocess.run(
            [sys.executable, script],
            input=payload,
            capture_output=True,
            text=True,
        )
        self.assertEqual(res_deny.returncode, 0)
        self.assertEqual(json.loads(res_deny.stdout)["decision"], "deny")

        env = os.environ.copy()
        env["TOKEN_OPTIMIZER_HOOK_BYPASS"] = "1"
        res_bypass = subprocess.run(
            [sys.executable, script],
            input=payload,
            capture_output=True,
            text=True,
            env=env,
        )
        self.assertEqual(res_bypass.returncode, 0)
        self.assertEqual(json.loads(res_bypass.stdout)["decision"], "allow")


if __name__ == "__main__":
    unittest.main()

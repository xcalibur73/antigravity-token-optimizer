#!/usr/bin/env python3
"""Unit tests for Google Antigravity Transcript Analyzer."""

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

from tools.transcript_analyzer import analyze_transcript


class TestTranscriptAnalyzer(unittest.TestCase):
    """Test real JSONL parsing, usage metadata aggregation, and anti-pattern detection."""

    def _write_jsonl(self, records):
        fd, path = tempfile.mkstemp(suffix=".jsonl")
        os.close(fd)
        with open(path, "w", encoding="utf-8") as f:
            for rec in records:
                f.write(json.dumps(rec) + "\n")
        return Path(path)

    def test_usage_metadata_and_violation_detection(self):
        long_output = "\n".join(f"line {i}" for i in range(45))
        records = [
            {
                "step_index": 0,
                "type": "PLANNER_RESPONSE",
                "usageMetadata": {"promptTokenCount": 10000, "cachedContentTokenCount": 9000, "candidatesTokenCount": 200},
                "tool_calls": [{"name": "view_file", "arguments": {"AbsolutePath": "/tmp/big.py"}}],
            },
            {
                "step_index": 1,
                "type": "TOOL_RESPONSE",
                "content": long_output,
            },
            {
                "step_index": 2,
                "type": "PLANNER_RESPONSE",
                "usageMetadata": {"promptTokenCount": 12000, "cachedContentTokenCount": 10000, "candidatesTokenCount": 100},
                "tool_calls": [{"name": "manage_task", "arguments": {"Action": "status", "TaskId": "t1"}}],
            },
            {
                "step_index": 3,
                "type": "PLANNER_RESPONSE",
                "usageMetadata": {"promptTokenCount": 12000, "cachedContentTokenCount": 10000, "candidatesTokenCount": 100},
                "tool_calls": [{"name": "manage_task", "arguments": {"Action": "status", "TaskId": "t1"}}],
            },
        ]
        path = self._write_jsonl(records)
        try:
            report = analyze_transcript(path)
            self.assertEqual(report["total_steps"], 4)
            self.assertEqual(report["steps_with_usage_metadata"], 3)
            self.assertEqual(report["measured_tokens"]["prompt_tokens"], 34000)
            self.assertEqual(report["measured_tokens"]["cached_tokens"], 29000)
            self.assertAlmostEqual(report["measured_tokens"]["cache_hit_rate_pct"], 85.29, places=2)
            self.assertEqual(len(report["findings"]["oversized_outputs_over_30_lines"]), 1)
            self.assertEqual(len(report["findings"]["unbounded_view_file_calls"]), 1)
            self.assertEqual(len(report["findings"]["busy_wait_polling_sequences"]), 1)
            self.assertEqual(report["findings"]["busy_wait_polling_sequences"][0]["consecutive_polls"], 2)
        finally:
            if path.exists():
                path.unlink()

    def test_cli_json_output_without_usage_metadata(self):
        records = [
            {"step_index": 0, "type": "USER_INPUT", "content": "Hello world"},
            {"step_index": 1, "type": "PLANNER_RESPONSE", "content": "Checking file", "tool_calls": [
                {"name": "view_file", "arguments": {"AbsolutePath": "/tmp/a.py", "StartLine": 1, "EndLine": 50}}
            ]},
        ]
        path = self._write_jsonl(records)
        script = str(REPO_ROOT / "tools" / "transcript_analyzer.py")
        try:
            res = subprocess.run(
                [sys.executable, script, str(path), "--json"],
                capture_output=True,
                text=True,
            )
            self.assertEqual(res.returncode, 0)
            payload = json.loads(res.stdout)
            self.assertEqual(payload["steps_with_usage_metadata"], 0)
            self.assertGreater(payload["estimated_content_tokens"], 0)
            self.assertEqual(payload["findings"]["unbounded_view_file_calls"], [])
        finally:
            if path.exists():
                path.unlink()

    def test_discovery_tail_health_loops_and_handoff(self):
        from tools.transcript_analyzer import (
            discover_transcripts,
            generate_handoff_summary,
            inspect_tail_health,
        )

        with tempfile.TemporaryDirectory() as tmp:
            fake_home = Path(tmp)
            log_dir = fake_home / ".gemini" / "jetski" / "brain" / "conv-1234" / ".system_generated" / "logs"
            log_dir.mkdir(parents=True)
            log_path = log_dir / "transcript.jsonl"

            records = [
                {"step_index": 0, "type": "USER_INPUT", "content": "<USER_REQUEST>Optimize Antigravity tokens</USER_REQUEST>"},
                {"step_index": 1, "type": "PLANNER_RESPONSE", "content": "Reading", "tool_calls": [
                    {"name": "replace_file_content", "arguments": {"TargetFile": "/repo/app.py"}}
                ]},
            ]
            # Pad with identical repeated tool calls to trigger redundant_tool_loops and multi-chunk tail seek
            for i in range(2, 20):
                records.append({
                    "step_index": i,
                    "type": "PLANNER_RESPONSE",
                    "content": "Retrying " + ("x" * 5000),
                    "usageMetadata": {"promptTokenCount": 50000 + i * 1000, "cachedContentTokenCount": 40000, "candidatesTokenCount": 50},
                    "tool_calls": [{"name": "run_command", "arguments": {"CommandLine": "pytest"}}],
                })
            with open(log_path, "w", encoding="utf-8") as f:
                for rec in records:
                    f.write(json.dumps(rec) + "\n")

            discovered = discover_transcripts(home_dir=fake_home)
            self.assertEqual(len(discovered), 1)
            self.assertEqual(discovered[0]["runtime"], "cli")
            self.assertIn("Optimize Antigravity tokens", discovered[0]["title"])

            report = analyze_transcript(log_path, context_limit=100_000)
            self.assertGreaterEqual(len(report["findings"]["redundant_tool_loops"]), 1)
            self.assertEqual(len(report["findings"]["top_consumers"]), 5)
            self.assertEqual(report["context_health"]["status"], "Moderate")

            tail = inspect_tail_health(log_path, context_limit=100_000, chunk_bytes=8192)
            self.assertLess(tail["tail_bytes_scanned"], tail["file_size_bytes"])
            self.assertEqual(tail["latest_usage"]["prompt_tokens"], 69000)
            self.assertEqual(tail["health"], "Moderate")

            handoff = generate_handoff_summary(log_path)
            self.assertIn("<CONTEXT_SUMMARY>", handoff)
            self.assertIn("Optimize Antigravity tokens", handoff)
            self.assertIn("/repo/app.py", handoff)


if __name__ == "__main__":
    unittest.main()

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
                encoding="utf-8",
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

    def test_v232_planner_response_top_level_tokens_and_tail_health(self):
        from tools.transcript_analyzer import inspect_tail_health

        single_step_path = self._write_jsonl([
            {
                "step_index": 0,
                "type": "PLANNER_RESPONSE",
                "input_tokens": 1000,
                "cache_read_tokens": 9000,
                "output_tokens": 200,
            }
        ])
        multi_step_path = self._write_jsonl([
            {
                "step_index": 0,
                "type": "PLANNER_RESPONSE",
                "input_tokens": 1000,
                "cache_read_tokens": 9000,
                "output_tokens": 200,
            },
            {
                "step_index": 1,
                "type": "PLANNER_RESPONSE",
                "usageMetadata": {},
                "input_tokens": 1000,
                "cache_read_tokens": 0,
                "output_tokens": 50,
            },
        ])
        try:
            single_report = analyze_transcript(single_step_path)
            self.assertEqual(single_report["steps_with_usage_metadata"], 1)
            self.assertEqual(single_report["measured_tokens"]["prompt_tokens"], 10000)
            self.assertEqual(single_report["measured_tokens"]["cached_tokens"], 9000)
            self.assertEqual(single_report["measured_tokens"]["uncached_tokens"], 1000)
            self.assertEqual(single_report["measured_tokens"]["output_tokens"], 200)
            self.assertEqual(single_report["measured_tokens"]["cache_hit_rate_pct"], 90.0)

            single_tail = inspect_tail_health(single_step_path)
            self.assertEqual(
                single_tail["latest_usage"],
                {"prompt_tokens": 10000, "cached_tokens": 9000, "output_tokens": 200},
            )

            multi_report = analyze_transcript(multi_step_path)
            self.assertEqual(multi_report["steps_with_usage_metadata"], 2)
            self.assertEqual(multi_report["measured_tokens"]["prompt_tokens"], 11000)
            self.assertEqual(multi_report["measured_tokens"]["cached_tokens"], 9000)
            self.assertEqual(multi_report["measured_tokens"]["uncached_tokens"], 2000)
            self.assertEqual(multi_report["measured_tokens"]["output_tokens"], 250)
            self.assertEqual(multi_report["measured_tokens"]["latest_prompt_tokens"], 1000)

            multi_tail = inspect_tail_health(multi_step_path)
            self.assertEqual(
                multi_tail["latest_usage"],
                {"prompt_tokens": 1000, "cached_tokens": 0, "output_tokens": 50},
            )
        finally:
            for p in (single_step_path, multi_step_path):
                if p.exists():
                    p.unlink()

    def test_v232_generic_command_output_and_path_unquoting(self):
        from tools.transcript_analyzer import generate_handoff_summary

        generic_output = "Command exited with code 0.\n" + "\n".join(f"row {i}" for i in range(40))
        records = [
            {
                "step_index": 0,
                "type": "PLANNER_RESPONSE",
                "input_tokens": 500,
                "cache_read_tokens": 0,
                "output_tokens": 80,
                "tool_calls": [
                    {"name": "read_file", "arguments": {"Path": '"/repo/app.py"'}},
                    {"name": "read_file", "arguments": {"Path": "/repo/bounded.py", "start_line": 1, "end_line": 50}},
                    {"name": "write_file", "arguments": {"Path": "/repo/new_file.py"}},
                    {"name": "edit_file", "arguments": {"Path": '"/repo/edited.py"'}},
                ],
            },
            {
                "step_index": 1,
                "type": "GENERIC",
                "content": generic_output,
            },
        ]
        path = self._write_jsonl(records)
        try:
            report = analyze_transcript(path)
            oversized = report["findings"]["oversized_outputs_over_30_lines"]
            self.assertEqual(len(oversized), 1)
            self.assertEqual(oversized[0]["step_index"], 1)
            self.assertEqual(
                report["findings"]["unbounded_view_file_calls"],
                [{"step_index": 0, "path": "/repo/app.py"}],
            )

            handoff = generate_handoff_summary(path)
            self.assertIn("- `/repo/new_file.py`", handoff)
            self.assertIn("- `/repo/edited.py`", handoff)
            self.assertIn("- `/repo/app.py`", handoff)
            self.assertIn("- `/repo/bounded.py`", handoff)
            self.assertNotIn('"/repo/app.py"', handoff)
            self.assertNotIn('"/repo/edited.py"', handoff)
        finally:
            if path.exists():
                path.unlink()

    def test_v234_antigravity_cli_discovery(self):
        from tools.transcript_analyzer import discover_transcripts

        with tempfile.TemporaryDirectory() as tmp:
            fake_home = Path(tmp)
            for rel, cid in (
                (".gemini/antigravity-cli/brain", "conv-cli"),
                (".gemini/jetski/brain", "conv-legacy"),
            ):
                log_dir = fake_home / rel / cid / ".system_generated" / "logs"
                log_dir.mkdir(parents=True)
                with open(log_dir / "transcript.jsonl", "w", encoding="utf-8") as f:
                    f.write(json.dumps({"step_index": 0, "type": "USER_INPUT", "content": cid}) + "\n")

            discovered = discover_transcripts(home_dir=fake_home)
            self.assertEqual(len(discovered), 2)
            self.assertTrue(all(item["runtime"] == "cli" for item in discovered))
            conv_ids = {item["conversation_id"] for item in discovered}
            self.assertIn("conv-cli", conv_ids)
            self.assertIn("conv-legacy", conv_ids)

    def test_v234_transcript_full_hydration_for_truncated_steps(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            compact_content = "\n".join(f"line {i:02d} " + ("x" * 192) for i in range(20))
            self.assertEqual(len(compact_content), 4019)
            full_content = "Command exited with code 0.\n" + "\n".join(
                f"row {i:03d} " + ("y" * 92) for i in range(120)
            )

            hydrated_dir = root / "hydrated"
            hydrated_dir.mkdir()
            compact_path = hydrated_dir / "transcript.jsonl"
            full_path = hydrated_dir / "transcript_full.jsonl"
            compact_records = [
                {"step_index": 0, "type": "USER_INPUT", "content": "Run suite"},
                {
                    "step_index": 1,
                    "type": "GENERIC",
                    "content": compact_content,
                    "truncated_fields": ["content"],
                },
            ]
            full_records = [
                {"step_index": 0, "type": "USER_INPUT", "content": "Run suite"},
                {"step_index": 1, "type": "GENERIC", "content": full_content},
            ]
            with open(compact_path, "w", encoding="utf-8") as f:
                for rec in compact_records:
                    f.write(json.dumps(rec) + "\n")
            with open(full_path, "w", encoding="utf-8") as f:
                for rec in full_records:
                    f.write(json.dumps(rec) + "\n")

            report = analyze_transcript(compact_path)
            top = report["findings"]["top_consumers"][0]
            self.assertEqual(top["step_index"], 1)
            self.assertGreaterEqual(top["estimated_tokens"], 2500)
            self.assertGreaterEqual(top["lines"], 120)
            oversized = report["findings"]["oversized_outputs_over_30_lines"]
            self.assertEqual([item["step_index"] for item in oversized], [1])

            mismatch_dir = root / "mismatched"
            mismatch_dir.mkdir()
            mismatch_compact = mismatch_dir / "transcript.jsonl"
            mismatch_full = mismatch_dir / "transcript_full.jsonl"
            with open(mismatch_compact, "w", encoding="utf-8") as f:
                for rec in compact_records:
                    f.write(json.dumps(rec) + "\n")
            mismatch_full_records = [
                {"step_index": 0, "type": "USER_INPUT", "content": "Run suite"},
                {"step_index": 99, "type": "GENERIC", "content": full_content},
            ]
            with open(mismatch_full, "w", encoding="utf-8") as f:
                for rec in mismatch_full_records:
                    f.write(json.dumps(rec) + "\n")

            mismatch_report = analyze_transcript(mismatch_compact)
            self.assertEqual(mismatch_report["findings"]["oversized_outputs_over_30_lines"], [])
            mismatch_top = mismatch_report["findings"]["top_consumers"][0]
            self.assertEqual(mismatch_top["lines"], 20)
            self.assertLess(mismatch_top["estimated_tokens"], 1500)

    def test_v234_compact_existing_file_exempt_from_unbounded_reads(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            small_json = root / "small.json"
            small_lines = ["{"] + [f'  "k{i}": {i},' for i in range(37)] + ['  "k37": 37', "}"]
            small_json.write_text("\n".join(small_lines) + "\n", encoding="utf-8")

            large_py = root / "large.py"
            large_py.write_text("\n".join(f"val_{i} = {i}" for i in range(220)) + "\n", encoding="utf-8")

            missing_path = "/repo/missing.py"
            records = [
                {"step_index": 0, "type": "PLANNER_RESPONSE", "tool_calls": [{"name": "read_file", "arguments": {"Path": str(small_json)}}]},
                {"step_index": 1, "type": "PLANNER_RESPONSE", "tool_calls": [{"name": "read_file", "arguments": {"Path": str(small_json)}}]},
                {"step_index": 2, "type": "PLANNER_RESPONSE", "tool_calls": [{"name": "read_file", "arguments": {"Path": str(small_json)}}]},
                {"step_index": 3, "type": "PLANNER_RESPONSE", "tool_calls": [{"name": "read_file", "arguments": {"Path": str(large_py)}}]},
                {"step_index": 4, "type": "PLANNER_RESPONSE", "tool_calls": [{"name": "read_file", "arguments": {"Path": missing_path}}]},
            ]
            log_path = root / "transcript.jsonl"
            with open(log_path, "w", encoding="utf-8") as f:
                for rec in records:
                    f.write(json.dumps(rec) + "\n")

            report = analyze_transcript(log_path)
            unbounded_paths = [item["path"] for item in report["findings"]["unbounded_view_file_calls"]]
            self.assertEqual(unbounded_paths, [str(large_py), missing_path])
            loops = report["findings"]["redundant_tool_loops"]
            self.assertEqual(len(loops), 1)
            self.assertEqual(loops[0]["tool"], "read_file")
            self.assertEqual(loops[0]["repeats"], 3)


if __name__ == "__main__":
    unittest.main()

#!/usr/bin/env python3
"""Unit tests for Google Antigravity MCP Schema Compressor.

Tests key sorting, deterministic idempotence, docstring condensation,
boilerplate pruning, CLI flags (--check, --minify, --in-place), and token metrics.
"""

import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

# Ensure repo root is on sys.path regardless of execution directory
REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from tools.mcp_schema_compressor import (
    calculate_metrics,
    compress_schema,
    condense_description,
    serialize_schema,
)


class TestSchemaCompressorSorting(unittest.TestCase):
    """Test suite for deterministic alphabetical key and array sorting."""

    def test_dict_key_sorting(self):
        """Ensure dictionary keys at all nested levels are sorted alphabetically."""
        raw_data = {
            "zebra": 1,
            "apple": {
                "charlie": "val",
                "bravo": "val",
            },
            "mango": [1, 2, 3],
        }
        compressed = compress_schema(raw_data)
        self.assertEqual(list(compressed.keys()), ["apple", "mango", "zebra"])
        self.assertEqual(list(compressed["apple"].keys()), ["bravo", "charlie"])

    def test_required_array_sorting(self):
        """Ensure required parameter lists are sorted alphabetically."""
        schema = {
            "type": "object",
            "properties": {
                "z_param": {"type": "string"},
                "a_param": {"type": "string"},
                "m_param": {"type": "string"},
            },
            "required": ["z_param", "a_param", "m_param"],
        }
        compressed = compress_schema(schema)
        self.assertEqual(compressed["required"], ["a_param", "m_param", "z_param"])

    def test_tools_array_sorting(self):
        """Ensure tool lists are sorted alphabetically by tool identifier name."""
        tools_list = {
            "tools": [
                {"name": "write_file", "description": "Write file to disk."},
                {"name": "create_dir", "description": "Create a directory."},
                {"name": "delete_file", "description": "Delete a file."},
            ]
        }
        compressed = compress_schema(tools_list)
        names = [t["name"] for t in compressed["tools"]]
        self.assertEqual(names, ["create_dir", "delete_file", "write_file"])


class TestSchemaCompressorIdempotence(unittest.TestCase):
    """Test suite asserting mathematical idempotence: compress(compress(x)) == compress(x)."""

    def test_idempotence_complex_schema(self):
        raw_schema = {
            "tools": [
                {
                    "name": "edit_file",
                    "description": "Use this tool to edit an existing file. Follow these rules:\n1. Exact match.",
                    "inputSchema": {
                        "type": "object",
                        "title": "EditFileInput",
                        "$schema": "http://json-schema.org/draft-07/schema#",
                        "properties": {
                            "target": {"type": "string", "description": "Target string."},
                            "replacement": {"type": "string", "description": "Replacement string."},
                            "path": {"type": "string", "title": "path", "description": "Target path."},
                        },
                        "required": ["path", "target", "replacement"],
                    },
                },
                {
                    "name": "read_file",
                    "description": "This is a tool from the file server. Read contents of target file.",
                    "inputSchema": {
                        "type": "object",
                        "properties": {
                            "path": {"type": "string", "description": "File path."},
                        },
                        "required": ["path"],
                    },
                },
            ]
        }
        pass1 = compress_schema(raw_schema)
        pass2 = compress_schema(pass1)
        self.assertEqual(pass1, pass2)

        # Check serialized string idempotence
        str1 = serialize_schema(pass1, minify=False)
        str2 = serialize_schema(pass2, minify=False)
        self.assertEqual(str1, str2)

        min1 = serialize_schema(pass1, minify=True)
        min2 = serialize_schema(pass2, minify=True)
        self.assertEqual(min1, min2)


class TestSchemaCompressorDocstrings(unittest.TestCase):
    """Test suite for docstring condensation and constraint preservation."""

    def test_preamble_removal_this_is_a_tool(self):
        desc = "This is a tool from the gemini-api server. Search current upstream documentation."
        condensed = condense_description(desc)
        self.assertEqual(condensed, "Search current upstream documentation.")

    def test_preamble_removal_use_this_tool(self):
        desc = "Use this tool to edit an existing file on disk."
        condensed = condense_description(desc)
        self.assertEqual(condensed, "Edit an existing file on disk.")

    def test_preamble_removal_this_tool_allows_you(self):
        desc = "This tool allows you to inspect system metrics."
        condensed = condense_description(desc)
        self.assertEqual(condensed, "Inspect system metrics.")

    def test_preserve_range_constraint(self):
        desc = (
            "Wait for command completion before timing out. "
            "Timeout must be between 500 to 10000 milliseconds."
        )
        condensed = condense_description(desc)
        self.assertIn("Range: 500 to 10000", condensed)
        self.assertTrue(condensed.startswith("Wait for command completion before timing out"))

    def test_preserve_default_constraint(self):
        desc = "Maximum number of results to retrieve. Default is 50."
        condensed = condense_description(desc)
        self.assertEqual(condensed, "Maximum number of results to retrieve (Default: 50).")

    def test_preserve_parenthetical_constraint(self):
        desc = "Milliseconds to wait for process (500 to 10000)."
        condensed = condense_description(desc)
        self.assertEqual(condensed, "Milliseconds to wait for process (500 to 10000).")

    def test_markdown_stripping(self):
        desc = "### Instructions\n* **Step 1**: Run `command` in shell.\n* Step 2: Check output."
        condensed = condense_description(desc)
        self.assertNotIn("#", condensed)
        self.assertNotIn("*", condensed)
        self.assertNotIn("`", condensed)


class TestSchemaCompressorPruning(unittest.TestCase):
    """Test suite for pruning nulls, boilerplate schemas, and redundant fields."""

    def test_prune_null_values(self):
        data = {"valid": "value", "empty_key": None, "nested": {"keep": 1, "drop": None}}
        compressed = compress_schema(data)
        self.assertEqual(compressed, {"nested": {"keep": 1}, "valid": "value"})

    def test_prune_schema_boilerplate(self):
        data = {
            "$schema": "http://json-schema.org/draft-07/schema#",
            "type": "object",
            "title": "Config",
            "properties": {
                "name": {"type": "string", "title": "name"},
            },
        }
        compressed = compress_schema(data)
        self.assertNotIn("$schema", compressed)
        # title matching property name 'name' should be pruned
        self.assertNotIn("title", compressed["properties"]["name"])

    def test_prune_empty_containers(self):
        data = {
            "type": "object",
            "examples": [],
            "definitions": {},
            "$defs": {},
            "description": "",
            "properties": {"val": {"type": "string"}},
        }
        compressed = compress_schema(data)
        self.assertNotIn("examples", compressed)
        self.assertNotIn("definitions", compressed)
        self.assertNotIn("$defs", compressed)
        self.assertNotIn("description", compressed)


class TestSchemaCompressorCLI(unittest.TestCase):
    """Test suite for CLI execution, --check flag, --minify, and --in-place."""

    def setUp(self):
        self.script_path = str(Path(__file__).resolve().parent.parent / "tools" / "mcp_schema_compressor.py")

    def test_cli_check_flag_fails_on_uncompressed(self):
        """CLI with --check must exit with code 1 if schema requires sorting or compression."""
        uncompressed = {
            "tools": [
                {"name": "zebra", "description": "This is a tool that runs zebra."},
                {"name": "alpha", "description": "This is a tool that runs alpha."},
            ]
        }
        with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False, encoding="utf-8") as f:
            f.write(json.dumps(uncompressed, indent=2))
            temp_path = f.name

        try:
            res = subprocess.run(
                [sys.executable, self.script_path, "--input", temp_path, "--check"],
                capture_output=True,
                text=True,
            )
            self.assertEqual(res.returncode, 1)
            self.assertIn("FAIL", res.stderr)
        finally:
            if os.path.exists(temp_path):
                os.unlink(temp_path)

    def test_cli_check_flag_passes_on_compressed(self):
        """CLI with --check must exit with code 0 on an already compressed schema."""
        raw = {
            "tools": [
                {"name": "zebra", "description": "This is a tool that runs zebra."},
                {"name": "alpha", "description": "This is a tool that runs alpha."},
            ]
        }
        compressed = compress_schema(raw)
        formatted = serialize_schema(compressed, minify=False)

        with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False, encoding="utf-8") as f:
            f.write(formatted)
            temp_path = f.name

        try:
            res = subprocess.run(
                [sys.executable, self.script_path, "--input", temp_path, "--check"],
                capture_output=True,
                text=True,
            )
            self.assertEqual(res.returncode, 0)
            self.assertIn("PASS", res.stderr)
        finally:
            if os.path.exists(temp_path):
                os.unlink(temp_path)

    def test_cli_in_place_compression(self):
        """CLI with --in-place must rewrite file with compressed content."""
        uncompressed = {
            "tools": [
                {"name": "zebra", "description": "This tool is used to run zebra."},
                {"name": "alpha", "description": "Run alpha."},
            ]
        }
        with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False, encoding="utf-8") as f:
            f.write(json.dumps(uncompressed, indent=4))
            temp_path = f.name

        try:
            res = subprocess.run(
                [sys.executable, self.script_path, "--input", temp_path, "--in-place"],
                capture_output=True,
                text=True,
            )
            self.assertEqual(res.returncode, 0)

            # Re-read file
            with open(temp_path, "r", encoding="utf-8") as f:
                content = f.read()
            data = json.loads(content)
            names = [t["name"] for t in data["tools"]]
            self.assertEqual(names, ["alpha", "zebra"])
            self.assertEqual(data["tools"][1]["description"], "Run zebra.")

            # Second run with --check should pass
            res_check = subprocess.run(
                [sys.executable, self.script_path, "--input", temp_path, "--check"],
                capture_output=True,
                text=True,
            )
            self.assertEqual(res_check.returncode, 0)
        finally:
            if os.path.exists(temp_path):
                os.unlink(temp_path)

    def test_cli_minify_flag(self):
        """CLI with --minify must emit compact single-line JSON without newlines."""
        data = {"tools": [{"name": "a", "description": "Tool A."}]}
        with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False, encoding="utf-8") as f:
            f.write(json.dumps(data, indent=2))
            temp_path = f.name

        try:
            res = subprocess.run(
                [sys.executable, self.script_path, "--input", temp_path, "--minify"],
                capture_output=True,
                text=True,
            )
            self.assertEqual(res.returncode, 0)
            self.assertNotIn("\n", res.stdout.strip())
            parsed = json.loads(res.stdout)
            self.assertEqual(parsed["tools"][0]["name"], "a")
        finally:
            if os.path.exists(temp_path):
                os.unlink(temp_path)

    def test_token_metrics_calculation(self):
        """Verify token metrics calculates characters, tokens, and percentage reduction accurately."""
        before = "1234567890123456"  # 16 chars -> 4 tokens
        after = "12345678"          # 8 chars -> 2 tokens
        metrics = calculate_metrics(before, after)
        self.assertEqual(metrics["chars_before"], 16)
        self.assertEqual(metrics["chars_after"], 8)
        self.assertEqual(metrics["tokens_before"], 4)
        self.assertEqual(metrics["tokens_after"], 2)
        self.assertEqual(metrics["chars_saved"], 8)
        self.assertEqual(metrics["pct_reduction"], 50.0)


if __name__ == "__main__":
    unittest.main()

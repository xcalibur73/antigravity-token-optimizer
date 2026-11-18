#!/usr/bin/env python3
"""Unit tests for Google Antigravity Prefix Linter.

Tests prefix invariance rules, dynamic token detection, evasion attempts,
and tool schema sorting validation.
"""

import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

# Ensure repo root is on sys.path regardless of execution directory
REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from tools.antigravity_prefix_linter import check_file, check_tool_ordering


class TestPrefixLinterCleanRules(unittest.TestCase):
    """Test suite for clean files that must pass with zero violations."""

    def test_production_agents_md(self):
        """Verify repository rules/AGENTS.md passes with zero errors and zero warnings."""
        repo_root = Path(__file__).resolve().parent.parent
        agents_md = repo_root / "rules" / "AGENTS.md"
        self.assertTrue(agents_md.is_file(), f"rules/AGENTS.md not found at {agents_md}")

        violations = check_file(agents_md, strict=True)
        self.assertEqual(
            violations,
            [],
            f"rules/AGENTS.md produced unexpected violations: {violations}",
        )

    def test_clean_markdown_prompt(self):
        """Verify static prompt templates pass without violations."""
        content = (
            "# Static System Instructions\n\n"
            "You are a specialized code implementer.\n"
            "Always follow deterministic testing standards.\n"
            "Tool schemas are registered in alphabetical order.\n"
        )
        with tempfile.NamedTemporaryFile("w", suffix=".md", delete=False, encoding="utf-8") as f:
            f.write(content)
            temp_path = f.name

        try:
            violations = check_file(temp_path, strict=True)
            self.assertEqual(violations, [])
        finally:
            if os.path.exists(temp_path):
                os.unlink(temp_path)

    def test_clean_sorted_tools_json(self):
        """Verify deterministically sorted JSON tools pass without violations."""
        tools_data = {
            "tools": [
                {"description": "First tool.", "name": "alpha_tool"},
                {"description": "Second tool.", "name": "beta_tool"},
                {"description": "Third tool.", "name": "gamma_tool"},
            ]
        }
        with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False, encoding="utf-8") as f:
            f.write(json.dumps(tools_data, indent=2, sort_keys=True))
            temp_path = f.name

        try:
            violations = check_file(temp_path, strict=True)
            self.assertEqual(violations, [])
        finally:
            if os.path.exists(temp_path):
                os.unlink(temp_path)


class TestPrefixLinterDynamicViolations(unittest.TestCase):
    """Test suite asserting exact detection of dynamic tokens in prompt prefixes."""

    def _assert_violation(self, text, expected_rule, suffix=".md", strict=False):
        with tempfile.NamedTemporaryFile("w", suffix=suffix, delete=False, encoding="utf-8") as f:
            f.write(text)
            temp_path = f.name

        try:
            violations = check_file(temp_path, strict=strict)
            rule_ids = [v["rule"] for v in violations]
            self.assertIn(
                expected_rule,
                rule_ids,
                f"Expected violation '{expected_rule}' not found in {rule_ids} for input:\n{text}",
            )
            return violations
        finally:
            if os.path.exists(temp_path):
                os.unlink(temp_path)

    def test_dynamic_interpolation_timestamp(self):
        self._assert_violation("Current run: {{ timestamp }}", "DYNAMIC_INTERPOLATION")

    def test_dynamic_interpolation_uuid(self):
        self._assert_violation("Session token: {{ uuid }}", "DYNAMIC_INTERPOLATION")

    def test_dynamic_interpolation_session_id(self):
        self._assert_violation("Trace: {{ session_id }}", "DYNAMIC_INTERPOLATION")

    def test_dynamic_date_call_datetime_now(self):
        self._assert_violation("current_time = datetime.now()", "DYNAMIC_DATE_CALL", suffix=".py")

    def test_dynamic_date_call_time_time(self):
        self._assert_violation("t = time.time()", "DYNAMIC_DATE_CALL", suffix=".py")

    def test_dynamic_date_call_uuid4(self):
        self._assert_violation("u = uuid.uuid4()", "DYNAMIC_DATE_CALL", suffix=".py")

    def test_literal_iso_timestamp(self):
        self._assert_violation("Generated at 2026-03-24T14:30:00Z", "LITERAL_ISO_TIMESTAMP")

    def test_literal_uuid(self):
        self._assert_violation("Request ID: c7365003-270f-4889-8d76-e8834f89d38c", "LITERAL_UUID")

    def test_dynamic_session_assignment(self):
        self._assert_violation("session_id = 'sess_live_99812'", "DYNAMIC_SESSION_ASSIGNMENT")

    def test_in_place_prompt_mutation_set_system_prompt(self):
        self._assert_violation("agent.set_system_prompt(new_prompt)", "IN_PLACE_PROMPT_MUTATION", suffix=".py")

    def test_in_place_prompt_mutation_history_slice(self):
        self._assert_violation("messages[0] = {'role': 'system', 'content': 'updated'}", "IN_PLACE_PROMPT_MUTATION", suffix=".py")

    def test_in_place_prompt_mutation_replace(self):
        self._assert_violation("system_prompt.replace('old', 'new')", "IN_PLACE_PROMPT_MUTATION", suffix=".py")


class TestPrefixLinterEvasionAttempts(unittest.TestCase):
    """Test suite testing whitespace evasion, case insensitivity, and structural edge cases."""

    def _assert_violation(self, text, expected_rule, suffix=".md", strict=False):
        with tempfile.NamedTemporaryFile("w", suffix=suffix, delete=False, encoding="utf-8") as f:
            f.write(text)
            temp_path = f.name

        try:
            violations = check_file(temp_path, strict=strict)
            rule_ids = [v["rule"] for v in violations]
            self.assertIn(
                expected_rule,
                rule_ids,
                f"Evasion attempt bypassed linter! Expected '{expected_rule}' in {rule_ids} for:\n{text}",
            )
        finally:
            if os.path.exists(temp_path):
                os.unlink(temp_path)

    def test_whitespace_interpolation_evasion(self):
        """Ensure extra whitespace inside template tags does not evade detection."""
        self._assert_violation("Header: {{\n  timestamp  \n}}", "DYNAMIC_INTERPOLATION")

    def test_case_insensitive_interpolation_evasion(self):
        """Ensure mixed-case variable names do not evade detection."""
        self._assert_violation("Header: {{ TiMeStAmP }}", "DYNAMIC_INTERPOLATION")
        self._assert_violation("Header: {{ NoNcE }}", "DYNAMIC_INTERPOLATION")

    def test_unsorted_tools_json_detection(self):
        """Ensure unsorted tool definitions in JSON files are caught."""
        unsorted_tools = {
            "tools": [
                {"name": "write_file", "description": "Write tool."},
                {"name": "edit_file", "description": "Edit tool."},
            ]
        }
        with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False, encoding="utf-8") as f:
            f.write(json.dumps(unsorted_tools, indent=2))
            temp_path = f.name

        try:
            violations = check_file(temp_path, strict=True)
            rule_ids = [v["rule"] for v in violations]
            self.assertIn("UNSORTED_TOOL_DEFINITIONS", rule_ids)
        finally:
            if os.path.exists(temp_path):
                os.unlink(temp_path)

    def test_unsorted_tools_markdown_block_detection(self):
        """Ensure unsorted tool definitions in markdown code blocks are caught."""
        markdown_content = (
            "# Agent Tools Configuration\n\n"
            "```python\n"
            "tools = ['zeta_tool', 'alpha_tool']\n"
            "```\n"
        )
        self._assert_violation(markdown_content, "UNSORTED_TOOL_DEFINITIONS", suffix=".md")

    def test_nested_bracket_tools_block_detection(self):
        """Ensure nested lists like required=['a'] inside tools=[...] do not truncate matching."""
        py_content = (
            "tools = [\n"
            "    {'name': 'zeta_tool', 'required': ['b', 'a']},\n"
            "    {'name': 'alpha_tool', 'required': ['x']},\n"
            "]\n"
        )
        self._assert_violation(py_content, "UNSORTED_TOOL_DEFINITIONS", suffix=".py")

    def test_unsorted_json_schema_keys_detection(self):
        """Ensure unsorted keys inside JSON tool schemas trigger UNSORTED_SCHEMA_KEYS."""
        unsorted_schema = {
            "tools": [
                {
                    "name": "alpha_tool",
                    "description": "First.",
                    "inputSchema": {
                        "type": "object",
                        "properties": {
                            "zeta": {"type": "string"},
                            "alpha": {"type": "string"},
                        },
                        "required": ["zeta", "alpha"],
                    },
                }
            ]
        }
        self._assert_violation(json.dumps(unsorted_schema, indent=2), "UNSORTED_SCHEMA_KEYS", suffix=".json")

    def test_dynamic_tail_marker_allows_tail_metadata(self):
        """Variables placed after <!-- DYNAMIC_TAIL --> must not violate prefix invariance."""
        content = (
            "# Static System Prefix\n"
            "Always keep rules deterministic.\n"
            "<!-- DYNAMIC_TAIL -->\n"
            "Current request time: {{ timestamp }}\n"
        )
        with tempfile.NamedTemporaryFile("w", suffix=".md", delete=False, encoding="utf-8") as f:
            f.write(content)
            temp_path = f.name

        try:
            violations = check_file(temp_path, strict=True)
            self.assertEqual(violations, [])
        finally:
            if os.path.exists(temp_path):
                os.unlink(temp_path)

    def test_inline_ignore_suppression_and_def_not_flagged(self):
        """Function defs named *set_system_prompt and inline ignore comments must not error."""
        content = (
            "def test_helper_set_system_prompt(self):\n"
            "    pass\n"
            "ts = datetime.now()  # prefix-linter: ignore\n"
        )
        with tempfile.NamedTemporaryFile("w", suffix=".py", delete=False, encoding="utf-8") as f:
            f.write(content)
            temp_path = f.name

        try:
            violations = check_file(temp_path, strict=True)
            self.assertEqual(violations, [])
        finally:
            if os.path.exists(temp_path):
                os.unlink(temp_path)


if __name__ == "__main__":
    unittest.main()

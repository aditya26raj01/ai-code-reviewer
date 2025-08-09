"""Analysis agent for parsing linter and test outputs."""

from typing import Dict, List, Any
from .base import BaseAgent, AgentResult
import json
import re


class AnalysisAgent(BaseAgent):
    """Agent for analyzing linter and test outputs."""

    def __init__(self):
        super().__init__("AnalysisAgent")

    async def execute(
        self, linter_results: Dict[str, Any], test_results: Dict[str, Any]
    ) -> AgentResult:
        """Parse and structure linter and test outputs."""
        try:
            self.log_info("Starting analysis of linter and test results")

            # Parse linter results
            linter_issues = self._parse_linter_results(linter_results)

            # Parse test results
            test_summary = self._parse_test_results(test_results)

            # Combine results
            analysis = {
                "linter_issues": linter_issues,
                "test_summary": test_summary,
                "total_issues": len(linter_issues),
                "critical_issues": len(
                    [i for i in linter_issues if i.get("severity") == "error"]
                ),
                "test_status": test_summary.get("status", "unknown"),
            }

            self.log_info(f"Analysis complete: {analysis['total_issues']} issues found")

            return AgentResult(
                success=True,
                data=analysis,
                metadata={
                    "files_analyzed": len(set(i["file"] for i in linter_issues)),
                    "test_files": test_summary.get("files_tested", 0),
                },
            )

        except Exception as e:
            self.log_error(f"Analysis failed: {str(e)}")
            return AgentResult(success=False, error=str(e))

    def _parse_linter_results(
        self, linter_results: Dict[str, Any]
    ) -> List[Dict[str, Any]]:
        """Parse linter results into structured format."""
        issues = []

        # Parse Pylint results
        if "pylint" in linter_results:
            issues.extend(self._parse_pylint_output(linter_results["pylint"]))

        # Parse ESLint results
        if "eslint" in linter_results:
            issues.extend(self._parse_eslint_output(linter_results["eslint"]))

        return issues

    def _parse_pylint_output(self, output: str) -> List[Dict[str, Any]]:
        """Parse Pylint output."""
        issues = []

        # Pylint output format: file.py:line:column: code: message
        pattern = r"([^:]+):(\d+):(\d+): ([A-Z]\d+): (.+)"

        for line in output.split("\n"):
            match = re.match(pattern, line)
            if match:
                file_path, line_num, column, code, message = match.groups()

                # Determine severity based on code prefix
                severity = (
                    "error"
                    if code.startswith("E")
                    else "warning" if code.startswith("W") else "info"
                )

                issues.append(
                    {
                        "file": file_path,
                        "line": int(line_num),
                        "column": int(column),
                        "code": code,
                        "message": message,
                        "severity": severity,
                        "linter": "pylint",
                    }
                )

        return issues

    def _parse_eslint_output(self, output: str) -> List[Dict[str, Any]]:
        """Parse ESLint output (assuming JSON format)."""
        issues = []

        try:
            eslint_data = json.loads(output)

            for file_result in eslint_data:
                file_path = file_result.get("filePath", "")

                for message in file_result.get("messages", []):
                    severity = (
                        "error"
                        if message.get("severity") == 2
                        else "warning" if message.get("severity") == 1 else "info"
                    )

                    issues.append(
                        {
                            "file": file_path,
                            "line": message.get("line", 0),
                            "column": message.get("column", 0),
                            "code": message.get("ruleId", ""),
                            "message": message.get("message", ""),
                            "severity": severity,
                            "linter": "eslint",
                        }
                    )

        except json.JSONDecodeError:
            self.log_error("Failed to parse ESLint JSON output")

        return issues

    def _parse_test_results(self, test_results: Dict[str, Any]) -> Dict[str, Any]:
        """Parse test results into summary."""
        summary = {
            "status": "unknown",
            "passed": 0,
            "failed": 0,
            "skipped": 0,
            "total": 0,
            "coverage": None,
            "failures": [],
        }

        # Parse pytest results
        if "pytest" in test_results:
            pytest_summary = self._parse_pytest_output(test_results["pytest"])
            summary.update(pytest_summary)

        # Parse jest results
        if "jest" in test_results:
            jest_summary = self._parse_jest_output(test_results["jest"])
            # Merge results if both exist
            if summary["status"] == "unknown":
                summary.update(jest_summary)
            else:
                summary["passed"] += jest_summary.get("passed", 0)
                summary["failed"] += jest_summary.get("failed", 0)
                summary["total"] += jest_summary.get("total", 0)
                summary["failures"].extend(jest_summary.get("failures", []))

        # Update status
        if summary["total"] > 0:
            summary["status"] = "passed" if summary["failed"] == 0 else "failed"

        return summary

    def _parse_pytest_output(self, output: str) -> Dict[str, Any]:
        """Parse pytest output."""
        summary = {"passed": 0, "failed": 0, "skipped": 0, "total": 0, "failures": []}

        # Look for summary line
        summary_pattern = r"(\d+) passed(?:, (\d+) failed)?(?:, (\d+) skipped)?"
        match = re.search(summary_pattern, output)

        if match:
            summary["passed"] = int(match.group(1))
            summary["failed"] = int(match.group(2) or 0)
            summary["skipped"] = int(match.group(3) or 0)
            summary["total"] = (
                summary["passed"] + summary["failed"] + summary["skipped"]
            )

        # Extract failure details
        failure_pattern = r"FAILED (.+) - (.+)"
        for match in re.finditer(failure_pattern, output):
            summary["failures"].append(
                {"test": match.group(1), "reason": match.group(2)}
            )

        return summary

    def _parse_jest_output(self, output: str) -> Dict[str, Any]:
        """Parse jest output."""
        summary = {"passed": 0, "failed": 0, "skipped": 0, "total": 0, "failures": []}

        # Try to parse JSON output first
        try:
            jest_data = json.loads(output)
            summary["passed"] = jest_data.get("numPassedTests", 0)
            summary["failed"] = jest_data.get("numFailedTests", 0)
            summary["total"] = jest_data.get("numTotalTests", 0)

            # Extract failures
            for test_result in jest_data.get("testResults", []):
                for assertion in test_result.get("assertionResults", []):
                    if assertion.get("status") == "failed":
                        summary["failures"].append(
                            {
                                "test": assertion.get("fullName", ""),
                                "reason": assertion.get("failureMessages", [""])[0],
                            }
                        )

        except json.JSONDecodeError:
            # Fall back to text parsing
            self.log_debug("Falling back to text parsing for jest output")

        return summary

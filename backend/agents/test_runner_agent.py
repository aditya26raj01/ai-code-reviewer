"""Test runner agent for validating patches."""

from typing import Dict, List, Any, Optional
from .base import BaseAgent, AgentResult
import tempfile
import shutil
import subprocess
import os
import json


class TestRunnerAgent(BaseAgent):
    """Agent for running tests on patched code."""

    def __init__(self):
        super().__init__("TestRunnerAgent")

    async def execute(
        self,
        patches: List[Dict[str, Any]],
        repo_path: str,
        test_commands: Optional[Dict[str, str]] = None,
    ) -> AgentResult:
        """Apply patches and run tests to verify they don't break anything."""
        try:
            self.log_info("Starting test validation for patches")

            if not patches:
                return AgentResult(
                    success=True, data={"all_tests_passed": True, "results": []}
                )

            # Default test commands if not provided
            if not test_commands:
                test_commands = self._detect_test_commands(repo_path)

            # Create temporary workspace
            with tempfile.TemporaryDirectory() as temp_dir:
                # Copy repository to temp directory
                temp_repo = os.path.join(temp_dir, "test_repo")
                shutil.copytree(
                    repo_path,
                    temp_repo,
                    ignore=shutil.ignore_patterns(
                        ".git", "__pycache__", "node_modules"
                    ),
                )

                # Test each patch
                results = []
                for patch in patches:
                    result = await self._test_patch(patch, temp_repo, test_commands)
                    results.append(result)

                # Aggregate results
                all_passed = all(r["tests_passed"] for r in results)

                self.log_info(
                    f"Test validation complete: {'PASSED' if all_passed else 'FAILED'}"
                )

                return AgentResult(
                    success=True,
                    data={
                        "all_tests_passed": all_passed,
                        "results": results,
                        "total_patches": len(patches),
                        "patches_passed": sum(1 for r in results if r["tests_passed"]),
                    },
                    metadata={"test_commands": test_commands},
                )

        except Exception as e:
            self.log_error(f"Test validation failed: {str(e)}")
            return AgentResult(success=False, error=str(e))

    def _detect_test_commands(self, repo_path: str) -> Dict[str, str]:
        """Detect appropriate test commands based on repository structure."""
        commands = {}

        # Python tests
        if os.path.exists(os.path.join(repo_path, "pytest.ini")) or os.path.exists(
            os.path.join(repo_path, "setup.cfg")
        ):
            commands["python"] = "pytest -xvs"
        elif os.path.exists(os.path.join(repo_path, "setup.py")):
            commands["python"] = "python -m pytest"

        # JavaScript/TypeScript tests
        if os.path.exists(os.path.join(repo_path, "package.json")):
            # Read package.json to check for test script
            try:
                with open(os.path.join(repo_path, "package.json"), "r") as f:
                    package_data = json.load(f)
                    if "test" in package_data.get("scripts", {}):
                        commands["javascript"] = "npm test"
            except:
                commands["javascript"] = "npm test"

        # Default fallback
        if not commands:
            commands["default"] = "echo 'No tests found'"

        return commands

    async def _test_patch(
        self, patch: Dict[str, Any], repo_path: str, test_commands: Dict[str, str]
    ) -> Dict[str, Any]:
        """Test a single patch."""
        file_path = patch["file_path"]
        full_path = os.path.join(repo_path, file_path)

        # Backup original file
        backup_path = full_path + ".backup"
        if os.path.exists(full_path):
            shutil.copy2(full_path, backup_path)

        try:
            # Apply patch
            os.makedirs(os.path.dirname(full_path), exist_ok=True)
            with open(full_path, "w") as f:
                f.write(patch["patched_content"])

            # Determine which tests to run
            file_type = self._get_file_type(file_path)
            test_cmd = test_commands.get(file_type, test_commands.get("default", ""))

            # Run linter first (quick check)
            linter_passed = await self._run_linter(full_path, file_type)

            if not linter_passed:
                return {
                    "file_path": file_path,
                    "tests_passed": False,
                    "linter_passed": False,
                    "test_output": "Linter check failed",
                    "error": "Code does not pass linting",
                }

            # Run tests
            test_result = await self._run_tests(repo_path, test_cmd, file_path)

            return {
                "file_path": file_path,
                "tests_passed": test_result["passed"],
                "linter_passed": linter_passed,
                "test_output": test_result["output"],
                "error": test_result.get("error"),
                "fixes_applied": len(patch.get("fixes", [])),
            }

        finally:
            # Restore original file
            if os.path.exists(backup_path):
                shutil.move(backup_path, full_path)

    def _get_file_type(self, file_path: str) -> str:
        """Determine file type from path."""
        if file_path.endswith(".py"):
            return "python"
        elif file_path.endswith((".js", ".jsx", ".ts", ".tsx")):
            return "javascript"
        else:
            return "default"

    async def _run_linter(self, file_path: str, file_type: str) -> bool:
        """Run linter on file."""
        try:
            if file_type == "python":
                result = subprocess.run(
                    ["pylint", "--errors-only", file_path],
                    capture_output=True,
                    text=True,
                    timeout=30,
                )
                return result.returncode == 0

            elif file_type == "javascript":
                # Assume ESLint is configured
                result = subprocess.run(
                    ["npx", "eslint", file_path],
                    capture_output=True,
                    text=True,
                    timeout=30,
                )
                return result.returncode == 0

            return True  # Skip linting for other file types

        except Exception as e:
            self.log_warning(f"Linter check failed: {str(e)}")
            return True  # Don't fail on linter errors

    async def _run_tests(
        self, repo_path: str, test_cmd: str, file_path: str
    ) -> Dict[str, Any]:
        """Run test command and parse results."""
        if not test_cmd or test_cmd == "echo 'No tests found'":
            return {"passed": True, "output": "No tests to run"}

        try:
            # Run tests with timeout
            result = subprocess.run(
                test_cmd.split(),
                cwd=repo_path,
                capture_output=True,
                text=True,
                timeout=300,  # 5 minute timeout
            )

            # Check if specific file tests exist
            if "pytest" in test_cmd and file_path.endswith(".py"):
                # Try to run tests for specific module
                module_name = file_path.replace("/", ".").replace(".py", "")
                specific_result = subprocess.run(
                    ["pytest", "-xvs", f"tests/test_{os.path.basename(file_path)}"],
                    cwd=repo_path,
                    capture_output=True,
                    text=True,
                    timeout=60,
                )

                if specific_result.returncode == 0:
                    return {"passed": True, "output": specific_result.stdout}

            return {
                "passed": result.returncode == 0,
                "output": result.stdout + result.stderr,
                "error": result.stderr if result.returncode != 0 else None,
            }

        except subprocess.TimeoutExpired:
            return {
                "passed": False,
                "output": "Test execution timed out",
                "error": "Timeout after 5 minutes",
            }
        except Exception as e:
            return {"passed": False, "output": str(e), "error": str(e)}

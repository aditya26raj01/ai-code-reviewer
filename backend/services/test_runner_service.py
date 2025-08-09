"""Service for running tests."""

import subprocess
import os
import json
import logging
from typing import Dict, List, Any, Optional

logger = logging.getLogger(__name__)


class TestRunnerService:
    """Service for running various test frameworks."""

    def __init__(self):
        self.test_runners = {
            "python": self._run_pytest,
            "javascript": self._run_jest,
            "typescript": self._run_jest,
        }

    async def run_tests(
        self, repo_path: str, changed_files: Optional[List[str]] = None
    ) -> Dict[str, Any]:
        """Run tests for the repository."""
        results = {}

        # Detect which test frameworks are available
        available_runners = self._detect_test_runners(repo_path)

        # Run each available test framework
        for framework, runner_func in available_runners.items():
            logger.info(f"Running {framework} tests")
            try:
                test_output = await runner_func(repo_path, changed_files)
                results[framework] = test_output
            except Exception as e:
                logger.error(f"Test runner {framework} failed: {str(e)}")
                results[framework] = {"error": str(e)}

        return results

    def _detect_test_runners(self, repo_path: str) -> Dict[str, Any]:
        """Detect which test runners are available."""
        available = {}

        # Check for Python test setup
        if any(
            os.path.exists(os.path.join(repo_path, f))
            for f in ["pytest.ini", "setup.cfg", "setup.py", "pyproject.toml"]
        ):
            available["pytest"] = self._run_pytest

        # Check for JavaScript/TypeScript test setup
        package_json_path = os.path.join(repo_path, "package.json")
        if os.path.exists(package_json_path):
            try:
                with open(package_json_path, "r") as f:
                    package_data = json.load(f)

                # Check for test script
                if "test" in package_data.get("scripts", {}):
                    # Check for specific test frameworks
                    deps = {
                        **package_data.get("dependencies", {}),
                        **package_data.get("devDependencies", {}),
                    }

                    if "jest" in deps or "@jest/core" in deps:
                        available["jest"] = self._run_jest
                    elif "mocha" in deps:
                        available["mocha"] = self._run_mocha
                    else:
                        # Generic npm test
                        available["npm"] = self._run_npm_test
            except:
                pass

        return available

    async def _run_pytest(
        self, repo_path: str, changed_files: Optional[List[str]] = None
    ) -> str:
        """Run pytest."""
        cmd = ["pytest", "-v", "--tb=short"]

        # Add coverage if available
        if self._check_package_installed("pytest-cov", repo_path):
            cmd.extend(["--cov", "--cov-report=term-missing"])

        # Add specific test files if provided
        if changed_files:
            # Find test files related to changed files
            test_files = self._find_test_files(changed_files, repo_path, ".py")
            if test_files:
                cmd.extend(test_files)

        try:
            result = subprocess.run(
                cmd,
                cwd=repo_path,
                capture_output=True,
                text=True,
                timeout=300,  # 5 minutes
            )

            return result.stdout + result.stderr

        except subprocess.TimeoutExpired:
            return "Test execution timed out after 5 minutes"
        except Exception as e:
            return f"Error running pytest: {str(e)}"

    async def _run_jest(
        self, repo_path: str, changed_files: Optional[List[str]] = None
    ) -> str:
        """Run Jest tests."""
        cmd = ["npx", "jest", "--json", "--outputFile=/tmp/jest-results.json"]

        # Add specific test files if provided
        if changed_files:
            test_files = self._find_test_files(
                changed_files,
                repo_path,
                [".test.js", ".test.ts", ".spec.js", ".spec.ts"],
            )
            if test_files:
                cmd.extend(test_files)

        try:
            # Run Jest
            result = subprocess.run(
                cmd, cwd=repo_path, capture_output=True, text=True, timeout=300
            )

            # Try to read JSON output
            try:
                if os.path.exists("/tmp/jest-results.json"):
                    with open("/tmp/jest-results.json", "r") as f:
                        return f.read()
            except:
                pass

            # Fallback to stdout
            return result.stdout + result.stderr

        except subprocess.TimeoutExpired:
            return json.dumps({"error": "Test execution timed out after 5 minutes"})
        except Exception as e:
            return json.dumps({"error": f"Error running jest: {str(e)}"})
        finally:
            # Clean up
            if os.path.exists("/tmp/jest-results.json"):
                os.unlink("/tmp/jest-results.json")

    async def _run_mocha(
        self, repo_path: str, changed_files: Optional[List[str]] = None
    ) -> str:
        """Run Mocha tests."""
        cmd = ["npx", "mocha", "--reporter=json"]

        # Add specific test files if provided
        if changed_files:
            test_files = self._find_test_files(
                changed_files,
                repo_path,
                [".test.js", ".test.ts", ".spec.js", ".spec.ts"],
            )
            if test_files:
                cmd.extend(test_files)

        try:
            result = subprocess.run(
                cmd, cwd=repo_path, capture_output=True, text=True, timeout=300
            )

            return result.stdout

        except subprocess.TimeoutExpired:
            return json.dumps({"error": "Test execution timed out after 5 minutes"})
        except Exception as e:
            return json.dumps({"error": f"Error running mocha: {str(e)}"})

    async def _run_npm_test(
        self, repo_path: str, changed_files: Optional[List[str]] = None
    ) -> str:
        """Run generic npm test."""
        cmd = ["npm", "test"]

        try:
            result = subprocess.run(
                cmd, cwd=repo_path, capture_output=True, text=True, timeout=300
            )

            return result.stdout + result.stderr

        except subprocess.TimeoutExpired:
            return "Test execution timed out after 5 minutes"
        except Exception as e:
            return f"Error running npm test: {str(e)}"

    def _find_test_files(
        self, changed_files: List[str], repo_path: str, extensions: Any
    ) -> List[str]:
        """Find test files related to changed files."""
        if isinstance(extensions, str):
            extensions = [extensions]

        test_files = []

        for file in changed_files:
            # Direct test file
            for ext in extensions:
                if file.endswith(ext):
                    if os.path.exists(os.path.join(repo_path, file)):
                        test_files.append(file)
                    break

            # Look for corresponding test file
            base_name = os.path.splitext(os.path.basename(file))[0]
            dir_name = os.path.dirname(file)

            # Common test file patterns
            test_patterns = [
                f"test_{base_name}",
                f"{base_name}_test",
                f"{base_name}.test",
                f"{base_name}.spec",
            ]

            # Check various test directories
            test_dirs = [
                dir_name,
                os.path.join(dir_name, "tests"),
                os.path.join(dir_name, "test"),
                os.path.join(dir_name, "__tests__"),
                "tests",
                "test",
                "__tests__",
            ]

            for test_dir in test_dirs:
                for pattern in test_patterns:
                    for ext in extensions:
                        test_file = os.path.join(test_dir, f"{pattern}{ext}")
                        full_path = os.path.join(repo_path, test_file)
                        if os.path.exists(full_path):
                            test_files.append(test_file)

        return list(set(test_files))  # Remove duplicates

    def _check_package_installed(self, package: str, repo_path: str) -> bool:
        """Check if a Python package is installed."""
        try:
            result = subprocess.run(
                ["pip", "show", package], capture_output=True, cwd=repo_path, timeout=5
            )
            return result.returncode == 0
        except:
            return False

"""Service for running linters on code."""

import subprocess
import os
import json
import tempfile
import logging
from typing import Dict, List, Any, Optional

logger = logging.getLogger(__name__)


class LinterService:
    """Service for running various linters."""

    def __init__(self):
        self.linters = {
            "python": self._run_pylint,
            "javascript": self._run_eslint,
            "typescript": self._run_eslint,
        }

    async def lint_files(
        self, files: List[Dict[str, Any]], repo_path: Optional[str] = None
    ) -> Dict[str, Any]:
        """Run appropriate linters on changed files."""
        results = {}

        # Group files by language
        files_by_lang = self._group_files_by_language(files)

        # Run linters for each language
        for lang, lang_files in files_by_lang.items():
            if lang in self.linters and lang_files:
                logger.info(f"Running {lang} linter on {len(lang_files)} files")
                try:
                    linter_output = await self.linters[lang](lang_files, repo_path)
                    results[lang] = linter_output
                except Exception as e:
                    logger.error(f"Linter for {lang} failed: {str(e)}")
                    results[lang] = {"error": str(e)}

        return results

    def _group_files_by_language(
        self, files: List[Dict[str, Any]]
    ) -> Dict[str, List[Dict[str, Any]]]:
        """Group files by programming language."""
        grouped = {}

        for file in files:
            filename = file.get("filename", "")

            # Skip deleted files
            if file.get("status") == "removed":
                continue

            # Determine language
            if filename.endswith(".py"):
                lang = "python"
            elif filename.endswith((".js", ".jsx")):
                lang = "javascript"
            elif filename.endswith((".ts", ".tsx")):
                lang = "typescript"
            else:
                continue

            if lang not in grouped:
                grouped[lang] = []
            grouped[lang].append(file)

        return grouped

    async def _run_pylint(
        self, files: List[Dict[str, Any]], repo_path: Optional[str] = None
    ) -> Dict[str, Any]:
        """Run Pylint on Python files."""
        results = {"output": "", "files_checked": 0, "issues": []}

        for file in files:
            if not file.get("content"):
                continue

            # Write content to temporary file
            with tempfile.NamedTemporaryFile(
                mode="w", suffix=".py", delete=False
            ) as tmp:
                tmp.write(file["content"])
                tmp_path = tmp.name

            try:
                # Run pylint
                cmd = [
                    "pylint",
                    "--output-format=json",
                    "--disable=C",  # Disable convention messages
                    "--disable=R",  # Disable refactor messages
                    tmp_path,
                ]

                result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)

                # Parse JSON output
                if result.stdout:
                    try:
                        pylint_data = json.loads(result.stdout)
                        for msg in pylint_data:
                            # Map temp file path back to original
                            msg["path"] = file["filename"]
                            results["issues"].append(msg)
                    except json.JSONDecodeError:
                        # Fallback to text output
                        results["output"] += result.stdout

                results["files_checked"] += 1

            except subprocess.TimeoutExpired:
                logger.warning(f"Pylint timeout for {file['filename']}")
            except Exception as e:
                logger.error(f"Pylint error for {file['filename']}: {str(e)}")
            finally:
                # Clean up temp file
                os.unlink(tmp_path)

        # Format output for compatibility
        if not results["output"] and results["issues"]:
            # Convert JSON issues to text format
            output_lines = []
            for issue in results["issues"]:
                line = f"{issue['path']}:{issue['line']}:{issue['column']}: {issue['message-id']}: {issue['message']}"
                output_lines.append(line)
            results["output"] = "\n".join(output_lines)

        return {"pylint": results["output"]}

    async def _run_eslint(
        self, files: List[Dict[str, Any]], repo_path: Optional[str] = None
    ) -> Dict[str, Any]:
        """Run ESLint on JavaScript/TypeScript files."""
        results = {"output": "", "files_checked": 0, "issues": []}

        # Check if ESLint is available
        if not self._check_eslint_available(repo_path):
            return {"eslint": json.dumps([{"error": "ESLint not configured"}])}

        # Create temporary directory for files
        with tempfile.TemporaryDirectory() as tmp_dir:
            file_paths = []

            # Write files to temp directory
            for file in files:
                if not file.get("content"):
                    continue

                # Preserve directory structure
                file_path = os.path.join(tmp_dir, file["filename"])
                os.makedirs(os.path.dirname(file_path), exist_ok=True)

                with open(file_path, "w") as f:
                    f.write(file["content"])

                file_paths.append(file_path)

            if not file_paths:
                return {"eslint": json.dumps([])}

            try:
                # Run ESLint
                cmd = ["npx", "eslint", "--format=json"] + file_paths

                # If repo_path provided, use its ESLint config
                cwd = repo_path if repo_path else tmp_dir

                result = subprocess.run(
                    cmd, capture_output=True, text=True, cwd=cwd, timeout=60
                )

                # ESLint returns non-zero for linting errors, which is expected
                if result.stdout:
                    try:
                        eslint_data = json.loads(result.stdout)

                        # Map temp paths back to original
                        for file_result in eslint_data:
                            # Find original filename
                            for file in files:
                                if file_result["filePath"].endswith(file["filename"]):
                                    file_result["filePath"] = file["filename"]
                                    break

                        results["output"] = json.dumps(eslint_data)
                    except json.JSONDecodeError:
                        results["output"] = result.stdout

                results["files_checked"] = len(file_paths)

            except subprocess.TimeoutExpired:
                logger.warning("ESLint timeout")
                results["output"] = json.dumps([{"error": "ESLint timeout"}])
            except Exception as e:
                logger.error(f"ESLint error: {str(e)}")
                results["output"] = json.dumps([{"error": str(e)}])

        return {"eslint": results["output"]}

    def _check_eslint_available(self, repo_path: Optional[str] = None) -> bool:
        """Check if ESLint is available."""
        try:
            cmd = ["npx", "eslint", "--version"]
            cwd = repo_path if repo_path else None

            result = subprocess.run(cmd, capture_output=True, timeout=10, cwd=cwd)

            return result.returncode == 0
        except:
            return False

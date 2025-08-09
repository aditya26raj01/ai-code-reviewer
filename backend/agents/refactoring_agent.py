"""Refactoring agent for generating code patches."""

from typing import Dict, List, Any, Optional
from .base import BaseAgent, AgentResult
from langchain.chat_models import ChatOpenAI
from langchain.prompts import ChatPromptTemplate
from langchain.schema import SystemMessage, HumanMessage
import difflib
import re
from ..config import settings


class RefactoringAgent(BaseAgent):
    """Agent for generating safe refactoring patches."""

    def __init__(self):
        super().__init__("RefactoringAgent")

        # Initialize code generation models
        self.code_model = None
        if settings.openai_api_key:
            self.code_model = ChatOpenAI(
                model="gpt-4-turbo-preview",
                api_key=settings.openai_api_key,
                temperature=0.1,  # Low temperature for consistent code generation
            )

    async def execute(
        self, files: List[Dict[str, Any]], review_results: Dict[str, Any]
    ) -> AgentResult:
        """Generate refactoring patches based on review results."""
        try:
            self.log_info("Starting refactoring patch generation")

            if not self.code_model:
                return AgentResult(
                    success=False, error="No code generation model available"
                )

            # Filter issues that can be auto-fixed
            fixable_issues = self._identify_fixable_issues(review_results["issues"])

            if not fixable_issues:
                self.log_info("No automatically fixable issues found")
                return AgentResult(success=True, data={"patches": [], "total_fixes": 0})

            # Group issues by file
            issues_by_file = self._group_issues_by_file(fixable_issues)

            # Generate patches for each file
            patches = []
            for file_path, issues in issues_by_file.items():
                file_data = next((f for f in files if f["filename"] == file_path), None)
                if file_data and file_data.get("content"):
                    patch = await self._generate_file_patch(file_data, issues)
                    if patch:
                        patches.append(patch)

            self.log_info(f"Generated {len(patches)} patches")

            return AgentResult(
                success=True,
                data={
                    "patches": patches,
                    "total_fixes": sum(len(p["fixes"]) for p in patches),
                    "confidence": (
                        min(p["confidence"] for p in patches) if patches else 0
                    ),
                },
                metadata={
                    "fixable_issues": len(fixable_issues),
                    "files_patched": len(patches),
                },
            )

        except Exception as e:
            self.log_error(f"Refactoring failed: {str(e)}")
            return AgentResult(success=False, error=str(e))

    def _identify_fixable_issues(
        self, issues: List[Dict[str, Any]]
    ) -> List[Dict[str, Any]]:
        """Identify issues that can be automatically fixed."""
        fixable_patterns = [
            # Linting issues
            r"missing.*docstring",
            r"unused.*import",
            r"trailing.*whitespace",
            r"line too long",
            r"missing.*type.*annotation",
            r"unnecessary.*parentheses",
            # Code style
            r"inconsistent.*indentation",
            r"missing.*space",
            r"extra.*space",
            # Simple refactorings
            r"use.*instead of",
            r"simplify.*expression",
            r"remove.*redundant",
        ]

        fixable = []
        for issue in issues:
            message = issue.get("message", "").lower()
            if any(re.search(pattern, message) for pattern in fixable_patterns):
                fixable.append(issue)
            # Also include high-confidence AI suggestions
            elif (
                issue.get("agreement_count", 0) >= 2 and issue.get("severity") != "low"
            ):
                fixable.append(issue)

        return fixable

    def _group_issues_by_file(
        self, issues: List[Dict[str, Any]]
    ) -> Dict[str, List[Dict[str, Any]]]:
        """Group issues by file path."""
        grouped = {}
        for issue in issues:
            file_path = issue.get("file", "")
            if file_path:
                if file_path not in grouped:
                    grouped[file_path] = []
                grouped[file_path].append(issue)
        return grouped

    async def _generate_file_patch(
        self, file_data: Dict[str, Any], issues: List[Dict[str, Any]]
    ) -> Optional[Dict[str, Any]]:
        """Generate patch for a single file."""
        self.log_debug(f"Generating patch for {file_data['filename']}")

        original_content = file_data["content"]
        if not original_content:
            return None

        # Prepare context for the model
        context = self._prepare_patch_context(file_data, issues)

        prompt = ChatPromptTemplate.from_messages(
            [
                SystemMessage(
                    content="""You are an expert code refactoring assistant. 
Given a file with issues, generate a corrected version that fixes the identified problems.

Rules:
1. Only fix the specific issues mentioned
2. Preserve all other code exactly as-is
3. Maintain the original code style and formatting
4. Ensure the fixed code is syntactically correct
5. Add necessary imports if required
6. Do not change functionality, only fix issues

Return the complete corrected file content."""
                ),
                HumanMessage(content=context),
            ]
        )

        try:
            # Get refactored code
            response = await self.code_model.ainvoke(prompt.format_messages())
            refactored_content = response.content

            # Clean up the response (remove markdown code blocks if present)
            refactored_content = self._clean_code_response(refactored_content)

            # Generate unified diff
            diff = self._generate_unified_diff(
                original_content, refactored_content, file_data["filename"]
            )

            # Identify what was fixed
            fixes = self._identify_fixes(original_content, refactored_content, issues)

            return {
                "file_path": file_data["filename"],
                "original_content": original_content,
                "patched_content": refactored_content,
                "unified_diff": diff,
                "fixes": fixes,
                "confidence": 0.8 if fixes else 0.5,
            }

        except Exception as e:
            self.log_error(
                f"Failed to generate patch for {file_data['filename']}: {str(e)}"
            )
            return None

    def _prepare_patch_context(
        self, file_data: Dict[str, Any], issues: List[Dict[str, Any]]
    ) -> str:
        """Prepare context for patch generation."""
        context = f"File: {file_data['filename']}\n\n"

        # Add issues
        context += "Issues to fix:\n"
        for issue in issues:
            context += f"- Line {issue.get('line', '?')}: {issue['message']}\n"

        context += f"\n\nOriginal code:\n```\n{file_data['content']}\n```"

        return context

    def _clean_code_response(self, code: str) -> str:
        """Clean up code response from model."""
        # Remove markdown code blocks
        code = re.sub(r"^```[\w]*\n", "", code, flags=re.MULTILINE)
        code = re.sub(r"\n```$", "", code, flags=re.MULTILINE)

        # Remove any leading/trailing whitespace
        code = code.strip()

        return code

    def _generate_unified_diff(
        self, original: str, modified: str, filename: str
    ) -> str:
        """Generate unified diff between original and modified content."""
        original_lines = original.splitlines(keepends=True)
        modified_lines = modified.splitlines(keepends=True)

        diff = difflib.unified_diff(
            original_lines,
            modified_lines,
            fromfile=f"a/{filename}",
            tofile=f"b/{filename}",
            n=3,  # Context lines
        )

        return "".join(diff)

    def _identify_fixes(
        self, original: str, modified: str, issues: List[Dict[str, Any]]
    ) -> List[Dict[str, Any]]:
        """Identify what fixes were applied."""
        fixes = []

        # Simple line-by-line comparison
        original_lines = original.splitlines()
        modified_lines = modified.splitlines()

        for issue in issues:
            line_num = issue.get("line", 0)
            if line_num > 0 and line_num <= len(original_lines):
                if line_num <= len(modified_lines):
                    if original_lines[line_num - 1] != modified_lines[line_num - 1]:
                        fixes.append(
                            {
                                "line": line_num,
                                "issue": issue["message"],
                                "original": original_lines[line_num - 1].strip(),
                                "fixed": modified_lines[line_num - 1].strip(),
                            }
                        )

        return fixes

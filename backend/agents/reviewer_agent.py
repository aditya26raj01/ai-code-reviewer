"""Reviewer agent for AI-powered code review."""

from typing import Dict, List, Any, Optional
from .base import BaseAgent, AgentResult
from langchain_community.chat_models import ChatOpenAI, ChatAnthropic
from langchain.prompts import ChatPromptTemplate
from langchain.schema import SystemMessage, HumanMessage
import json
import asyncio
from ..config import settings


class ReviewerAgent(BaseAgent):
    """Agent for performing AI-powered code review."""

    def __init__(self):
        super().__init__("ReviewerAgent")

        # Initialize OpenAI models only
        self.models = {}
        if settings.openai_api_key:
            # Primary model for reasoning and review
            self.models["gpt-4o-mini"] = ChatOpenAI(
                model="gpt-4o-mini", api_key=settings.openai_api_key, temperature=0.2
            )
            # Backup model for complex analysis
            self.models["gpt-4-turbo"] = ChatOpenAI(
                model="gpt-4-turbo-preview",
                api_key=settings.openai_api_key,
                temperature=0.3,
            )
        else:
            raise ValueError("OpenAI API key is required for ReviewerAgent")

    async def execute(
        self,
        files: List[Dict[str, Any]],
        analysis_results: Dict[str, Any],
        pr_metadata: Dict[str, Any],
    ) -> AgentResult:
        """Review code changes using multiple AI models."""
        try:
            self.log_info("Starting AI code review")

            # Prepare context
            context = self._prepare_review_context(files, analysis_results, pr_metadata)

            # Get reviews from multiple models
            reviews = await self._get_multi_model_reviews(context)

            # Aggregate and prioritize issues
            final_review = self._aggregate_reviews(reviews)

            self.log_info(
                f"Review complete: {len(final_review['issues'])} issues identified"
            )

            return AgentResult(
                success=True,
                data=final_review,
                metadata={
                    "models_used": list(reviews.keys()),
                    "files_reviewed": len(files),
                },
            )

        except Exception as e:
            self.log_error(f"Review failed: {str(e)}")
            return AgentResult(success=False, error=str(e))

    def _prepare_review_context(
        self,
        files: List[Dict[str, Any]],
        analysis_results: Dict[str, Any],
        pr_metadata: Dict[str, Any],
    ) -> str:
        """Prepare context for AI review."""
        context = f"""
Pull Request: {pr_metadata.get('title', 'Untitled')}
Description: {pr_metadata.get('description', 'No description')}
Author: {pr_metadata.get('author', 'Unknown')}

Static Analysis Results:
- Total Issues: {analysis_results.get('total_issues', 0)}
- Critical Issues: {analysis_results.get('critical_issues', 0)}
- Test Status: {analysis_results.get('test_status', 'unknown')}

Files Changed:
"""

        for file in files:
            context += (
                f"\n{file['filename']} (+{file['additions']}/-{file['deletions']})"
            )

            # Add patch if available
            if file.get("patch"):
                context += f"\n```diff\n{file['patch']}\n```\n"

        # Add linter issues
        if analysis_results.get("linter_issues"):
            context += "\n\nLinter Issues Found:\n"
            for issue in analysis_results["linter_issues"][:10]:  # Limit to first 10
                context += f"- {issue['file']}:{issue['line']} - {issue['message']}\n"

        return context

    async def _get_multi_model_reviews(self, context: str) -> Dict[str, Any]:
        """Get reviews from multiple AI models."""
        reviews = {}

        prompt = ChatPromptTemplate.from_messages(
            [
                SystemMessage(
                    content="""You are an expert code reviewer. Review the following pull request and provide:
1. A brief summary of the changes
2. A list of issues found (with severity: high/medium/low)
3. Suggestions for improvement
4. A confidence score (0-1) for your review

Respond in JSON format:
{
    "summary": "string",
    "issues": [
        {
            "severity": "high|medium|low",
            "file": "string",
            "line": number,
            "message": "string"
        }
    ],
    "suggestions": ["string"],
    "confidence": float
}"""
                ),
                HumanMessage(content=context),
            ]
        )

        # Run reviews in parallel
        tasks = []
        for model_name, model in self.models.items():
            if model:
                tasks.append(self._get_model_review(model_name, model, prompt))

        if tasks:
            results = await asyncio.gather(*tasks, return_exceptions=True)

            for model_name, result in zip(self.models.keys(), results):
                if isinstance(result, Exception):
                    self.log_error(f"Model {model_name} failed: {str(result)}")
                else:
                    reviews[model_name] = result

        return reviews

    async def _get_model_review(
        self, model_name: str, model: Any, prompt: ChatPromptTemplate
    ) -> Dict[str, Any]:
        """Get review from a single model."""
        self.log_debug(f"Getting review from {model_name}")

        try:
            # Get response from model
            response = await model.ainvoke(prompt.format_messages())

            # Parse JSON response
            review_text = response.content

            # Try to extract JSON from the response
            import re

            json_match = re.search(r"\{.*\}", review_text, re.DOTALL)
            if json_match:
                review_data = json.loads(json_match.group())
            else:
                # Fallback to basic parsing
                review_data = {
                    "summary": review_text[:200],
                    "issues": [],
                    "suggestions": [],
                    "confidence": 0.5,
                }

            return review_data

        except Exception as e:
            self.log_error(f"Error with {model_name}: {str(e)}")
            raise

    def _aggregate_reviews(self, reviews: Dict[str, Any]) -> Dict[str, Any]:
        """Aggregate reviews from multiple models."""
        if not reviews:
            return {
                "summary": "No AI models available for review",
                "issues": [],
                "patch": None,
                "tests": [],
                "confidence": 0.0,
            }

        # Collect all issues
        all_issues = []
        for model_name, review in reviews.items():
            for issue in review.get("issues", []):
                issue["model"] = model_name
                all_issues.append(issue)

        # Deduplicate and prioritize issues
        unique_issues = self._deduplicate_issues(all_issues)

        # Calculate average confidence
        avg_confidence = sum(r.get("confidence", 0) for r in reviews.values()) / len(
            reviews
        )

        # Combine summaries
        summaries = [r.get("summary", "") for r in reviews.values() if r.get("summary")]
        combined_summary = " ".join(summaries[:2])  # Use first two summaries

        # Combine suggestions
        all_suggestions = []
        for review in reviews.values():
            all_suggestions.extend(review.get("suggestions", []))

        return {
            "summary": combined_summary,
            "issues": unique_issues,
            "patch": None,  # Will be generated by RefactoringAgent
            "tests": [],  # Will be populated by TestRunnerAgent
            "confidence": avg_confidence,
            "suggestions": list(set(all_suggestions))[:5],  # Top 5 unique suggestions
        }

    def _deduplicate_issues(self, issues: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """Deduplicate issues based on file, line, and similarity."""
        unique_issues = []
        seen = set()

        for issue in issues:
            # Create a key for deduplication
            key = (issue.get("file", ""), issue.get("line", 0))

            if key not in seen:
                seen.add(key)
                # Count how many models found this issue
                issue["agreement_count"] = sum(
                    1
                    for i in issues
                    if i.get("file") == issue.get("file")
                    and i.get("line") == issue.get("line")
                )
                unique_issues.append(issue)

        # Sort by severity and agreement count
        severity_order = {"high": 0, "medium": 1, "low": 2}
        unique_issues.sort(
            key=lambda x: (
                severity_order.get(x.get("severity", "low"), 3),
                -x.get("agreement_count", 0),
            )
        )

        return unique_issues[:20]  # Limit to top 20 issues

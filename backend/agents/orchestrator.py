"""Orchestrator for coordinating AI agents."""

from typing import Dict, List, Any, Optional
import asyncio
import logging
from .analysis_agent import AnalysisAgent
from .reviewer_agent import ReviewerAgent
from .refactoring_agent import RefactoringAgent
from .test_runner_agent import TestRunnerAgent
from .pr_commenter_agent import PRCommenterAgent
from .base import AgentResult

logger = logging.getLogger(__name__)


class AgentOrchestrator:
    """Coordinate execution of multiple AI agents."""

    def __init__(self):
        self.analysis_agent = AnalysisAgent()
        self.reviewer_agent = ReviewerAgent()
        self.refactoring_agent = RefactoringAgent()
        self.test_runner_agent = TestRunnerAgent()
        self.pr_commenter_agent = PRCommenterAgent()

    async def process_pull_request(
        self,
        pr_metadata: Dict[str, Any],
        files: List[Dict[str, Any]],
        linter_results: Dict[str, Any],
        test_results: Dict[str, Any],
        installation_id: int,
        repo_path: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Process a pull request through all agents."""
        logger.info(f"Starting orchestrated review for PR #{pr_metadata['pr_number']}")

        results = {"pr_metadata": pr_metadata, "stages": {}}

        try:
            # Stage 1: Analysis
            logger.info("Stage 1: Running analysis agent")
            analysis_result = await self.analysis_agent.execute(
                linter_results=linter_results, test_results=test_results
            )
            results["stages"]["analysis"] = analysis_result.dict()

            if not analysis_result.success:
                logger.error("Analysis failed, stopping pipeline")
                return results

            # Stage 2: Review (parallel with initial refactoring ideas)
            logger.info("Stage 2: Running reviewer agent")
            review_task = asyncio.create_task(
                self.reviewer_agent.execute(
                    files=files,
                    analysis_results=analysis_result.data,
                    pr_metadata=pr_metadata,
                )
            )

            # Wait for review to complete
            review_result = await review_task
            results["stages"]["review"] = review_result.dict()

            if not review_result.success:
                logger.error("Review failed")
                # Still post what we have
                await self._post_partial_results(
                    pr_metadata, analysis_result, None, installation_id
                )
                return results

            # Stage 3: Refactoring (if issues found)
            patches = []
            test_validation_result = None

            if review_result.data.get("issues") and repo_path:
                logger.info("Stage 3: Running refactoring agent")
                refactoring_result = await self.refactoring_agent.execute(
                    files=files, review_results=review_result.data
                )
                results["stages"]["refactoring"] = refactoring_result.dict()

                if refactoring_result.success and refactoring_result.data.get(
                    "patches"
                ):
                    patches = refactoring_result.data["patches"]

                    # Stage 4: Test validation
                    logger.info("Stage 4: Running test validation")
                    test_validation_result = await self.test_runner_agent.execute(
                        patches=patches, repo_path=repo_path
                    )
                    results["stages"]["test_validation"] = test_validation_result.dict()

            # Stage 5: Post comments
            logger.info("Stage 5: Posting review comments")
            comment_result = await self.pr_commenter_agent.execute(
                pr_metadata=pr_metadata,
                review_results=review_result.data,
                test_results=(
                    test_validation_result.data if test_validation_result else None
                ),
                patches=(
                    patches
                    if test_validation_result
                    and test_validation_result.data.get("all_tests_passed")
                    else None
                ),
                installation_id=installation_id,
            )
            results["stages"]["commenting"] = comment_result.dict()

            # Summary
            results["summary"] = {
                "success": True,
                "issues_found": len(review_result.data.get("issues", [])),
                "patches_generated": len(patches),
                "patches_validated": (
                    test_validation_result.data.get("patches_passed", 0)
                    if test_validation_result
                    else 0
                ),
                "fix_pr_created": comment_result.data.get("fix_pr_created", False),
                "fix_pr_number": comment_result.data.get("fix_pr_number"),
            }

            logger.info(f"Orchestrated review complete: {results['summary']}")

        except Exception as e:
            logger.error(f"Orchestration failed: {str(e)}")
            results["error"] = str(e)
            results["summary"] = {"success": False, "error": str(e)}

        return results

    async def _post_partial_results(
        self,
        pr_metadata: Dict[str, Any],
        analysis_result: Optional[AgentResult],
        review_result: Optional[AgentResult],
        installation_id: int,
    ):
        """Post partial results when pipeline fails."""
        try:
            # Format a simple error comment
            partial_review = {
                "summary": "Review partially completed due to errors",
                "issues": [],
                "confidence": 0.0,
            }

            if analysis_result and analysis_result.data:
                partial_review[
                    "summary"
                ] += f"\n\nAnalysis found {analysis_result.data.get('total_issues', 0)} linter issues."

            await self.pr_commenter_agent.execute(
                pr_metadata=pr_metadata,
                review_results=partial_review,
                installation_id=installation_id,
            )
        except Exception as e:
            logger.error(f"Failed to post partial results: {str(e)}")

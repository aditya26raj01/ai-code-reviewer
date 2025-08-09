"""Celery tasks for processing pull request reviews."""

from celery import Celery
from celery.utils.log import get_task_logger
from typing import Dict, Any
import asyncio
from sqlalchemy.orm import Session

from ..config import settings
from ..models import get_db, PullRequest, Review, RefactoringPatch, ReviewStatus
from ..services.github_service import GitHubService
from ..services.linter_service import LinterService
from ..services.test_runner_service import TestRunnerService
from ..agents.orchestrator import AgentOrchestrator

# Initialize Celery
celery_app = Celery(
    "ai_code_reviewer",
    broker=settings.celery_broker_url,
    backend=settings.celery_result_backend,
)

# Configure Celery
celery_app.conf.update(
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",
    timezone="UTC",
    enable_utc=True,
    task_soft_time_limit=1800,  # 30 minutes soft limit
    task_time_limit=2100,  # 35 minutes hard limit
)

logger = get_task_logger(__name__)


@celery_app.task(bind=True, max_retries=3)
def process_pull_request(self, pr_id: int, installation_id: int):
    """Process a pull request for AI review."""
    try:
        logger.info(f"Starting review for PR ID: {pr_id}")

        # Get PR from database
        db = next(get_db())
        try:
            pr = db.query(PullRequest).filter_by(id=pr_id).first()
            if not pr:
                logger.error(f"PR with ID {pr_id} not found")
                return

            # Update status
            pr.status = ReviewStatus.IN_PROGRESS
            db.commit()

            # Run async processing
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)

            try:
                result = loop.run_until_complete(
                    _process_pr_async(pr, installation_id, db)
                )

                # Update status based on result
                if result.get("summary", {}).get("success"):
                    pr.status = ReviewStatus.COMPLETED
                else:
                    pr.status = ReviewStatus.FAILED

                db.commit()

                logger.info(f"Review completed for PR ID: {pr_id}")
                return result

            finally:
                loop.close()

        finally:
            db.close()

    except Exception as e:
        logger.error(f"Error processing PR {pr_id}: {str(e)}")

        # Retry with exponential backoff
        retry_count = self.request.retries
        if retry_count < self.max_retries:
            retry_delay = 60 * (2**retry_count)  # 1min, 2min, 4min
            logger.info(f"Retrying in {retry_delay} seconds...")
            raise self.retry(countdown=retry_delay)

        # Mark as failed after max retries
        db = next(get_db())
        try:
            pr = db.query(PullRequest).filter_by(id=pr_id).first()
            if pr:
                pr.status = ReviewStatus.FAILED
                db.commit()
        finally:
            db.close()

        raise


async def _process_pr_async(
    pr: PullRequest, installation_id: int, db: Session
) -> Dict[str, Any]:
    """Async function to process PR through all stages."""

    # Initialize services
    github_service = GitHubService(installation_id)
    linter_service = LinterService()
    test_runner_service = TestRunnerService()
    orchestrator = AgentOrchestrator()

    try:
        # Fetch PR files and diff
        logger.info(
            f"Fetching PR files for {pr.repo_owner}/{pr.repo_name}#{pr.pr_number}"
        )
        files = github_service.get_pr_files(pr.repo_owner, pr.repo_name, pr.pr_number)

        # Prepare repo path (this would be the actual cloned repo in production)
        # For now, we'll work with the files we have
        repo_path = None  # Would be set to cloned repo path

        # Run linters on changed files
        logger.info("Running linters")
        linter_results = await linter_service.lint_files(files, repo_path)

        # Run tests (if repo is cloned)
        test_results = {}
        if repo_path:
            logger.info("Running tests")
            changed_files = [f["filename"] for f in files]
            test_results = await test_runner_service.run_tests(repo_path, changed_files)

        # Process through orchestrator
        logger.info("Running AI agents")
        pr_metadata = {
            "pr_number": pr.pr_number,
            "repo_owner": pr.repo_owner,
            "repo_name": pr.repo_name,
            "title": pr.title,
            "description": pr.description,
            "author": pr.author,
        }

        orchestration_result = await orchestrator.process_pull_request(
            pr_metadata=pr_metadata,
            files=files,
            linter_results=linter_results,
            test_results=test_results,
            installation_id=installation_id,
            repo_path=repo_path,
        )

        # Save results to database
        if orchestration_result.get("stages", {}).get("review"):
            review_data = orchestration_result["stages"]["review"]["data"]

            review = Review(
                pr_id=pr.id,
                summary=review_data.get("summary", ""),
                issues=review_data.get("issues", []),
                patch=review_data.get("patch"),
                tests=review_data.get("tests", []),
                confidence=review_data.get("confidence", 0.0),
                models_used=orchestration_result["stages"]["review"]
                .get("metadata", {})
                .get("models_used", []),
                analysis_time=0.0,  # Would track actual time
                tokens_used=0,  # Would track actual tokens
            )
            db.add(review)
            db.commit()

            # Save patches if any
            if orchestration_result.get("stages", {}).get("refactoring"):
                patches = orchestration_result["stages"]["refactoring"]["data"].get(
                    "patches", []
                )
                test_results = (
                    orchestration_result.get("stages", {})
                    .get("test_validation", {})
                    .get("data", {})
                )

                for patch in patches:
                    patch_record = RefactoringPatch(
                        review_id=review.id,
                        pr_id=pr.id,
                        file_path=patch["file_path"],
                        original_content=patch.get("original_content", ""),
                        patched_content=patch.get("patched_content", ""),
                        unified_diff=patch.get("unified_diff", ""),
                        tests_passed=[],  # Would extract from test results
                        tests_failed=[],
                        test_coverage=0.0,
                        applied="pending",
                    )

                    # Update if fix PR was created
                    if orchestration_result.get("summary", {}).get("fix_pr_number"):
                        patch_record.applied = "success"
                        patch_record.pr_created = str(
                            orchestration_result["summary"]["fix_pr_number"]
                        )

                    db.add(patch_record)

                db.commit()

        return orchestration_result

    except Exception as e:
        logger.error(f"Error in async processing: {str(e)}")
        raise


# Additional helper tasks


@celery_app.task
def cleanup_old_reviews(days: int = 30):
    """Clean up old review records."""
    from datetime import datetime, timedelta

    db = next(get_db())
    try:
        cutoff_date = datetime.utcnow() - timedelta(days=days)

        # Delete old reviews
        deleted = db.query(Review).filter(Review.created_at < cutoff_date).delete()

        db.commit()
        logger.info(f"Deleted {deleted} old reviews")

    finally:
        db.close()


@celery_app.task
def generate_review_metrics():
    """Generate metrics for review performance."""
    db = next(get_db())
    try:
        # Calculate various metrics
        from sqlalchemy import func

        metrics = {
            "total_reviews": db.query(Review).count(),
            "avg_confidence": db.query(func.avg(Review.confidence)).scalar() or 0,
            "avg_issues_per_pr": db.query(
                func.avg(func.json_array_length(Review.issues))
            ).scalar()
            or 0,
            "total_patches_created": db.query(RefactoringPatch).count(),
            "successful_patches": db.query(RefactoringPatch)
            .filter_by(applied="success")
            .count(),
        }

        logger.info(f"Generated metrics: {metrics}")
        return metrics

    finally:
        db.close()

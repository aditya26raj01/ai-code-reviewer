"""GitHub webhook routes."""

from fastapi import APIRouter, Request, HTTPException, Header, BackgroundTasks
from typing import Optional
import json
import logging
from ..config import settings
from ..utils.github_auth import github_auth
from ..tasks.review_tasks import process_pull_request
from ..models import get_db, PullRequest, ReviewStatus
from sqlalchemy.orm import Session

logger = logging.getLogger(__name__)
router = APIRouter()


@router.post("/webhook/github")
async def github_webhook(
    request: Request,
    background_tasks: BackgroundTasks,
    x_hub_signature_256: Optional[str] = Header(None),
    x_github_event: Optional[str] = Header(None),
):
    """Handle GitHub webhook events."""
    logger.info(f"🔗 Webhook received: Event={x_github_event}")

    if not x_hub_signature_256:
        logger.error("❌ Missing signature header")
        raise HTTPException(status_code=401, detail="Missing signature")

    # Get raw payload
    payload = await request.body()

    # Verify signature (temporarily disabled for testing)
    logger.info("🔐 Checking webhook signature...")
    if settings.debug:
        logger.warning("⚠️ DEBUG MODE: Skipping signature verification")
    else:
        if not github_auth.verify_webhook_signature(payload, x_hub_signature_256):
            logger.error("❌ Invalid webhook signature")
            raise HTTPException(status_code=401, detail="Invalid signature")
        logger.info("✅ Signature verified")

    # Parse payload
    logger.info("📄 Parsing JSON payload...")
    data = json.loads(payload)

    # Handle pull request events
    if x_github_event == "pull_request":
        action = data.get("action")
        logger.info(f"📋 PR event action: {action}")

        if action in ["opened", "reopened", "synchronize"]:
            logger.info("🎯 Processing PR event...")
            # Extract PR information
            pr_data = data["pull_request"]
            repo_data = data["repository"]
            installation_id = data["installation"]["id"]

            logger.info(
                f"📁 Repository: {repo_data['owner']['login']}/{repo_data['name']}"
            )
            logger.info(f"🔢 PR Number: {pr_data['number']}")
            logger.info(f"⚙️ Installation ID: {installation_id}")

            # Create or update PR record
            logger.info("💾 Connecting to database...")
            db = next(get_db())
            try:
                logger.info("🔍 Checking for existing PR record...")
                pr = (
                    db.query(PullRequest)
                    .filter_by(
                        repo_owner=repo_data["owner"]["login"],
                        repo_name=repo_data["name"],
                        pr_number=pr_data["number"],
                    )
                    .first()
                )

                if not pr:
                    logger.info("➕ Creating new PR record...")
                    pr = PullRequest(
                        repo_owner=repo_data["owner"]["login"],
                        repo_name=repo_data["name"],
                        pr_number=pr_data["number"],
                        title=pr_data["title"],
                        description=pr_data["body"] or "",
                        author=pr_data["user"]["login"],
                        status=ReviewStatus.PENDING,
                        github_data=pr_data,
                    )
                    db.add(pr)
                    logger.info("✅ PR record created")
                else:
                    logger.info("🔄 Updating existing PR record...")
                    pr.status = ReviewStatus.PENDING
                    pr.github_data = pr_data

                logger.info("💾 Committing to database...")
                db.commit()
                logger.info(f"✅ Database commit successful. PR ID: {pr.id}")

                # Enqueue review task
                logger.info("📤 Enqueueing Celery task...")
                task = process_pull_request.delay(
                    pr_id=pr.id, installation_id=installation_id
                )
                logger.info(f"✅ Task enqueued with ID: {task.id}")

                logger.info(
                    f"🎉 Enqueued review for PR #{pr.pr_number} in {pr.repo_owner}/{pr.repo_name}"
                )

            except Exception as e:
                logger.error(f"❌ Error processing webhook: {e}")
                logger.error(f"Exception type: {type(e).__name__}")
                import traceback

                logger.error(f"Traceback: {traceback.format_exc()}")
                db.rollback()
                raise HTTPException(status_code=500, detail="Internal server error")
            finally:
                db.close()
    else:
        logger.info(f"ℹ️ Ignoring event: {x_github_event}")

    logger.info("✅ Webhook processing completed")
    return {"status": "ok"}

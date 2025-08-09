"""GitHub webhook routes."""

from fastapi import APIRouter, Request, HTTPException, Header, BackgroundTasks
from typing import Optional
import json
import logging
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
    if not x_hub_signature_256:
        raise HTTPException(status_code=401, detail="Missing signature")

    # Get raw payload
    payload = await request.body()

    # Verify signature
    if not github_auth.verify_webhook_signature(payload, x_hub_signature_256):
        raise HTTPException(status_code=401, detail="Invalid signature")

    # Parse payload
    data = json.loads(payload)

    # Handle pull request events
    if x_github_event == "pull_request":
        action = data.get("action")
        if action in ["opened", "reopened", "synchronize"]:
            # Extract PR information
            pr_data = data["pull_request"]
            repo_data = data["repository"]
            installation_id = data["installation"]["id"]

            # Create or update PR record
            db = next(get_db())
            try:
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
                else:
                    pr.status = ReviewStatus.PENDING
                    pr.github_data = pr_data

                db.commit()

                # Enqueue review task
                process_pull_request.delay(pr_id=pr.id, installation_id=installation_id)

                logger.info(
                    f"Enqueued review for PR #{pr.pr_number} in {pr.repo_owner}/{pr.repo_name}"
                )

            except Exception as e:
                logger.error(f"Error processing webhook: {e}")
                db.rollback()
                raise HTTPException(status_code=500, detail="Internal server error")
            finally:
                db.close()

    return {"status": "ok"}

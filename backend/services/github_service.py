"""GitHub API service."""

from github import Github
from typing import List, Dict, Any, Optional
import base64
import logging
from ..utils.github_auth import github_auth

logger = logging.getLogger(__name__)


class GitHubService:
    """Service for GitHub API interactions."""

    def __init__(self, installation_id: int):
        self.installation_id = installation_id
        self.client = github_auth.get_github_client(installation_id)

    def get_pull_request(self, owner: str, repo: str, pr_number: int):
        """Get pull request details."""
        repo_obj = self.client.get_repo(f"{owner}/{repo}")
        return repo_obj.get_pull(pr_number)

    def get_pr_diff(self, owner: str, repo: str, pr_number: int) -> str:
        """Get pull request diff."""
        pr = self.get_pull_request(owner, repo, pr_number)
        return pr.get_diff()

    def get_pr_files(
        self, owner: str, repo: str, pr_number: int
    ) -> List[Dict[str, Any]]:
        """Get list of files changed in PR."""
        pr = self.get_pull_request(owner, repo, pr_number)
        files = []

        for file in pr.get_files():
            file_data = {
                "filename": file.filename,
                "status": file.status,
                "additions": file.additions,
                "deletions": file.deletions,
                "changes": file.changes,
                "patch": file.patch if hasattr(file, "patch") else None,
            }

            # Get file content if it exists
            if file.status != "removed":
                try:
                    repo_obj = self.client.get_repo(f"{owner}/{repo}")
                    content = repo_obj.get_contents(file.filename, ref=pr.head.sha)
                    if content.encoding == "base64":
                        file_data["content"] = base64.b64decode(content.content).decode(
                            "utf-8"
                        )
                    else:
                        file_data["content"] = content.content
                except Exception as e:
                    logger.warning(f"Could not get content for {file.filename}: {e}")
                    file_data["content"] = None
            else:
                file_data["content"] = None

            files.append(file_data)

        return files

    def create_pr_review(
        self,
        owner: str,
        repo: str,
        pr_number: int,
        body: str,
        comments: List[Dict[str, Any]] = None,
    ):
        """Create a PR review with comments."""
        pr = self.get_pull_request(owner, repo, pr_number)

        # Convert comments to GitHub format
        review_comments = []
        if comments:
            for comment in comments:
                review_comments.append(
                    {
                        "path": comment["file"],
                        "line": comment.get("line", 1),
                        "body": comment["message"],
                    }
                )

        # Create review
        pr.create_review(body=body, event="COMMENT", comments=review_comments)

    def create_issue_comment(self, owner: str, repo: str, pr_number: int, body: str):
        """Create a simple comment on the PR."""
        pr = self.get_pull_request(owner, repo, pr_number)
        pr.create_issue_comment(body)

    def create_pull_request(
        self,
        owner: str,
        repo: str,
        title: str,
        body: str,
        head: str,
        base: str = "main",
    ) -> Optional[int]:
        """Create a new pull request."""
        try:
            repo_obj = self.client.get_repo(f"{owner}/{repo}")
            pr = repo_obj.create_pull(title=title, body=body, head=head, base=base)
            return pr.number
        except Exception as e:
            logger.error(f"Failed to create PR: {e}")
            return None

    def create_branch(
        self, owner: str, repo: str, branch_name: str, base_sha: str
    ) -> bool:
        """Create a new branch."""
        try:
            repo_obj = self.client.get_repo(f"{owner}/{repo}")
            ref = repo_obj.create_git_ref(ref=f"refs/heads/{branch_name}", sha=base_sha)
            return True
        except Exception as e:
            logger.error(f"Failed to create branch: {e}")
            return False

    def update_file(
        self,
        owner: str,
        repo: str,
        file_path: str,
        content: str,
        message: str,
        branch: str,
        sha: str = None,
    ):
        """Update or create a file in the repository."""
        repo_obj = self.client.get_repo(f"{owner}/{repo}")

        # Get current file SHA if not provided
        if sha is None and file_path:
            try:
                current_file = repo_obj.get_contents(file_path, ref=branch)
                sha = current_file.sha
            except:
                # File doesn't exist, will create new
                sha = None

        # Encode content
        encoded_content = base64.b64encode(content.encode("utf-8")).decode("utf-8")

        if sha:
            # Update existing file
            repo_obj.update_file(
                path=file_path,
                message=message,
                content=encoded_content,
                sha=sha,
                branch=branch,
            )
        else:
            # Create new file
            repo_obj.create_file(
                path=file_path, message=message, content=encoded_content, branch=branch
            )

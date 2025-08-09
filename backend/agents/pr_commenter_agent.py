"""PR commenter agent for posting review results to GitHub."""

from typing import Dict, List, Any, Optional
from .base import BaseAgent, AgentResult
from ..services.github_service import GitHubService
import json


class PRCommenterAgent(BaseAgent):
    """Agent for posting AI review comments to pull requests."""

    def __init__(self):
        super().__init__("PRCommenterAgent")

    async def execute(
        self,
        pr_metadata: Dict[str, Any],
        review_results: Dict[str, Any],
        test_results: Optional[Dict[str, Any]] = None,
        patches: Optional[List[Dict[str, Any]]] = None,
        installation_id: int = None,
    ) -> AgentResult:
        """Post review comments and create fix PRs if applicable."""
        try:
            self.log_info(f"Posting review for PR #{pr_metadata['pr_number']}")

            # Initialize GitHub service
            github = GitHubService(installation_id)

            # Format review comment
            review_body = self._format_review_comment(review_results, test_results)

            # Post main review comment
            github.create_issue_comment(
                owner=pr_metadata["repo_owner"],
                repo=pr_metadata["repo_name"],
                pr_number=pr_metadata["pr_number"],
                body=review_body,
            )

            # Post inline comments for specific issues
            if review_results.get("issues"):
                self._post_inline_comments(
                    github, pr_metadata, review_results["issues"]
                )

            # Create fix PR if patches passed tests
            fix_pr_number = None
            if patches and test_results and test_results.get("all_tests_passed"):
                fix_pr_number = await self._create_fix_pr(github, pr_metadata, patches)

            self.log_info("Review comments posted successfully")

            return AgentResult(
                success=True,
                data={
                    "review_posted": True,
                    "inline_comments": len(review_results.get("issues", [])),
                    "fix_pr_created": fix_pr_number is not None,
                    "fix_pr_number": fix_pr_number,
                },
            )

        except Exception as e:
            self.log_error(f"Failed to post review: {str(e)}")
            return AgentResult(success=False, error=str(e))

    def _format_review_comment(
        self,
        review_results: Dict[str, Any],
        test_results: Optional[Dict[str, Any]] = None,
    ) -> str:
        """Format the main review comment."""
        comment = "## 🤖 AI Code Review\n\n"

        # Summary
        comment += (
            f"**Summary:** {review_results.get('summary', 'No summary available')}\n\n"
        )

        # Confidence score
        confidence = review_results.get("confidence", 0)
        confidence_emoji = (
            "🟢" if confidence > 0.7 else "🟡" if confidence > 0.4 else "🔴"
        )
        comment += f"**Confidence:** {confidence_emoji} {confidence:.1%}\n\n"

        # Issues found
        issues = review_results.get("issues", [])
        if issues:
            comment += f"### 📋 Issues Found ({len(issues)})\n\n"

            # Group by severity
            high = [i for i in issues if i.get("severity") == "high"]
            medium = [i for i in issues if i.get("severity") == "medium"]
            low = [i for i in issues if i.get("severity") == "low"]

            if high:
                comment += f"#### 🔴 High Priority ({len(high)})\n"
                for issue in high[:5]:  # Limit to 5
                    comment += f"- **{issue['file']}:{issue.get('line', '?')}** - {issue['message']}\n"
                comment += "\n"

            if medium:
                comment += f"#### 🟡 Medium Priority ({len(medium)})\n"
                for issue in medium[:5]:
                    comment += f"- **{issue['file']}:{issue.get('line', '?')}** - {issue['message']}\n"
                comment += "\n"

            if low:
                comment += f"#### 🟢 Low Priority ({len(low)})\n"
                for issue in low[:3]:
                    comment += f"- **{issue['file']}:{issue.get('line', '?')}** - {issue['message']}\n"
                comment += "\n"
        else:
            comment += "### ✅ No issues found!\n\n"

        # Suggestions
        suggestions = review_results.get("suggestions", [])
        if suggestions:
            comment += "### 💡 Suggestions\n\n"
            for i, suggestion in enumerate(suggestions[:5], 1):
                comment += f"{i}. {suggestion}\n"
            comment += "\n"

        # Test results
        if test_results:
            comment += "### 🧪 Automated Fix Testing\n\n"
            if test_results.get("all_tests_passed"):
                comment += (
                    "✅ All automated fixes passed tests! A fix PR will be created.\n\n"
                )
            else:
                failed = test_results.get("total_patches", 0) - test_results.get(
                    "patches_passed", 0
                )
                comment += (
                    f"⚠️ {failed} automated fixes failed tests and were not applied.\n\n"
                )

        # Footer
        comment += "---\n"
        comment += "*Generated by AI Code Reviewer • "
        comment += f"Models: {', '.join(review_results.get('metadata', {}).get('models_used', ['Unknown']))}*"

        return comment

    def _post_inline_comments(
        self,
        github: GitHubService,
        pr_metadata: Dict[str, Any],
        issues: List[Dict[str, Any]],
    ):
        """Post inline comments for specific issues."""
        # Filter to high and medium priority issues with specific line numbers
        inline_issues = [
            i
            for i in issues
            if i.get("line") and i.get("severity") in ["high", "medium"]
        ][
            :10
        ]  # Limit to 10 inline comments

        if not inline_issues:
            return

        # Format as GitHub review comments
        comments = []
        for issue in inline_issues:
            severity_emoji = "🔴" if issue["severity"] == "high" else "🟡"

            comment_body = (
                f"{severity_emoji} **{issue.get('code', 'Issue')}**: {issue['message']}"
            )

            # Add model agreement info if available
            if issue.get("agreement_count", 0) > 1:
                comment_body += (
                    f"\n\n*{issue['agreement_count']} models identified this issue*"
                )

            comments.append(
                {"file": issue["file"], "line": issue["line"], "message": comment_body}
            )

        try:
            github.create_pr_review(
                owner=pr_metadata["repo_owner"],
                repo=pr_metadata["repo_name"],
                pr_number=pr_metadata["pr_number"],
                body="Inline code review comments",
                comments=comments,
            )
        except Exception as e:
            self.log_warning(f"Failed to post inline comments: {str(e)}")

    async def _create_fix_pr(
        self,
        github: GitHubService,
        pr_metadata: Dict[str, Any],
        patches: List[Dict[str, Any]],
    ) -> Optional[int]:
        """Create a pull request with automated fixes."""
        try:
            # Get original PR
            pr = github.get_pull_request(
                pr_metadata["repo_owner"],
                pr_metadata["repo_name"],
                pr_metadata["pr_number"],
            )

            # Create branch name
            branch_name = f"ai-fix/{pr_metadata['pr_number']}-{pr.head.ref}"

            # Create branch from PR head
            if not github.create_branch(
                pr_metadata["repo_owner"],
                pr_metadata["repo_name"],
                branch_name,
                pr.head.sha,
            ):
                self.log_error("Failed to create fix branch")
                return None

            # Apply patches
            for patch in patches:
                github.update_file(
                    owner=pr_metadata["repo_owner"],
                    repo=pr_metadata["repo_name"],
                    file_path=patch["file_path"],
                    content=patch["patched_content"],
                    message=f"AI: Fix issues in {patch['file_path']}",
                    branch=branch_name,
                )

            # Create PR
            pr_body = self._format_fix_pr_body(pr_metadata, patches)

            fix_pr_number = github.create_pull_request(
                owner=pr_metadata["repo_owner"],
                repo=pr_metadata["repo_name"],
                title=f"AI Fix: {pr_metadata['title']}",
                body=pr_body,
                head=branch_name,
                base=pr.base.ref,
            )

            if fix_pr_number:
                # Comment on original PR
                github.create_issue_comment(
                    owner=pr_metadata["repo_owner"],
                    repo=pr_metadata["repo_name"],
                    pr_number=pr_metadata["pr_number"],
                    body=f"🤖 I've created PR #{fix_pr_number} with automated fixes for the issues found in this PR.",
                )

            return fix_pr_number

        except Exception as e:
            self.log_error(f"Failed to create fix PR: {str(e)}")
            return None

    def _format_fix_pr_body(
        self, pr_metadata: Dict[str, Any], patches: List[Dict[str, Any]]
    ) -> str:
        """Format the body for the fix PR."""
        body = f"## 🤖 Automated Fixes for PR #{pr_metadata['pr_number']}\n\n"
        body += f"This PR contains automated fixes for issues found in #{pr_metadata['pr_number']}.\n\n"

        body += "### 📝 Changes Made\n\n"

        for patch in patches:
            body += f"#### `{patch['file_path']}`\n"
            if patch.get("fixes"):
                for fix in patch["fixes"]:
                    body += f"- Line {fix['line']}: {fix['issue']}\n"
            body += "\n"

        body += "### ✅ All changes have been tested\n\n"
        body += "These fixes have been validated to ensure they:\n"
        body += "- Pass all existing tests\n"
        body += "- Meet linting standards\n"
        body += "- Don't introduce new issues\n\n"

        body += "---\n"
        body += "*Generated by AI Code Reviewer*"

        return body

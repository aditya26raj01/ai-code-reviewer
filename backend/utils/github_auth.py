"""GitHub authentication utilities."""

import jwt
import time
import hmac
import hashlib
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.backends import default_backend
from github import Github, GithubIntegration
from ..config import settings


class GitHubAuth:
    """Handle GitHub App authentication."""

    def __init__(self):
        self.app_id = settings.github_app_id
        self.private_key_path = settings.github_app_private_key_path
        self.webhook_secret = settings.github_webhook_secret
        self._private_key = None
        self._integration = None

    @property
    def private_key(self):
        """Load private key lazily."""
        if self._private_key is None:
            with open(self.private_key_path, "rb") as key_file:
                self._private_key = serialization.load_pem_private_key(
                    key_file.read(), password=None, backend=default_backend()
                )
        return self._private_key

    @property
    def private_key_pem(self):
        """Get private key as PEM string for JWT signing."""
        with open(self.private_key_path, "r") as key_file:
            return key_file.read()

    @property
    def integration(self):
        """Get GitHub Integration instance."""
        if self._integration is None:
            self._integration = GithubIntegration(self.app_id, self.private_key_pem)
        return self._integration

    def generate_jwt(self):
        """Generate JWT for GitHub App authentication."""
        # GitHub Apps JWT expires after 10 minutes max
        now = int(time.time())
        payload = {"iat": now, "exp": now + 600, "iss": str(self.app_id)}  # 10 minutes

        return jwt.encode(payload, self.private_key_pem, algorithm="RS256")

    def get_installation_token(self, installation_id: int):
        """Get installation access token."""
        return self.integration.get_access_token(installation_id)

    def get_github_client(self, installation_id: int):
        """Get authenticated GitHub client for an installation."""
        token = self.get_installation_token(installation_id)
        return Github(token.token)

    def verify_webhook_signature(self, payload: bytes, signature: str) -> bool:
        """Verify GitHub webhook signature."""
        expected_signature = (
            "sha256="
            + hmac.new(
                self.webhook_secret.encode("utf-8"), payload, hashlib.sha256
            ).hexdigest()
        )

        return hmac.compare_digest(expected_signature, signature)


# Global instance
github_auth = GitHubAuth()

"""Database models for AI Code Reviewer."""

from sqlalchemy import Column, Integer, String, Text, DateTime, Float, JSON, Enum
from sqlalchemy.sql import func
from datetime import datetime
import enum
from .database import Base


class ReviewStatus(enum.Enum):
    """Review status enumeration."""

    PENDING = "pending"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    FAILED = "failed"


class IssueSeverity(enum.Enum):
    """Issue severity levels."""

    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"


class PullRequest(Base):
    """Pull request model."""

    __tablename__ = "pull_requests"

    id = Column(Integer, primary_key=True, index=True)
    repo_owner = Column(String, nullable=False)
    repo_name = Column(String, nullable=False)
    pr_number = Column(Integer, nullable=False)
    title = Column(String)
    description = Column(Text)
    author = Column(String)
    status = Column(Enum(ReviewStatus), default=ReviewStatus.PENDING)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())

    # GitHub metadata
    github_data = Column(JSON)

    # Unique constraint
    __table_args__ = (
        # Use UniqueConstraint instead of unique_together
        # UniqueConstraint("repo_owner", "repo_name", "pr_number"),
    )


class Review(Base):
    """AI review results model."""

    __tablename__ = "reviews"

    id = Column(Integer, primary_key=True, index=True)
    pr_id = Column(Integer, index=True)
    summary = Column(Text)
    issues = Column(JSON)  # List of issues found
    patch = Column(Text)  # Suggested patch
    tests = Column(JSON)  # Test results
    confidence = Column(Float)

    # Metadata
    models_used = Column(JSON)  # Which AI models were used
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    # Performance metrics
    analysis_time = Column(Float)  # Time taken in seconds
    tokens_used = Column(Integer)


class RefactoringPatch(Base):
    """Refactoring patches model."""

    __tablename__ = "refactoring_patches"

    id = Column(Integer, primary_key=True, index=True)
    review_id = Column(Integer, index=True)
    pr_id = Column(Integer, index=True)

    # Patch details
    file_path = Column(String)
    original_content = Column(Text)
    patched_content = Column(Text)
    unified_diff = Column(Text)

    # Test results
    tests_passed = Column(JSON)
    tests_failed = Column(JSON)
    test_coverage = Column(Float)

    # Status
    applied = Column(String, default="pending")  # pending, success, failed
    pr_created = Column(String)  # PR number if created

    created_at = Column(DateTime(timezone=True), server_default=func.now())

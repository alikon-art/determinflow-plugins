"""Domain errors for the novel production API."""

from __future__ import annotations


class NovelError(Exception):
    error = "novel_error"
    status_code = 500

    def __init__(self, message: str, details: dict | None = None):
        super().__init__(message)
        self.message = message
        self.details = details or {}


class NotFoundError(NovelError):
    error = "not_found"
    status_code = 404


class VersionConflictError(NovelError):
    error = "version_conflict"
    status_code = 409


class InvalidResourceError(NovelError):
    error = "invalid_resource"
    status_code = 400


class JobAlreadyRunningError(NovelError):
    error = "job_already_running"
    status_code = 409


class WorkflowStartError(NovelError):
    error = "workflow_start_failed"
    status_code = 502

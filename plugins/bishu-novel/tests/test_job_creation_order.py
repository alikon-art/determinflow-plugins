"""Novel Job creation must persist its business identity before execution."""

from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass
from typing import Any

import pytest
from fastapi import HTTPException

from ai_company_plugin_bishu_novel.backend import routes
from ai_company_plugin_bishu_novel.backend.novel import jobs as jobs_module
from ai_company_plugin_bishu_novel.backend.novel.errors import (
    JobAlreadyRunningError,
    WorkflowStartError,
)
from ai_company_plugin_bishu_novel.backend.novel.jobs import NovelJobService
from ai_company_plugin_bishu_novel.backend.novel.resource_ids import (
    configure_resource_resolver,
)
from ai_company_plugin_bishu_novel.backend.novel.workflow_adapter import (
    WorkflowAdapter,
    WorkflowHandle,
)


class _Context:
    def __init__(self, value: Any):
        self.value = value

    async def __aenter__(self):
        return self.value

    async def __aexit__(self, exc_type, exc, tb):
        return False


@pytest.fixture(autouse=True)
def _configured_resource_resolver():
    configure_resource_resolver(
        lambda _resource_type, local_id, **_kwargs: f"novel-{local_id}"
    )
    yield
    configure_resource_resolver(None)


class _Transaction:
    def __init__(self, connection: "_Connection"):
        self.connection = connection

    async def __aenter__(self):
        self.connection.trace.append("begin")
        return self

    async def __aexit__(self, exc_type, exc, tb):
        self.connection.trace.append("rollback" if exc_type else "commit")
        return False


class _Pool:
    def __init__(self, connection: "_Connection"):
        self.connection = connection

    def acquire(self):
        return _Context(self.connection)


class _Connection:
    def __init__(
        self, *, existing: dict[str, Any] | None = None, fail_event: bool = False
    ):
        self.trace: list[str] = []
        self.existing = existing
        self.fail_event = fail_event
        self.inserted_job: dict[str, Any] | None = None
        self.job_status: str | None = None
        self.event_types: list[str] = []

    def transaction(self):
        return _Transaction(self)

    async def fetchrow(self, query: str, *args):
        normalized = " ".join(query.split())
        if "FROM novel_job" in normalized and "idempotency_key" in normalized:
            if self.existing and self.existing.get("idempotency_key") == args[-1]:
                return self.existing
            return None
        if (
            "FROM novel_job" in normalized
            and "status IN ('queued', 'running')" in normalized
        ):
            if self.existing and self.existing.get("status") in {"queued", "running"}:
                return self.existing
            return None
        if "INSERT INTO novel_job_event" in normalized:
            if self.fail_event:
                raise RuntimeError("event insert failed")
            self.trace.append("insert_event")
            self.event_types.append(str(args[1]))
            return {"id": len(self.event_types)}
        raise AssertionError(f"unexpected fetchrow: {normalized}")

    async def execute(self, query: str, *args):
        normalized = " ".join(query.split())
        if "pg_advisory_xact_lock" in normalized:
            self.trace.append("lock")
            return "SELECT 1"
        if "INSERT INTO novel_job" in normalized:
            self.trace.append("insert_job")
            self.inserted_job = {
                "job_id": str(args[0]),
                "book_id": str(args[1]),
                "operation": str(args[2]),
                "status": "queued",
                "workflow_id": str(args[3]),
                "workflow_task_id": str(args[4]),
                "request_payload": json.loads(args[5]),
                "actor_ref": args[6],
                "request_id": args[7],
                "idempotency_key": args[8],
            }
            self.job_status = "queued"
            return "INSERT 0 1"
        if "SET status='failed'" in normalized:
            self.trace.append("mark_failed")
            self.job_status = "failed"
            return "UPDATE 1"
        if "SET post_hoc_status = 'failed'" in normalized:
            self.trace.append("post_hoc_failed")
            return "UPDATE 1"
        if "UPDATE chapter SET post_hoc_status" in normalized:
            self.trace.append("post_hoc_status")
            return "UPDATE 1"
        raise AssertionError(f"unexpected execute: {normalized}")


@dataclass
class _AdapterState:
    trace: list[str]
    fail_start: bool = False


class _TrackingAdapter:
    state: _AdapterState

    def __init__(self, _manager):
        pass

    def prepare_workflow(self, workflow_id: str, **_kwargs) -> WorkflowHandle:
        self.state.trace.append("prepare")
        return WorkflowHandle(workflow_id=workflow_id, task_id="task-prepared")

    async def start_prepared_workflow(self, handle: WorkflowHandle) -> WorkflowHandle:
        self.state.trace.append("start")
        if self.state.fail_start:
            raise RuntimeError("start failed")
        return handle

    async def discard_prepared_workflow(self, _handle: WorkflowHandle) -> bool:
        self.state.trace.append("discard")
        return True


def _run_create(
    monkeypatch,
    connection: _Connection,
    *,
    payload: dict[str, Any] | None = None,
    operation: str = "world_build",
    idempotency_key: str = "request-1",
    fail_start: bool = False,
) -> dict:
    adapter_state = _AdapterState(connection.trace, fail_start=fail_start)
    _TrackingAdapter.state = adapter_state

    async def fake_get_pool():
        return _Pool(connection)

    monkeypatch.setattr(jobs_module, "get_pool", fake_get_pool)
    monkeypatch.setattr(jobs_module, "WorkflowAdapter", _TrackingAdapter)
    return asyncio.run(
        NovelJobService().create_job(
            book_id="00000000-0000-0000-0000-000000000001",
            operation=operation,
            request_payload=payload or {"premise": "潮汐"},
            manager=object(),
            actor_ref="portal-user-1",
            request_id="portal-request-1",
            idempotency_key=idempotency_key,
        )
    )


def test_workflow_adapter_prepares_without_running_then_starts_explicitly():
    class Manager:
        def __init__(self):
            self.calls: list[str] = []

        def get_workflow(self, _workflow_id):
            return {"definition": {"variables": []}}

        def create_task(self, workflow_id, **_kwargs):
            self.calls.append(f"create:{workflow_id}")
            return {"task_id": "task-1"}

        async def run_task(self, workflow_id, task_id):
            self.calls.append(f"run:{workflow_id}:{task_id}")
            return {"success": True}

        async def stop_task(self, workflow_id, task_id):
            self.calls.append(f"stop:{workflow_id}:{task_id}")
            return {"success": True}

    manager = Manager()
    adapter = WorkflowAdapter(manager)
    handle = adapter.prepare_workflow("wf-demo", parameter_values={})

    assert manager.calls == ["create:wf-demo"]
    assert asyncio.run(adapter.start_prepared_workflow(handle)) == handle
    assert manager.calls == ["create:wf-demo", "run:wf-demo:task-1"]


def test_job_transaction_commits_before_workflow_starts(monkeypatch):
    connection = _Connection()

    result = _run_create(monkeypatch, connection)

    assert result["status"] == "queued"
    assert connection.trace == [
        "prepare",
        "begin",
        "lock",
        "insert_job",
        "insert_event",
        "commit",
        "start",
    ]


def test_job_transaction_failure_discards_pending_task_without_starting(monkeypatch):
    connection = _Connection(fail_event=True)

    with pytest.raises(RuntimeError, match="event insert failed"):
        _run_create(monkeypatch, connection)

    assert connection.trace == [
        "prepare",
        "begin",
        "lock",
        "insert_job",
        "rollback",
        "discard",
    ]
    assert "start" not in connection.trace


def test_same_idempotency_key_and_payload_reuses_existing_job(monkeypatch):
    existing = {
        "id": "00000000-0000-0000-0000-000000000099",
        "job_id": "00000000-0000-0000-0000-000000000099",
        "operation": "world_build",
        "status": "completed",
        "request_payload": {"premise": "潮汐"},
        "idempotency_key": "request-1",
    }
    connection = _Connection(existing=existing)

    result = _run_create(monkeypatch, connection)

    assert result == {
        "job_id": existing["job_id"],
        "operation": "world_build",
        "status": "completed",
        "stream_url": f"/api/v1/novel/jobs/{existing['job_id']}/stream",
    }
    assert "prepare" not in connection.trace
    assert "start" not in connection.trace


def test_same_idempotency_key_with_different_payload_is_conflict(monkeypatch):
    existing = {
        "id": "00000000-0000-0000-0000-000000000099",
        "job_id": "00000000-0000-0000-0000-000000000099",
        "operation": "world_build",
        "status": "completed",
        "request_payload": {"premise": "旧请求"},
        "idempotency_key": "request-1",
    }
    connection = _Connection(existing=existing)

    with pytest.raises(JobAlreadyRunningError, match="Idempotency-Key"):
        _run_create(monkeypatch, connection)

    assert "prepare" not in connection.trace
    assert "start" not in connection.trace


def test_active_job_conflict_discards_prepared_task(monkeypatch):
    existing = {
        "id": "00000000-0000-0000-0000-000000000099",
        "operation": "world_build",
        "status": "running",
        "request_payload": {"premise": "其他请求"},
        "idempotency_key": "another-request",
    }
    connection = _Connection(existing=existing)

    with pytest.raises(JobAlreadyRunningError, match="同类生产任务"):
        _run_create(monkeypatch, connection)

    assert connection.trace == ["prepare", "begin", "lock", "rollback", "discard"]
    assert "start" not in connection.trace


def test_idempotent_job_committed_during_prepare_is_reused(monkeypatch):
    existing = {
        "id": "00000000-0000-0000-0000-000000000099",
        "job_id": "00000000-0000-0000-0000-000000000099",
        "operation": "world_build",
        "status": "queued",
        "request_payload": {"premise": "潮汐"},
        "idempotency_key": "request-1",
    }

    class RacingConnection(_Connection):
        def __init__(self):
            super().__init__(existing=existing)
            self.idempotency_reads = 0

        async def fetchrow(self, query: str, *args):
            normalized = " ".join(query.split())
            if "FROM novel_job" in normalized and "idempotency_key" in normalized:
                self.idempotency_reads += 1
                if self.idempotency_reads == 1:
                    return None
            return await super().fetchrow(query, *args)

    connection = RacingConnection()

    result = _run_create(monkeypatch, connection)

    assert result["job_id"] == existing["job_id"]
    assert connection.trace == ["prepare", "begin", "lock", "commit", "discard"]
    assert "insert_job" not in connection.trace
    assert "start" not in connection.trace


def test_post_hoc_status_is_in_same_transaction_before_start(monkeypatch):
    connection = _Connection()

    _run_create(
        monkeypatch,
        connection,
        operation="post_hoc",
        payload={"chapter_number": "0007", "language": "中文"},
    )

    assert connection.trace == [
        "prepare",
        "begin",
        "lock",
        "insert_job",
        "insert_event",
        "post_hoc_status",
        "commit",
        "start",
    ]


def test_workflow_start_failure_marks_persisted_job_failed(monkeypatch):
    connection = _Connection()

    with pytest.raises(WorkflowStartError, match="启动工作流任务失败") as caught:
        _run_create(monkeypatch, connection, fail_start=True)

    assert caught.value.details["job_id"] == connection.inserted_job["job_id"]
    assert caught.value.details["workflow_task_id"] == "task-prepared"
    assert connection.trace[:7] == [
        "prepare",
        "begin",
        "lock",
        "insert_job",
        "insert_event",
        "commit",
        "start",
    ]
    assert "mark_failed" in connection.trace
    assert connection.event_types == ["job_started", "job_failed"]
    assert connection.job_status == "failed"
    assert connection.trace[-1] == "discard"


def test_post_hoc_start_failure_marks_job_and_chapter_failed_in_one_transaction(
    monkeypatch,
):
    connection = _Connection()

    with pytest.raises(WorkflowStartError):
        _run_create(
            monkeypatch,
            connection,
            operation="post_hoc",
            payload={"chapter_number": "0007", "language": "中文"},
            fail_start=True,
        )

    assert connection.trace == [
        "prepare",
        "begin",
        "lock",
        "insert_job",
        "insert_event",
        "post_hoc_status",
        "commit",
        "start",
        "begin",
        "mark_failed",
        "post_hoc_failed",
        "insert_event",
        "commit",
        "discard",
    ]
    assert connection.event_types == ["job_started", "job_failed"]
    assert connection.job_status == "failed"


def test_workflow_start_error_maps_to_http_502_without_internal_message():
    error = WorkflowStartError(
        "启动工作流任务失败",
        {"job_id": "job-1", "workflow_task_id": "task-1"},
    )

    with pytest.raises(HTTPException) as caught:
        routes._raise_http(error)

    assert caught.value.status_code == 502
    assert caught.value.detail == {
        "error": "workflow_start_failed",
        "message": "启动工作流任务失败",
        "details": {"job_id": "job-1", "workflow_task_id": "task-1"},
    }

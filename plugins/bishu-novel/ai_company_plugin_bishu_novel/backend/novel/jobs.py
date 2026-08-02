"""Novel production job service."""

from __future__ import annotations

import asyncio
import json
import logging
import uuid
from typing import Any

import asyncpg

from .db import get_pool
from .errors import JobAlreadyRunningError, NotFoundError, WorkflowStartError
from .progress_mapper import ProgressMapper, workflow_for_operation
from .workflow_adapter import WorkflowAdapter

logger = logging.getLogger(__name__)


class NovelJobService:
    async def create_job(
        self,
        *,
        book_id: str,
        operation: str,
        request_payload: dict[str, Any],
        manager,
        actor_ref: str | None = None,
        request_id: str | None = None,
        idempotency_key: str | None = None,
    ) -> dict:
        pool = await get_pool()
        workflow_id = workflow_for_operation(operation)
        params = dict(request_payload)
        params["book_id"] = book_id
        writer_type = params.pop(
            "writer_type", "single"
        )  # passthrough to workflow variable
        params["writer_type"] = writer_type  # put back so it reaches the workflow
        stored_payload = dict(request_payload)
        idempotency_key = (idempotency_key or "").strip() or None

        # Replays should not even create a pending Core task.  The transaction
        # below repeats this lookup after taking the operation lock to close the
        # race with another request that is currently committing its Job.
        if idempotency_key:
            async with pool.acquire() as conn:
                existing = await self._find_idempotent_job(
                    conn,
                    book_id,
                    operation,
                    idempotency_key,
                )
            if existing:
                return self._reuse_idempotent_job(existing, stored_payload)

        adapter = WorkflowAdapter(manager)
        handle = adapter.prepare_workflow(
            workflow_id,
            parameter_values=params,
            workspace_override=f"data/book/{book_id}",
        )

        job_id = str(uuid.uuid4())
        reused: dict | None = None
        try:
            async with pool.acquire() as conn:
                async with conn.transaction():
                    await conn.execute(
                        "SELECT pg_advisory_xact_lock(hashtextextended($1, 0))",
                        self._active_lock_scope(book_id, operation, request_payload),
                    )
                    if idempotency_key:
                        existing = await self._find_idempotent_job(
                            conn,
                            book_id,
                            operation,
                            idempotency_key,
                        )
                        if existing:
                            reused = self._reuse_idempotent_job(
                                existing, stored_payload
                            )

                    if reused is None:
                        active = await self._find_active_job(
                            conn,
                            book_id,
                            operation,
                            request_payload,
                        )
                        if active:
                            raise self._active_job_error(active, operation)
                        await conn.execute(
                            """INSERT INTO novel_job (
                                   id, book_id, operation, status, workflow_id, workflow_task_id,
                                   request_payload, actor_ref, request_id, idempotency_key, created_at, updated_at
                               ) VALUES ($1, $2, $3, 'queued', $4, $5, $6::jsonb, $7, $8, $9, now(), now())""",
                            job_id,
                            book_id,
                            operation,
                            handle.workflow_id,
                            handle.task_id,
                            json.dumps(stored_payload, ensure_ascii=False),
                            actor_ref,
                            request_id,
                            idempotency_key,
                        )
                        await self.add_event(
                            conn,
                            job_id,
                            "job_started",
                            None,
                            None,
                            0,
                            {"operation": operation},
                        )
                        if operation == "post_hoc":
                            chapter_number = request_payload.get("chapter_number")
                            if chapter_number:
                                await conn.execute(
                                    """UPDATE chapter SET post_hoc_status = 'running'
                                       WHERE book_id = $1 AND chapter_number = $2""",
                                    book_id,
                                    int(chapter_number),
                                )
        except asyncpg.UniqueViolationError as exc:
            await self._discard_prepared_safely(adapter, handle)
            return await self._resolve_unique_conflict(
                pool=pool,
                book_id=book_id,
                operation=operation,
                request_payload=request_payload,
                stored_payload=stored_payload,
                idempotency_key=idempotency_key,
                cause=exc,
            )
        except Exception:
            await self._discard_prepared_safely(adapter, handle)
            raise

        if reused is not None:
            await self._discard_prepared_safely(adapter, handle)
            return reused

        try:
            await adapter.start_prepared_workflow(handle)
        except Exception as exc:
            await self._mark_start_failed(
                pool,
                job_id,
                book_id,
                operation,
                request_payload,
                exc,
            )
            await self._discard_prepared_safely(adapter, handle)
            raise WorkflowStartError(
                "启动工作流任务失败",
                {
                    "job_id": job_id,
                    "workflow_id": handle.workflow_id,
                    "workflow_task_id": handle.task_id,
                },
            ) from exc

        return self._job_result(job_id, operation, "queued")

    @staticmethod
    def _job_result(job_id: str, operation: str, status: str) -> dict:
        return {
            "job_id": str(job_id),
            "operation": operation,
            "status": status,
            "stream_url": f"/api/v1/novel/jobs/{job_id}/stream",
        }

    @staticmethod
    def _payload_dict(value: Any) -> dict:
        if isinstance(value, dict):
            return value
        if isinstance(value, str):
            parsed = json.loads(value)
            return parsed if isinstance(parsed, dict) else {}
        return {}

    def _reuse_idempotent_job(self, row, stored_payload: dict) -> dict:
        existing_payload = self._payload_dict(row.get("request_payload"))
        if existing_payload != stored_payload:
            raise JobAlreadyRunningError(
                "Idempotency-Key 已用于不同请求",
                {
                    "job_id": str(row.get("job_id") or row.get("id")),
                    "reason": "idempotency_payload_mismatch",
                },
            )
        return self._job_result(
            str(row.get("job_id") or row.get("id")),
            str(row.get("operation")),
            str(row.get("status")),
        )

    @staticmethod
    async def _find_idempotent_job(
        conn, book_id: str, operation: str, idempotency_key: str
    ):
        return await conn.fetchrow(
            """SELECT id AS job_id, operation, status, request_payload, idempotency_key
               FROM novel_job
               WHERE book_id = $1 AND operation = $2 AND idempotency_key = $3
               LIMIT 1""",
            book_id,
            operation,
            idempotency_key,
        )

    @staticmethod
    async def _find_active_job(
        conn, book_id: str, operation: str, request_payload: dict
    ):
        if operation == "chapter_polish":
            return await conn.fetchrow(
                """SELECT id, operation, status FROM novel_job
                   WHERE book_id = $1 AND operation = $2 AND status IN ('queued', 'running')
                     AND request_payload->>'chapter_number' = $3
                   ORDER BY created_at DESC LIMIT 1
                   FOR UPDATE""",
                book_id,
                operation,
                str(request_payload.get("chapter_number", "")),
            )
        return await conn.fetchrow(
            """SELECT id, operation, status FROM novel_job
               WHERE book_id = $1 AND operation = $2 AND status IN ('queued', 'running')
               ORDER BY created_at DESC LIMIT 1
               FOR UPDATE""",
            book_id,
            operation,
        )

    @staticmethod
    def _active_lock_scope(book_id: str, operation: str, request_payload: dict) -> str:
        chapter_scope = (
            str(request_payload.get("chapter_number", ""))
            if operation == "chapter_polish"
            else "*"
        )
        return f"novel-job:{book_id}:{operation}:{chapter_scope}"

    @staticmethod
    def _active_job_error(row, operation: str) -> JobAlreadyRunningError:
        return JobAlreadyRunningError(
            "同类生产任务正在运行",
            {
                "job_id": str(row["id"]),
                "operation": operation,
                "status": row["status"],
            },
        )

    async def _resolve_unique_conflict(
        self,
        *,
        pool,
        book_id: str,
        operation: str,
        request_payload: dict,
        stored_payload: dict,
        idempotency_key: str | None,
        cause: Exception,
    ) -> dict:
        async with pool.acquire() as conn:
            if idempotency_key:
                existing = await self._find_idempotent_job(
                    conn,
                    book_id,
                    operation,
                    idempotency_key,
                )
                if existing:
                    return self._reuse_idempotent_job(existing, stored_payload)
            active = await self._find_active_job(
                conn,
                book_id,
                operation,
                request_payload,
            )
        if active:
            raise self._active_job_error(active, operation) from cause
        raise JobAlreadyRunningError(
            "任务约束冲突，请使用原请求查询任务状态",
            {"operation": operation, "reason": "unique_constraint_conflict"},
        ) from cause

    async def _mark_start_failed(
        self,
        pool,
        job_id: str,
        book_id: str,
        operation: str,
        request_payload: dict,
        exc: Exception,
    ) -> None:
        error = {"message": "启动工作流任务失败", "type": type(exc).__name__}
        try:
            async with pool.acquire() as conn:
                async with conn.transaction():
                    await conn.execute(
                        """UPDATE novel_job
                           SET status='failed', updated_at=now(), error=$1::jsonb
                           WHERE id=$2 AND status='queued'""",
                        json.dumps(error, ensure_ascii=False),
                        job_id,
                    )
                    if operation == "post_hoc":
                        chapter_number = request_payload.get("chapter_number")
                        if chapter_number:
                            await conn.execute(
                                """UPDATE chapter SET post_hoc_status = 'failed'
                                   WHERE book_id = $1 AND chapter_number = $2""",
                                book_id,
                                int(chapter_number),
                            )
                    await self.add_event(
                        conn,
                        job_id,
                        "job_failed",
                        None,
                        None,
                        None,
                        error,
                    )
        except Exception:
            logger.exception("记录 Workflow 启动失败状态异常: job_id=%s", job_id)

    @staticmethod
    async def _discard_prepared_safely(adapter: WorkflowAdapter, handle) -> None:
        try:
            await adapter.discard_prepared_workflow(handle)
        except Exception:
            logger.exception(
                "清理未启动 WorkflowTask 失败: workflow_id=%s task_id=%s",
                handle.workflow_id,
                handle.task_id,
            )

    async def get_job(self, job_id: str) -> dict:
        pool = await get_pool()
        async with pool.acquire() as conn:
            row = await conn.fetchrow(
                """SELECT id AS job_id, book_id, operation, status, current_stage, progress,
                          request_payload, result_payload, error, created_at, updated_at
                   FROM novel_job WHERE id = $1""",
                job_id,
            )
        if not row:
            raise NotFoundError("任务不存在", {"job_id": job_id})
        data = dict(row)
        for key in ("request_payload", "result_payload", "error"):
            if isinstance(data.get(key), str):
                data[key] = json.loads(data[key])
        return data

    async def get_job_internal(self, job_id: str) -> dict:
        pool = await get_pool()
        async with pool.acquire() as conn:
            row = await conn.fetchrow("SELECT * FROM novel_job WHERE id = $1", job_id)
        if not row:
            raise NotFoundError("任务不存在", {"job_id": job_id})
        return dict(row)

    async def list_events(self, job_id: str, after_id: int | None = None) -> list[dict]:
        pool = await get_pool()
        async with pool.acquire() as conn:
            if after_id is not None:
                rows = await conn.fetch(
                    """SELECT id, event_type, stage_id, stage_name, progress, payload, created_at
                       FROM novel_job_event WHERE job_id = $1 AND id > $2 ORDER BY id""",
                    job_id,
                    after_id,
                )
            else:
                rows = await conn.fetch(
                    """SELECT id, event_type, stage_id, stage_name, progress, payload, created_at
                       FROM novel_job_event WHERE job_id = $1 ORDER BY id""",
                    job_id,
                )
        events = []
        for r in rows:
            d = dict(r)
            if isinstance(d.get("payload"), str):
                d["payload"] = json.loads(d["payload"])
            events.append(d)
        return events

    async def cancel_job(self, job_id: str, manager) -> dict:
        job = await self.get_job_internal(job_id)
        adapter = WorkflowAdapter(manager)
        stopped = await adapter.cancel_task(job["workflow_id"], job["workflow_task_id"])
        pool = await get_pool()
        async with pool.acquire() as conn:
            await conn.execute(
                """UPDATE novel_job SET status='cancelled', updated_at=now(), error=$1::jsonb WHERE id=$2""",
                json.dumps({"stopped": stopped}, ensure_ascii=False),
                job_id,
            )
            await self.add_event(
                conn, job_id, "job_cancelled", None, None, None, {"stopped": stopped}
            )
        return {"job_id": job_id, "status": "cancelled", "stopped": stopped}

    async def cleanup_zombie_jobs(self) -> int:
        """清理服务器重启后遗留的僵尸任务。

        服务器重启后，所有 running/queued 状态的 Job 对应的进程内协程已丢失，
        任务永远无法完成。此方法将其标记为 failed 并写入 job_failed 事件。
        """
        pool = await get_pool()
        async with pool.acquire() as conn:
            rows = await conn.fetch(
                "SELECT id, operation FROM novel_job WHERE status IN ('queued', 'running')"
            )
            if not rows:
                return 0

            await conn.execute(
                """UPDATE novel_job
                   SET status = 'failed', updated_at = now(),
                       error = '{"message": "服务器重启，任务中断"}'::jsonb
                   WHERE status IN ('queued', 'running')"""
            )
            for row in rows:
                await self.add_event(
                    conn,
                    str(row["id"]),
                    "job_failed",
                    None,
                    None,
                    None,
                    {"status": "failed", "error": "服务器重启，任务中断"},
                )
            logger.warning("清理了 %d 个僵尸任务（服务器重启导致）", len(rows))
            return len(rows)

    async def add_event(
        self,
        conn,
        job_id: str,
        event_type: str,
        stage_id: str | None,
        stage_name: str | None,
        progress: float | None,
        payload: dict,
    ) -> int:
        row = await conn.fetchrow(
            """INSERT INTO novel_job_event (job_id, event_type, stage_id, stage_name, progress, payload)
               VALUES ($1, $2, $3, $4, $5, $6::jsonb)
               RETURNING id""",
            job_id,
            event_type,
            stage_id,
            stage_name,
            progress,
            json.dumps(payload or {}, ensure_ascii=False),
        )
        return int(row["id"])

    async def pump_workflow_events(
        self, job_id: str, manager, queue: asyncio.Queue | None = None
    ) -> None:
        job = await self.get_job_internal(job_id)
        mapper = ProgressMapper(job["operation"])
        workflow_id = job["workflow_id"]
        task_id = job["workflow_task_id"]
        prev_states: dict[str, str] = {}
        pool = await get_pool()
        while True:
            await asyncio.sleep(1.5)
            task = manager.get_task(workflow_id, task_id)
            if not task:
                break
            async with pool.acquire() as conn:
                node_states = task.get("node_states", {})
                for node_id, state in node_states.items():
                    status = state.get("status", "pending")
                    if prev_states.get(node_id) == status:
                        continue
                    prev_states[node_id] = status
                    mapped = mapper.map_node(node_id, status)
                    if not mapped:
                        continue
                    await conn.execute(
                        """UPDATE novel_job SET current_stage=$1, progress=$2, status='running', updated_at=now()
                           WHERE id=$3""",
                        mapped["stage_id"],
                        mapped["progress"],
                        job_id,
                    )
                    read_path = mapped.get("read_path")
                    if read_path:
                        read_path = read_path.replace("{book_id}", str(job["book_id"]))
                        rp = job.get("request_payload") or {}
                        if isinstance(rp, str):
                            rp = json.loads(rp)
                        read_path = read_path.replace(
                            "{chapter_number}", str(rp.get("chapter_number", ""))
                        )
                    payload = {
                        "operation": job["operation"],
                        "workflow_id": workflow_id,
                        "workflow_task_id": task_id,
                        "node_id": node_id,
                        "resource_type": mapped.get("resource_type"),
                        "resource_key": mapped.get("resource_key"),
                        "artifact_path": mapped.get("artifact_path"),
                        "content_available": mapped.get("content_available", False),
                        "read_path": read_path,
                    }
                    event_id = await self.add_event(
                        conn,
                        job_id,
                        mapped["event_type"],
                        mapped["stage_id"],
                        mapped["stage_name"],
                        mapped["progress"],
                        payload,
                    )
                    event_data = {
                        "id": event_id,
                        **mapped,
                        "read_path": read_path,
                        "job_id": job_id,
                        "operation": job["operation"],
                        "payload": payload,
                    }
                    if queue:
                        await queue.put(event_data)

                task_status = task.get("status")
                if task_status in ("completed", "failed", "stopped"):
                    # --- 更新 post_hoc_status ---
                    if job["operation"] == "post_hoc":
                        rp = job.get("request_payload") or {}
                        if isinstance(rp, str):
                            rp = json.loads(rp)
                        cn = rp.get("chapter_number")
                        if cn:
                            await conn.execute(
                                "UPDATE chapter SET post_hoc_status = $1 WHERE book_id = $2 AND chapter_number = $3",
                                "completed" if task_status == "completed" else "failed",
                                job["book_id"],
                                int(cn),
                            )
                    # --- 原有完成/失败逻辑 ---
                    if task_status == "completed":
                        await conn.execute(
                            """UPDATE novel_job SET status='completed', progress=1, updated_at=now(), result_payload=$1::jsonb WHERE id=$2""",
                            json.dumps(
                                {"workflow_task_id": task_id}, ensure_ascii=False
                            ),
                            job_id,
                        )
                        event_id = await self.add_event(
                            conn,
                            job_id,
                            "job_completed",
                            None,
                            None,
                            1,
                            {"status": "completed"},
                        )
                        if queue:
                            await queue.put(
                                {
                                    "id": event_id,
                                    "event_type": "job_completed",
                                    "job_id": job_id,
                                    "status": "completed",
                                    "progress": 1,
                                }
                            )
                    else:
                        await conn.execute(
                            """UPDATE novel_job SET status='failed', updated_at=now(), error=$1::jsonb WHERE id=$2""",
                            json.dumps(
                                {"status": task_status, "error": task.get("error", "")},
                                ensure_ascii=False,
                            ),
                            job_id,
                        )
                        event_id = await self.add_event(
                            conn,
                            job_id,
                            "job_failed",
                            None,
                            None,
                            None,
                            {"status": task_status, "error": task.get("error", "")},
                        )
                        if queue:
                            await queue.put(
                                {
                                    "id": event_id,
                                    "event_type": "job_failed",
                                    "job_id": job_id,
                                    "status": task_status,
                                }
                            )
                    break

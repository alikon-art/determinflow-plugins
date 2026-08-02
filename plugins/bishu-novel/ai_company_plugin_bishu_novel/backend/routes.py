"""小说 API 路由 — 炼字引擎对外接口.

Legacy endpoints remain under /api/novel.
Product endpoints live under /api/v1/novel.
"""

from __future__ import annotations

import asyncio
import json
import logging
from typing import Any

from fastapi import APIRouter, Header, HTTPException, Request
from fastapi.responses import StreamingResponse

from src.extension_api import WorkflowRuntime

from .novel.dao import NovelDAO, WORLD_DIMENSIONS
from .novel.db import get_pool
from .novel.edits import EditService
from .novel.errors import NovelError
from .novel.jobs import NovelJobService
from .novel.resource_ids import workflow_for_operation
from .novel.schemas import (
    BuildCharacterRequest,
    BuildOutlineRequest,
    BuildStoryPlanRequest,
    BuildWorldRequest,
    GenerateChapterRequest,
    PolishChapterRequest,
    PostHocChapterRequest,
    CreateBookRequest,
    ReplaceChapterBodyRequest,
    ReplaceJsonResourceRequest,
    UpdateBookRequest,
    UpdateDebtRequest,
    UpdateHookRequest,
)

logger = logging.getLogger(__name__)

router = APIRouter(tags=["novel"])
legacy_router = APIRouter(prefix="/api/novel", tags=["novel-legacy"])
v1_router = APIRouter(prefix="/api/v1/novel", tags=["novel-v1"])

_task_queues: dict[str, asyncio.Queue] = {}
_job_queues: dict[str, asyncio.Queue] = {}
_job_pumps: dict[str, asyncio.Task] = {}

dao = NovelDAO()
edit_service = EditService()
job_service = NovelJobService()
_workflow_runtime: WorkflowRuntime | None = None


def configure_workflow_runtime(runtime: WorkflowRuntime | None) -> None:
    global _workflow_runtime
    _workflow_runtime = runtime


def _get_manager() -> WorkflowRuntime:
    if _workflow_runtime is None:
        raise HTTPException(status_code=503, detail="Workflow Runtime 未初始化")
    return _workflow_runtime


def _raise_http(exc: Exception):
    if isinstance(exc, HTTPException):
        raise exc
    if isinstance(exc, NovelError):
        raise HTTPException(
            status_code=exc.status_code,
            detail={"error": exc.error, "message": exc.message, "details": exc.details},
        )
    raise HTTPException(status_code=500, detail=str(exc))


def _actor(actor_header: str | None, body_actor: str | None = None) -> str | None:
    return actor_header or body_actor


def _request_id(
    req_header: str | None, body_request_id: str | None = None
) -> str | None:
    return req_header or body_request_id


# ═══════════════════════════════════════════════════════════
#  Legacy API: /api/novel
# ═══════════════════════════════════════════════════════════


@legacy_router.post("/books")
async def legacy_create_book(body: CreateBookRequest, request: Request):
    try:
        book = await dao.create_book(
            body.title, body.external_ref, body.genre, body.settings
        )
        return {"book_id": str(book["id"]), "title": book["title"]}
    except Exception as exc:
        logger.exception("建书失败")
        _raise_http(exc)


@legacy_router.get("/books/{book_id}")
async def legacy_get_book(book_id: str, request: Request):
    try:
        return await dao.get_book(book_id)
    except Exception as exc:
        logger.exception("获取书信息失败: book_id=%s", book_id)
        _raise_http(exc)


@legacy_router.get("/books/{book_id}/chapters")
async def legacy_list_chapters(book_id: str, request: Request):
    try:
        return await dao.list_chapters(book_id)
    except Exception as exc:
        logger.exception("获取章节目录失败: book_id=%s", book_id)
        _raise_http(exc)


@legacy_router.get("/books/{book_id}/chapters/{chapter_number}")
async def legacy_get_chapter(book_id: str, chapter_number: int, request: Request):
    try:
        return await dao.get_chapter(book_id, chapter_number)
    except Exception as exc:
        logger.exception(
            "获取章节正文失败: book_id=%s chapter=%s", book_id, chapter_number
        )
        _raise_http(exc)


@legacy_router.get("/books/{book_id}/world")
async def legacy_get_world(book_id: str, request: Request):
    try:
        return await dao.get_world(book_id)
    except Exception as exc:
        logger.exception("获取世界观失败: book_id=%s", book_id)
        _raise_http(exc)


@legacy_router.post("/books/{book_id}/world/build")
async def legacy_build_world(book_id: str, body: BuildWorldRequest, request: Request):
    """Legacy world build endpoint. Returns workflow task_id for compatibility."""
    try:
        pool = await get_pool()
        async with pool.acquire() as conn:
            exists = await conn.fetchval("SELECT 1 FROM book WHERE id = $1", book_id)
        if not exists:
            raise HTTPException(status_code=404, detail="书不存在")

        mgr = _get_manager()
        workflow_id = workflow_for_operation("world_build")
        result = mgr.create_task(
            workflow_id,
            parameter_values={
                "premise": body.premise,
                "genre": body.genre,
                "language": body.language,
                "book_id": book_id,
            },
            workspace_override=f"data/book/{book_id}",
        )
        if result is None:
            raise HTTPException(status_code=500, detail="创建工作流任务失败")
        task_id = result["task_id"]
        _task_queues[task_id] = asyncio.Queue(maxsize=64)
        run_result = await mgr.run_task(workflow_id, task_id)
        if not run_result.get("success"):
            _task_queues.pop(task_id, None)
            raise HTTPException(
                status_code=500, detail=run_result.get("message", "启动失败")
            )
        init_task = mgr.get_task(workflow_id, task_id) or {}
        _push_to_queue(task_id, {"task": init_task}, "initial_state")
        asyncio.create_task(_pump_task_events(task_id, workflow_id, mgr))
        return {"task_id": task_id, "stream_url": f"/api/novel/tasks/{task_id}/stream"}
    except Exception as exc:
        logger.exception("启动世界观构建失败: book_id=%s", book_id)
        _raise_http(exc)


@legacy_router.get("/tasks/{task_id}/stream")
async def legacy_stream_task(task_id: str, request: Request):
    q = _task_queues.get(task_id)
    if q is None:
        try:
            mgr = _get_manager()
            workflow_id = workflow_for_operation("world_build")
            status_data = mgr.get_task(workflow_id, task_id)
            if status_data is None:
                raise HTTPException(status_code=404, detail="任务不存在")
            q = asyncio.Queue(maxsize=64)
            _task_queues[task_id] = q
            await q.put({"type": "initial_state", "data": {"task": status_data}})
            asyncio.create_task(_pump_task_events(task_id, workflow_id, mgr))
        except Exception as exc:
            logger.exception("SSE 流初始化失败: task_id=%s", task_id)
            _raise_http(exc)

    async def event_stream():
        try:
            while True:
                try:
                    event = await asyncio.wait_for(q.get(), timeout=30.0)
                except asyncio.TimeoutError:
                    yield "event: heartbeat\ndata: {}\n\n"
                    continue
                event_type = _map_event_type(event)
                yield f"event: {event_type}\ndata: {json.dumps(event['data'], ensure_ascii=False, default=str)}\n\n"
                if event_type in ("task_completed", "task_failed"):
                    break
        except asyncio.CancelledError:
            pass

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


# ═══════════════════════════════════════════════════════════
#  Product API: /api/v1/novel
# ═══════════════════════════════════════════════════════════


@v1_router.get("/books")
async def list_books(limit: int = 50, offset: int = 0):
    try:
        return await dao.list_books(limit=limit, offset=offset)
    except Exception as exc:
        logger.exception("书列表查询失败")
        _raise_http(exc)


@v1_router.post("/books")
async def create_book(body: CreateBookRequest):
    try:
        book = await dao.create_book(
            body.title, body.external_ref, body.genre, body.settings
        )
        return {"book_id": str(book["id"]), **book}
    except Exception as exc:
        logger.exception("建书失败")
        _raise_http(exc)


@v1_router.get("/books/{book_id}")
async def get_book(book_id: str):
    try:
        return await dao.get_book(book_id)
    except Exception as exc:
        logger.exception("获取书信息失败: book_id=%s", book_id)
        _raise_http(exc)


@v1_router.put("/books/{book_id}")
async def update_book(
    book_id: str,
    body: UpdateBookRequest,
    x_actor_ref: str | None = Header(default=None, alias="X-Actor-Ref"),
    x_request_id: str | None = Header(default=None, alias="X-Request-Id"),
):
    try:
        content = {
            "title": body.title,
            "status": body.status,
            "genre": body.genre,
            "estimated_length": body.estimated_length,
            "words_per_chapter": body.words_per_chapter,
        }
        return await edit_service.apply_edit(
            book_id=book_id,
            resource_type="book",
            resource_key="meta",
            base_version=body.base_version,
            new_content=content,
            source="portal_user",
            source_detail="portal:manual_edit",
            actor_ref=_actor(x_actor_ref, body.actor_ref),
            request_id=_request_id(x_request_id, body.request_id),
            reason=body.reason,
        )
    except Exception as exc:
        logger.exception("更新书信息失败: book_id=%s", book_id)
        _raise_http(exc)


@v1_router.delete("/books/{book_id}")
async def delete_book(book_id: str):
    """软删除书籍"""
    try:
        return await dao.delete_book(book_id)
    except Exception as exc:
        logger.exception("删除书籍失败: book_id=%s", book_id)
        _raise_http(exc)


@v1_router.get("/books/{book_id}/world")
async def get_world(book_id: str):
    try:
        return await dao.get_world(book_id)
    except Exception as exc:
        logger.exception("获取世界观失败: book_id=%s", book_id)
        _raise_http(exc)


@v1_router.get("/books/{book_id}/world/{dimension}")
async def get_world_dimension(book_id: str, dimension: str):
    try:
        return await dao.get_world_dimension(book_id, dimension)
    except Exception as exc:
        logger.exception(
            "获取世界观维度失败: book_id=%s dimension=%s", book_id, dimension
        )
        _raise_http(exc)


@v1_router.put("/books/{book_id}/world/{dimension}")
async def update_world_dimension(
    book_id: str,
    dimension: str,
    body: ReplaceJsonResourceRequest,
    x_actor_ref: str | None = Header(default=None, alias="X-Actor-Ref"),
    x_request_id: str | None = Header(default=None, alias="X-Request-Id"),
):
    try:
        if dimension not in WORLD_DIMENSIONS:
            raise HTTPException(status_code=400, detail="世界观维度不存在")
        return await edit_service.apply_edit(
            book_id=book_id,
            resource_type="world",
            resource_key=dimension,
            base_version=body.base_version,
            new_content=body.content,
            source="portal_user",
            source_detail="portal:manual_edit",
            actor_ref=_actor(x_actor_ref, body.actor_ref),
            request_id=_request_id(x_request_id, body.request_id),
            reason=body.reason,
        )
    except Exception as exc:
        logger.exception(
            "更新世界观维度失败: book_id=%s dimension=%s", book_id, dimension
        )
        _raise_http(exc)


@v1_router.get("/books/{book_id}/story-plan")
async def get_story_plan(book_id: str):
    try:
        return await dao.get_book_json_resource(book_id, "story_plan")
    except Exception as exc:
        logger.exception("获取故事规划失败: book_id=%s", book_id)
        _raise_http(exc)


@v1_router.put("/books/{book_id}/story-plan")
async def update_story_plan(
    book_id: str,
    body: ReplaceJsonResourceRequest,
    x_actor_ref: str | None = Header(default=None, alias="X-Actor-Ref"),
    x_request_id: str | None = Header(default=None, alias="X-Request-Id"),
):
    try:
        return await edit_service.apply_edit(
            book_id=book_id,
            resource_type="book",
            resource_key="story_plan",
            base_version=body.base_version,
            new_content=body.content,
            source="portal_user",
            source_detail="portal:manual_edit",
            actor_ref=_actor(x_actor_ref, body.actor_ref),
            request_id=_request_id(x_request_id, body.request_id),
            reason=body.reason,
        )
    except Exception as exc:
        logger.exception("更新故事规划失败: book_id=%s", book_id)
        _raise_http(exc)


@v1_router.get("/books/{book_id}/style-profile")
async def get_style_profile(book_id: str):
    try:
        return await dao.get_book_json_resource(book_id, "style_profile")
    except Exception as exc:
        logger.exception("获取风格档案失败: book_id=%s", book_id)
        _raise_http(exc)


@v1_router.put("/books/{book_id}/style-profile")
async def update_style_profile(
    book_id: str,
    body: ReplaceJsonResourceRequest,
    x_actor_ref: str | None = Header(default=None, alias="X-Actor-Ref"),
    x_request_id: str | None = Header(default=None, alias="X-Request-Id"),
):
    try:
        return await edit_service.apply_edit(
            book_id=book_id,
            resource_type="book",
            resource_key="style_profile",
            base_version=body.base_version,
            new_content=body.content,
            source="portal_user",
            source_detail="portal:manual_edit",
            actor_ref=_actor(x_actor_ref, body.actor_ref),
            request_id=_request_id(x_request_id, body.request_id),
            reason=body.reason,
        )
    except Exception as exc:
        logger.exception("更新风格档案失败: book_id=%s", book_id)
        _raise_http(exc)


async def _create_and_start_job(
    *,
    request: Request,
    book_id: str,
    operation: str,
    request_payload: dict[str, Any],
    actor_ref: str | None,
    request_id: str | None,
    idempotency_key: str | None,
):
    mgr = _get_manager()
    result = await job_service.create_job(
        book_id=book_id,
        operation=operation,
        request_payload=request_payload,
        manager=mgr,
        actor_ref=actor_ref,
        request_id=request_id,
        idempotency_key=idempotency_key,
    )
    if result.get("status") in {"queued", "running"}:
        _ensure_job_pump(result["job_id"], mgr)
    return result


@v1_router.post("/books/{book_id}/world/build")
async def build_world(
    book_id: str,
    body: BuildWorldRequest,
    request: Request,
    x_actor_ref: str | None = Header(default=None, alias="X-Actor-Ref"),
    x_request_id: str | None = Header(default=None, alias="X-Request-Id"),
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
):
    try:
        return await _create_and_start_job(
            request=request,
            book_id=book_id,
            operation="world_build",
            request_payload={
                "premise": body.premise,
                "genre": body.genre,
                "language": body.language,
            },
            actor_ref=x_actor_ref,
            request_id=x_request_id,
            idempotency_key=idempotency_key,
        )
    except Exception as exc:
        logger.exception("启动世界观构建 job 失败: book_id=%s", book_id)
        _raise_http(exc)


@v1_router.post("/books/{book_id}/characters/build")
async def build_characters(
    book_id: str,
    body: BuildCharacterRequest,
    request: Request,
    x_actor_ref: str | None = Header(default=None, alias="X-Actor-Ref"),
    x_request_id: str | None = Header(default=None, alias="X-Request-Id"),
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
):
    try:
        return await _create_and_start_job(
            request=request,
            book_id=book_id,
            operation="character_build",
            request_payload={
                "premise": body.premise,
                "genre": body.genre,
                "language": body.language,
            },
            actor_ref=x_actor_ref,
            request_id=x_request_id,
            idempotency_key=idempotency_key,
        )
    except Exception as exc:
        logger.exception("启动角色构建 job 失败: book_id=%s", book_id)
        _raise_http(exc)


@v1_router.post("/books/{book_id}/story-plan/build")
async def build_story_plan(
    book_id: str,
    body: BuildStoryPlanRequest,
    request: Request,
    x_actor_ref: str | None = Header(default=None, alias="X-Actor-Ref"),
    x_request_id: str | None = Header(default=None, alias="X-Request-Id"),
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
):
    try:
        return await _create_and_start_job(
            request=request,
            book_id=book_id,
            operation="story_plan_build",
            request_payload={
                "premise": body.premise,
                "genre": body.genre,
                "language": body.language,
            },
            actor_ref=x_actor_ref,
            request_id=x_request_id,
            idempotency_key=idempotency_key,
        )
    except Exception as exc:
        logger.exception("启动故事规划 job 失败: book_id=%s", book_id)
        _raise_http(exc)


@v1_router.post("/books/{book_id}/outline/build")
async def build_outline(
    book_id: str,
    body: BuildOutlineRequest,
    request: Request,
    x_actor_ref: str | None = Header(default=None, alias="X-Actor-Ref"),
    x_request_id: str | None = Header(default=None, alias="X-Request-Id"),
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
):
    try:
        pool = await get_pool()
        async with pool.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT COALESCE(MAX(chapter_number), 0) AS last_chapter FROM chapter WHERE book_id = $1",
                book_id,
            )
            last_chapter_int = row["last_chapter"] if row else 0

            volume_number = body.volume_number
            if volume_number is None:
                row = await conn.fetchrow(
                    "SELECT COALESCE(MAX(volume_number), 0) AS max_vol FROM outline WHERE book_id = $1 AND type = 'volume'",
                    book_id,
                )
                max_vol = row["max_vol"] if row else 0
                volume_number = max_vol + 1

        return await _create_and_start_job(
            request=request,
            book_id=book_id,
            operation="outline_build",
            request_payload={
                "latest_chapter": str(last_chapter_int).zfill(4),
                "volume_number": str(volume_number),
                "estimated_length": body.estimated_length,
                "words_per_chapter": body.words_per_chapter,
            },
            actor_ref=x_actor_ref,
            request_id=x_request_id,
            idempotency_key=idempotency_key,
        )
    except Exception as exc:
        logger.exception("启动大纲 job 失败: book_id=%s", book_id)
        _raise_http(exc)


@v1_router.post("/books/{book_id}/chapters/{chapter_number}/generate")
async def generate_chapter(
    book_id: str,
    chapter_number: int,
    body: GenerateChapterRequest,
    request: Request,
    x_actor_ref: str | None = Header(default=None, alias="X-Actor-Ref"),
    x_request_id: str | None = Header(default=None, alias="X-Request-Id"),
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
):
    try:
        return await _create_and_start_job(
            request=request,
            book_id=book_id,
            operation="chapter_generate",
            request_payload={
                "chapter_number": f"{chapter_number:04d}",
                "prev_chapter": body.prev_chapter,
                "human_intent": body.human_intent,
                "world_intent": body.world_intent,
                "target_word_count": body.target_word_count,
                "language": body.language,
                "writer_type": body.writer_type,
            },
            actor_ref=x_actor_ref,
            request_id=x_request_id,
            idempotency_key=idempotency_key,
        )
    except Exception as exc:
        logger.exception(
            "启动章节生成 job 失败: book_id=%s chapter=%s", book_id, chapter_number
        )
        _raise_http(exc)


@v1_router.post("/books/{book_id}/chapters/{chapter_number}/polish")
async def polish_chapter(
    book_id: str,
    chapter_number: int,
    body: PolishChapterRequest,
    request: Request,
    x_actor_ref: str | None = Header(default=None, alias="X-Actor-Ref"),
    x_request_id: str | None = Header(default=None, alias="X-Request-Id"),
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
):
    try:
        return await _create_and_start_job(
            request=request,
            book_id=book_id,
            operation="chapter_polish",
            request_payload={
                "chapter_number": f"{chapter_number:04d}",
                "language": body.language,
            },
            actor_ref=x_actor_ref,
            request_id=x_request_id,
            idempotency_key=idempotency_key,
        )
    except Exception as exc:
        logger.exception(
            "启动章节润色 job 失败: book_id=%s chapter=%s", book_id, chapter_number
        )
        _raise_http(exc)


@v1_router.post("/books/{book_id}/chapters/{chapter_number}/post-hoc")
async def post_hoc_chapter(
    book_id: str,
    chapter_number: int,
    body: PostHocChapterRequest,
    request: Request,
    x_actor_ref: str | None = Header(default=None, alias="X-Actor-Ref"),
    x_request_id: str | None = Header(default=None, alias="X-Request-Id"),
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
):
    try:
        return await _create_and_start_job(
            request=request,
            book_id=book_id,
            operation="post_hoc",
            request_payload={
                "chapter_number": f"{chapter_number:04d}",
                "language": body.language,
            },
            actor_ref=x_actor_ref,
            request_id=x_request_id,
            idempotency_key=idempotency_key,
        )
    except Exception as exc:
        logger.exception(
            "启动章节后验 job 失败: book_id=%s chapter=%s", book_id, chapter_number
        )
        _raise_http(exc)


@v1_router.get("/books/{book_id}/chapters")
async def v1_list_chapters(book_id: str):
    try:
        return await dao.list_chapters(book_id)
    except Exception as exc:
        logger.exception("获取章节目录失败: book_id=%s", book_id)
        _raise_http(exc)


@v1_router.get("/books/{book_id}/chapters/{chapter_number}")
async def v1_get_chapter(book_id: str, chapter_number: int):
    try:
        return await dao.get_chapter(book_id, chapter_number)
    except Exception as exc:
        logger.exception(
            "获取章节正文失败: book_id=%s chapter=%s", book_id, chapter_number
        )
        _raise_http(exc)


@v1_router.put("/books/{book_id}/chapters/{chapter_number}/body")
async def update_chapter_body(
    book_id: str,
    chapter_number: int,
    body: ReplaceChapterBodyRequest,
    x_actor_ref: str | None = Header(default=None, alias="X-Actor-Ref"),
    x_request_id: str | None = Header(default=None, alias="X-Request-Id"),
):
    try:
        content = {"body": body.body, "title": body.title, "status": body.status}
        return await edit_service.apply_edit(
            book_id=book_id,
            resource_type="chapter",
            resource_key=f"{chapter_number:04d}:body",
            base_version=body.base_version,
            new_content=content,
            source="portal_user",
            source_detail="portal:manual_edit",
            actor_ref=_actor(x_actor_ref, body.actor_ref),
            request_id=_request_id(x_request_id, body.request_id),
            reason=body.reason,
            metadata={"invalidates": ["post_hoc", "polish"]},
        )
    except Exception as exc:
        logger.exception(
            "更新章节正文失败: book_id=%s chapter=%s", book_id, chapter_number
        )
        _raise_http(exc)


@v1_router.get("/books/{book_id}/chapters/{chapter_number}/world")
async def get_chapter_world(book_id: str, chapter_number: int):
    try:
        return await dao.get_chapter_world(book_id, chapter_number)
    except Exception as exc:
        logger.exception(
            "获取章节世界状态失败: book_id=%s chapter=%s", book_id, chapter_number
        )
        _raise_http(exc)


@v1_router.put("/books/{book_id}/chapters/{chapter_number}/world")
async def update_chapter_world(
    book_id: str,
    chapter_number: int,
    body: ReplaceJsonResourceRequest,
    x_actor_ref: str | None = Header(default=None, alias="X-Actor-Ref"),
    x_request_id: str | None = Header(default=None, alias="X-Request-Id"),
):
    try:
        return await edit_service.apply_edit(
            book_id=book_id,
            resource_type="chapter",
            resource_key=f"{chapter_number:04d}:world",
            base_version=body.base_version,
            new_content=body.content,
            source="portal_user",
            source_detail="portal:manual_edit",
            actor_ref=_actor(x_actor_ref, body.actor_ref),
            request_id=_request_id(x_request_id, body.request_id),
            reason=body.reason,
        )
    except Exception as exc:
        logger.exception(
            "更新章节世界状态失败: book_id=%s chapter=%s", book_id, chapter_number
        )
        _raise_http(exc)


@v1_router.get("/books/{book_id}/chapters/{chapter_number}/guide")
async def get_chapter_guide(book_id: str, chapter_number: int):
    try:
        return await dao.get_chapter_guide(book_id, chapter_number)
    except Exception as exc:
        logger.exception(
            "获取章节大纲失败: book_id=%s chapter=%s", book_id, chapter_number
        )
        _raise_http(exc)


@v1_router.put("/books/{book_id}/chapters/{chapter_number}/guide")
async def update_chapter_guide(
    book_id: str,
    chapter_number: int,
    body: ReplaceJsonResourceRequest,
    x_actor_ref: str | None = Header(default=None, alias="X-Actor-Ref"),
    x_request_id: str | None = Header(default=None, alias="X-Request-Id"),
):
    try:
        return await edit_service.apply_edit(
            book_id=book_id,
            resource_type="chapter",
            resource_key=f"{chapter_number:04d}:guide",
            base_version=body.base_version,
            new_content=body.content,
            source="portal_user",
            source_detail="portal:manual_edit",
            actor_ref=_actor(x_actor_ref, body.actor_ref),
            request_id=_request_id(x_request_id, body.request_id),
            reason=body.reason,
        )
    except Exception as exc:
        logger.exception(
            "更新章节大纲失败: book_id=%s chapter=%s", book_id, chapter_number
        )
        _raise_http(exc)


@v1_router.get("/books/{book_id}/chapters/{chapter_number}/state")
async def get_chapter_state(book_id: str, chapter_number: int):
    try:
        return await dao.get_chapter_state(book_id, chapter_number)
    except Exception as exc:
        logger.exception(
            "获取章节状态失败: book_id=%s chapter=%s", book_id, chapter_number
        )
        _raise_http(exc)


@v1_router.get("/books/{book_id}/characters")
async def list_characters(book_id: str):
    try:
        return await dao.list_characters(book_id)
    except Exception as exc:
        logger.exception("获取角色列表失败: book_id=%s", book_id)
        _raise_http(exc)


@v1_router.get("/books/{book_id}/characters/{name}")
async def get_character(book_id: str, name: str):
    try:
        return await dao.get_character(book_id, name)
    except Exception as exc:
        logger.exception("获取角色失败: book_id=%s name=%s", book_id, name)
        _raise_http(exc)


@v1_router.put("/books/{book_id}/characters/{name}")
async def update_character(
    book_id: str,
    name: str,
    body: ReplaceJsonResourceRequest,
    x_actor_ref: str | None = Header(default=None, alias="X-Actor-Ref"),
    x_request_id: str | None = Header(default=None, alias="X-Request-Id"),
):
    try:
        return await edit_service.apply_edit(
            book_id=book_id,
            resource_type="character",
            resource_key=name,
            base_version=body.base_version,
            new_content=body.content,
            source="portal_user",
            source_detail="portal:manual_edit",
            actor_ref=_actor(x_actor_ref, body.actor_ref),
            request_id=_request_id(x_request_id, body.request_id),
            reason=body.reason,
        )
    except Exception as exc:
        logger.exception("更新角色失败: book_id=%s name=%s", book_id, name)
        _raise_http(exc)


@v1_router.get("/books/{book_id}/outlines")
async def list_outlines(book_id: str):
    try:
        return await dao.list_outlines(book_id)
    except Exception as exc:
        logger.exception("获取大纲列表失败: book_id=%s", book_id)
        _raise_http(exc)


@v1_router.get("/books/{book_id}/outlines/volume/latest")
async def get_latest_volume_outline(book_id: str):
    try:
        return await dao.get_latest_outline(book_id, "volume")
    except Exception as exc:
        logger.exception("获取最新卷纲失败: book_id=%s", book_id)
        _raise_http(exc)


@v1_router.get("/books/{book_id}/outlines/near-term/latest")
async def get_latest_near_term_outline(book_id: str):
    try:
        return await dao.get_latest_outline(book_id, "near_term")
    except Exception as exc:
        logger.exception("获取最新近纲失败: book_id=%s", book_id)
        _raise_http(exc)


@v1_router.get("/books/{book_id}/outlines/volume/{volume_number}")
async def get_volume_outline(book_id: str, volume_number: int):
    try:
        return await dao.get_outline(book_id, "volume", volume_number)
    except Exception as exc:
        logger.exception("获取卷纲失败: book_id=%s volume=%s", book_id, volume_number)
        _raise_http(exc)


@v1_router.put("/books/{book_id}/outlines/volume/{volume_number}")
async def update_volume_outline(
    book_id: str,
    volume_number: int,
    body: ReplaceJsonResourceRequest,
    x_actor_ref: str | None = Header(default=None, alias="X-Actor-Ref"),
    x_request_id: str | None = Header(default=None, alias="X-Request-Id"),
):
    try:
        return await edit_service.apply_edit(
            book_id=book_id,
            resource_type="outline",
            resource_key=f"volume:{volume_number}",
            base_version=body.base_version,
            new_content=body.content,
            source="portal_user",
            source_detail="portal:manual_edit",
            actor_ref=_actor(x_actor_ref, body.actor_ref),
            request_id=_request_id(x_request_id, body.request_id),
            reason=body.reason,
        )
    except Exception as exc:
        logger.exception("更新卷纲失败: book_id=%s volume=%s", book_id, volume_number)
        _raise_http(exc)


@v1_router.get("/books/{book_id}/outlines/near-term/{volume_number}")
async def get_near_term_outline(book_id: str, volume_number: int):
    try:
        return await dao.get_outline(book_id, "near_term", volume_number)
    except Exception as exc:
        logger.exception("获取近纲失败: book_id=%s volume=%s", book_id, volume_number)
        _raise_http(exc)


@v1_router.put("/books/{book_id}/outlines/near-term/{volume_number}")
async def update_near_term_outline(
    book_id: str,
    volume_number: int,
    body: ReplaceJsonResourceRequest,
    x_actor_ref: str | None = Header(default=None, alias="X-Actor-Ref"),
    x_request_id: str | None = Header(default=None, alias="X-Request-Id"),
):
    try:
        return await edit_service.apply_edit(
            book_id=book_id,
            resource_type="outline",
            resource_key=f"near_term:{volume_number}",
            base_version=body.base_version,
            new_content=body.content,
            source="portal_user",
            source_detail="portal:manual_edit",
            actor_ref=_actor(x_actor_ref, body.actor_ref),
            request_id=_request_id(x_request_id, body.request_id),
            reason=body.reason,
        )
    except Exception as exc:
        logger.exception("更新近纲失败: book_id=%s volume=%s", book_id, volume_number)
        _raise_http(exc)


@v1_router.get("/books/{book_id}/hooks")
async def list_hooks(book_id: str):
    try:
        return await dao.list_hooks(book_id)
    except Exception as exc:
        logger.exception("获取伏笔失败: book_id=%s", book_id)
        _raise_http(exc)


@v1_router.put("/books/{book_id}/hooks/{item_id}")
async def update_hook(
    book_id: str,
    item_id: str,
    body: UpdateHookRequest,
    x_actor_ref: str | None = Header(default=None, alias="X-Actor-Ref"),
    x_request_id: str | None = Header(default=None, alias="X-Request-Id"),
):
    try:
        return await edit_service.apply_edit(
            book_id=book_id,
            resource_type="hook",
            resource_key=item_id,
            base_version=None,
            new_content=body.dict(
                exclude_none=True, exclude={"reason", "actor_ref", "request_id"}
            ),
            source="portal_user",
            source_detail="portal:manual_edit",
            actor_ref=_actor(x_actor_ref, body.actor_ref),
            request_id=_request_id(x_request_id, body.request_id),
            reason=body.reason,
            enforce_version=False,
        )
    except Exception as exc:
        logger.exception("更新伏笔失败: book_id=%s item_id=%s", book_id, item_id)
        _raise_http(exc)


@v1_router.get("/books/{book_id}/debts")
async def list_debts(book_id: str):
    try:
        return await dao.list_debts(book_id)
    except Exception as exc:
        logger.exception("获取债务失败: book_id=%s", book_id)
        _raise_http(exc)


@v1_router.put("/books/{book_id}/debts/{item_id}")
async def update_debt(
    book_id: str,
    item_id: str,
    body: UpdateDebtRequest,
    x_actor_ref: str | None = Header(default=None, alias="X-Actor-Ref"),
    x_request_id: str | None = Header(default=None, alias="X-Request-Id"),
):
    try:
        return await edit_service.apply_edit(
            book_id=book_id,
            resource_type="debt",
            resource_key=item_id,
            base_version=None,
            new_content=body.dict(
                exclude_none=True, exclude={"reason", "actor_ref", "request_id"}
            ),
            source="portal_user",
            source_detail="portal:manual_edit",
            actor_ref=_actor(x_actor_ref, body.actor_ref),
            request_id=_request_id(x_request_id, body.request_id),
            reason=body.reason,
            enforce_version=False,
        )
    except Exception as exc:
        logger.exception("更新债务失败: book_id=%s item_id=%s", book_id, item_id)
        _raise_http(exc)


@v1_router.get("/books/{book_id}/resources/{resource_type}/{resource_key}/revisions")
async def list_revisions(book_id: str, resource_type: str, resource_key: str):
    try:
        return await dao.list_revisions(book_id, resource_type, resource_key)
    except Exception as exc:
        logger.exception(
            "获取修订历史失败: book_id=%s resource=%s/%s",
            book_id,
            resource_type,
            resource_key,
        )
        _raise_http(exc)


@v1_router.get(
    "/books/{book_id}/resources/{resource_type}/{resource_key}/revisions/{revision_id}"
)
async def get_revision(
    book_id: str, resource_type: str, resource_key: str, revision_id: str
):
    try:
        return await dao.get_revision(book_id, resource_type, resource_key, revision_id)
    except Exception as exc:
        logger.exception(
            "获取修订详情失败: book_id=%s resource=%s/%s rev=%s",
            book_id,
            resource_type,
            resource_key,
            revision_id,
        )
        _raise_http(exc)


@v1_router.get("/jobs/{job_id}")
async def get_job(job_id: str):
    try:
        return await job_service.get_job(job_id)
    except Exception as exc:
        logger.exception("获取 job 失败: job_id=%s", job_id)
        _raise_http(exc)


@v1_router.get("/jobs/{job_id}/events")
async def get_job_events(job_id: str, after_id: int | None = None):
    try:
        return await job_service.list_events(job_id, after_id)
    except Exception as exc:
        logger.exception("获取 job events 失败: job_id=%s", job_id)
        _raise_http(exc)


@v1_router.post("/jobs/{job_id}/cancel")
async def cancel_job(job_id: str, request: Request):
    try:
        mgr = _get_manager()
        return await job_service.cancel_job(job_id, mgr)
    except Exception as exc:
        logger.exception("取消 job 失败: job_id=%s", job_id)
        _raise_http(exc)


@v1_router.get("/jobs/{job_id}/token-usage")
async def get_job_token_usage(job_id: str, request: Request):
    """获取 Novel Job 的 Token 消耗详情。

    按节点、模型和 agent 类型分别汇总返回。
    """
    try:
        job = await job_service.get_job_internal(job_id)
        workflow_id = job.get("workflow_id")
        task_id = job.get("workflow_task_id")
        if not workflow_id or not task_id:
            raise HTTPException(status_code=400, detail="Job 未绑定工作流任务")

        mgr = _get_manager()
        usage = mgr.get_task_token_usage(workflow_id, task_id)
        if usage is None:
            raise HTTPException(status_code=404, detail="工作流任务不存在")
        return usage

    except HTTPException:
        raise
    except Exception as exc:
        logger.exception("获取 token 消耗失败: job_id=%s", job_id)
        _raise_http(exc)


@v1_router.get("/jobs/{job_id}/stream")
async def stream_job(job_id: str, request: Request, after_id: int | None = None):
    q = _job_queues.get(job_id)
    mgr = _get_manager()
    if q is None:
        q = asyncio.Queue(maxsize=128)
        _job_queues[job_id] = q
    _ensure_job_pump(job_id, mgr)

    last_event_id = _resolve_last_event_id(request, after_id)

    async def event_stream():
        try:
            replayed_terminal = False
            replay_events = await job_service.list_events(job_id, last_event_id)
            for event in replay_events:
                event_type = event.get("event_type") or "message"
                yield _format_sse_event(event_type, event)
                if event_type in ("job_completed", "job_failed", "job_cancelled"):
                    replayed_terminal = True
                    break
            if replayed_terminal:
                return

            while True:
                try:
                    event = await asyncio.wait_for(q.get(), timeout=30.0)
                except asyncio.TimeoutError:
                    yield "event: heartbeat\ndata: {}\n\n"
                    continue
                event_type = event.get("event_type") or event.get("type") or "message"
                yield _format_sse_event(event_type, event)
                if event_type in ("job_completed", "job_failed", "job_cancelled"):
                    break
        except asyncio.CancelledError:
            pass
        finally:
            # Keep the queue until the pump finishes so late readers in the same
            # process can still receive already queued terminal events.
            if job_id not in _job_pumps or _job_pumps[job_id].done():
                _job_queues.pop(job_id, None)

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


def _resolve_last_event_id(request: Request, after_id: int | None) -> int | None:
    header_value = request.headers.get("last-event-id")
    header_id: int | None = None
    if header_value:
        try:
            header_id = int(header_value)
        except ValueError:
            header_id = None
    candidates = [value for value in (after_id, header_id) if value is not None]
    return max(candidates) if candidates else None


def _format_sse_event(event_type: str, event: dict) -> str:
    event_id = event.get("id")
    data = json.dumps(event, ensure_ascii=False, default=str)
    if event_id is None:
        return f"event: {event_type}\ndata: {data}\n\n"
    return f"id: {event_id}\nevent: {event_type}\ndata: {data}\n\n"


def _ensure_job_pump(job_id: str, mgr) -> None:
    """Start at most one workflow-event pump per Novel Job."""
    existing = _job_pumps.get(job_id)
    if existing is not None and not existing.done():
        return
    q = _job_queues.get(job_id)
    if q is None:
        q = asyncio.Queue(maxsize=128)
        _job_queues[job_id] = q
    task = asyncio.create_task(job_service.pump_workflow_events(job_id, mgr, q))
    _job_pumps[job_id] = task

    def _cleanup(done_task: asyncio.Task) -> None:
        current = _job_pumps.get(job_id)
        if current is done_task:
            _job_pumps.pop(job_id, None)

    task.add_done_callback(_cleanup)


# ═══════════════════════════════════════════════════════════
#  Legacy workflow task SSE helpers
# ═══════════════════════════════════════════════════════════


async def _pump_task_events(task_id: str, workflow_id: str, mgr) -> None:
    prev_states: dict[str, str] = {}
    try:
        while True:
            await asyncio.sleep(1.5)
            task_data = mgr.get_task(workflow_id, task_id)
            if task_data is None:
                break
            node_states: dict = task_data.get("node_states", {})
            for nid, ns in node_states.items():
                status = ns.get("status", "pending")
                prev = prev_states.get(nid)
                if status == prev:
                    continue
                prev_states[nid] = status
                label = ns.get("node_label", nid)
                if status == "running":
                    _push_to_queue(
                        task_id,
                        {"node": nid, "label": label, "status": "running"},
                        "node_update",
                    )
                elif status in ("completed", "success"):
                    _push_to_queue(
                        task_id,
                        {
                            "node": nid,
                            "label": label,
                            "status": "done",
                            "summary": ns.get("summary", ""),
                            "output": ns.get("outputs", {}),
                        },
                        "node_done",
                    )
                elif status == "failed":
                    _push_to_queue(
                        task_id,
                        {
                            "node": nid,
                            "label": label,
                            "status": "failed",
                            "error": ns.get("error", ""),
                        },
                        "node_failed",
                    )
            task_status = task_data.get("status", "")
            if task_status in ("completed", "failed", "stopped"):
                if task_status == "completed":
                    _push_to_queue(
                        task_id,
                        {
                            "status": "completed",
                            "total_nodes": len(task_data.get("node_states", {})),
                        },
                        "task_completed",
                    )
                else:
                    _push_to_queue(
                        task_id,
                        {"status": task_status, "error": task_data.get("error", "")},
                        "task_failed",
                    )
                break
    except Exception:
        logger.exception("任务事件泵异常: task_id=%s", task_id)
        _push_to_queue(
            task_id, {"status": "failed", "error": "内部错误"}, "task_failed"
        )
    finally:
        await asyncio.sleep(5)
        _task_queues.pop(task_id, None)


def _push_to_queue(task_id: str, data: dict, event_type: str) -> None:
    q = _task_queues.get(task_id)
    if q is None:
        return
    try:
        q.put_nowait({"type": event_type, "data": data})
    except asyncio.QueueFull:
        pass


def _map_event_type(event: dict) -> str:
    t = event.get("type", "")
    if t == "initial_state":
        return "task_update"
    if t in {
        "node_update",
        "node_done",
        "node_failed",
        "task_completed",
        "task_failed",
    }:
        return t
    return "message"


router.include_router(legacy_router)
router.include_router(v1_router)


async def shutdown_background_tasks() -> None:
    tasks = [task for task in _job_pumps.values() if not task.done()]
    for task in tasks:
        task.cancel()
    if tasks:
        await asyncio.gather(*tasks, return_exceptions=True)
    _job_pumps.clear()
    _job_queues.clear()
    _task_queues.clear()

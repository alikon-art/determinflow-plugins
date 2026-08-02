"""Pydantic schemas for the novel production API."""
from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field


JsonDict = dict[str, Any]


class CreateBookRequest(BaseModel):
    title: str = Field(..., description="书名")
    external_ref: str | None = Field(default=None, description="门户项目或外部业务引用")
    genre: str | None = Field(default=None, description="题材")
    settings: JsonDict = Field(default_factory=dict, description="书级配置")


class UpdateBookRequest(BaseModel):
    base_version: int | None = Field(default=None, description="book:meta 的当前版本")
    title: str | None = None
    status: str | None = None
    genre: str | None = None
    estimated_length: str | None = None
    words_per_chapter: str | None = None
    settings: JsonDict | None = None
    reason: str | None = None
    actor_ref: str | None = None
    request_id: str | None = None


class BuildWorldRequest(BaseModel):
    premise: str = Field(..., description="题材创意")
    genre: str = Field(default="东方玄幻", description="题材类型")
    language: str = Field(default="中文", description="输出语言")


class BuildCharacterRequest(BaseModel):
    premise: str = Field(..., description="题材创意")
    genre: str = Field(default="东方玄幻", description="题材类型")
    language: str = Field(default="中文", description="输出语言")


class BuildStoryPlanRequest(BaseModel):
    premise: str = Field(..., description="题材创意")
    genre: str = Field(default="东方玄幻", description="题材类型")
    language: str = Field(default="中文", description="输出语言")


class BuildOutlineRequest(BaseModel):
    volume_number: int | None = Field(default=None, description="目标卷号。不传则自动取已有最大卷号+1（创建新卷），传数字则重写对应卷")
    latest_chapter: str = Field(default="0000", description="当前已完成的最后一章。0000=尚未开始（引擎自动填充，门户可不传）")
    estimated_length: str = Field(default="中", description="全书预计篇幅：短/中/长。影响卷数和每卷章数")
    words_per_chapter: str = Field(default="2000-2500", description="每章预计字数范围。影响每章能承载的情节密度")


class GenerateChapterRequest(BaseModel):
    prev_chapter: str = Field(default="0000", description="上一章节号")
    human_intent: str = Field(default="", description="人类对本章的意图指令")
    world_intent: str = Field(default="", description="世界层的人类意图。直入世界状态机，注入世界级推力（瘟疫、天灾、势力变动等）")
    target_word_count: str = Field(default="3000-4000", description="目标字数范围")
    language: str = Field(default="中文", description="输出语言")
    writer_type: Literal["single", "muti"] = Field(default="single", description="写手类型。single=单写手一次成稿（默认），muti=写手群6+1")


class PolishChapterRequest(BaseModel):
    language: str = Field(default="中文", description="输出语言")


class PostHocChapterRequest(BaseModel):
    language: str = Field(default="中文", description="输出语言")


class ReplaceJsonResourceRequest(BaseModel):
    base_version: int = Field(..., description="资源当前版本")
    content: Any = Field(..., description="替换后的完整资源内容")
    reason: str | None = None
    actor_ref: str | None = None
    request_id: str | None = None


class ReplaceChapterBodyRequest(BaseModel):
    base_version: int = Field(..., description="章节正文当前版本")
    body: str = Field(..., description="替换后的完整正文")
    title: str | None = None
    status: str | None = None
    reason: str | None = None
    actor_ref: str | None = None
    request_id: str | None = None


class UpdateHookRequest(BaseModel):
    description: str | None = None
    status: str | None = None
    chapter_created: int | None = None
    chapter_resolved: int | None = None
    expected_payoff: str | None = None
    last_advanced: int | None = None
    source: str | None = None
    content: JsonDict | None = None
    reason: str | None = None
    actor_ref: str | None = None
    request_id: str | None = None


class UpdateDebtRequest(BaseModel):
    description: str | None = None
    status: str | None = None
    chapter_created: int | None = None
    chapter_resolved: int | None = None
    expected_payoff: str | None = None
    last_advanced: int | None = None
    source: str | None = None
    from_char: str | None = None
    to_char: str | None = None
    content: JsonDict | None = None
    reason: str | None = None
    actor_ref: str | None = None
    request_id: str | None = None


class RollbackRequest(BaseModel):
    base_version: int
    target_version: int
    reason: str | None = None
    actor_ref: str | None = None
    request_id: str | None = None


class EditResult(BaseModel):
    book_id: str
    resource_type: str
    resource_key: str
    version: int | None = None
    revision_id: str
    updated_at: str | None = None


class JobCreateResult(BaseModel):
    job_id: str
    operation: str
    status: str
    stream_url: str


class ErrorResponse(BaseModel):
    error: str
    message: str
    details: JsonDict = Field(default_factory=dict)


EditSource = Literal["workflow", "portal_user", "polish", "system", "rollback", "import"]

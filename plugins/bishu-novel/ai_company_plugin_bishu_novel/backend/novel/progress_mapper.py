"""Map internal workflow nodes to public novel production stages."""
from __future__ import annotations

from dataclasses import dataclass

from .resource_ids import workflow_for_operation


@dataclass(frozen=True)
class Stage:
    node_id: str
    stage_id: str
    name: str
    progress: float
    resource_type: str | None = None
    resource_key: str | None = None
    artifact_path: str | None = None
    content_available: bool = False
    read_path: str | None = None


OPERATION_STAGES = {
    "world_build": [
        Stage("agent_corelaws", "core_laws", "生成核心法则", 0.10, "world", "core_laws", "world/core_laws.json", False),
        Stage("script_persist_corelaws", "core_laws", "写入核心法则", 0.15, "world", "core_laws", "world/core_laws.json", True, "/api/v1/novel/books/{book_id}/world/core_laws"),
        Stage("agent_spacetime", "space_time", "生成时空地理", 0.25, "world", "space_time", "world/space_time.json", False),
        Stage("script_persist_spacetime", "space_time", "写入时空地理", 0.30, "world", "space_time", "world/space_time.json", True, "/api/v1/novel/books/{book_id}/world/space_time"),
        Stage("agent_society", "society", "生成社会权力结构", 0.40, "world", "society", "world/society.json", False),
        Stage("script_persist_society", "society", "写入社会权力结构", 0.45, "world", "society", "world/society.json", True, "/api/v1/novel/books/{book_id}/world/society"),
        Stage("agent_historyculture", "history_culture", "生成历史文化", 0.55, "world", "history_culture", "world/history_culture.json", False),
        Stage("script_persist_historyculture", "history_culture", "写入历史文化", 0.60, "world", "history_culture", "world/history_culture.json", True, "/api/v1/novel/books/{book_id}/world/history_culture"),
        Stage("agent_existence", "existence", "生成存在基础", 0.70, "world", "existence", "world/existence.json", False),
        Stage("script_persist_existence", "existence", "写入存在基础", 0.75, "world", "existence", "world/existence.json", True, "/api/v1/novel/books/{book_id}/world/existence"),
        Stage("agent_information", "information", "生成信息传播结构", 0.88, "world", "information", "world/information.json", False),
        Stage("script_persist_information", "information", "写入信息传播结构", 0.93, "world", "information", "world/information.json", True, "/api/v1/novel/books/{book_id}/world/information"),
        Stage("script_merge_world", "world_document", "拼接世界观文档", 1.00),
    ],
    "character_build": [
        Stage("script_sync_down", "prepare_context", "准备上下文", 0.05),
        Stage("agent_skeleton", "skeleton", "生成角色阵容", 0.12),
        Stage("script_persist_skeleton", "skeleton", "写入角色阵容", 0.18,
              resource_type="character", resource_key="skeleton",
              artifact_path="cache/character/skeleton.json",
              content_available=True, read_path="/api/v1/novel/books/{book_id}/characters"),
        Stage("agent_belief", "beliefs", "生成信念生态", 0.32),
        Stage("script_persist_belief", "beliefs", "写入信念生态", 0.38,
              resource_type="character", resource_key="beliefs",
              artifact_path="cache/character/beliefs.json",
              content_available=True, read_path="/api/v1/novel/books/{book_id}/characters"),
        Stage("agent_deep", "deep_profile", "生成深层维度", 0.50),
        Stage("script_persist_deep", "deep_profile", "写入深层维度", 0.55,
              resource_type="character", resource_key="deep",
              artifact_path="cache/character/{name}_deep.json",
              content_available=True, read_path="/api/v1/novel/books/{book_id}/characters/{name}"),
        Stage("agent_voice", "voice", "生成角色声线", 0.80),
        Stage("script_persist_voice", "voice", "写入角色声线", 0.85,
              resource_type="character", resource_key="voice",
              artifact_path="cache/character/voice.json",
              content_available=True, read_path="/api/v1/novel/books/{book_id}/characters"),
        Stage("script_merge", "render_md", "渲染角色文档", 1.00),
    ],
    "story_plan_build": [
        Stage("script_sync_down", "prepare_context", "同步世界观与角色", 0.10),
        Stage("agent_mpvb7xer_1", "story_plan", "生成故事宏观规划", 0.30),
        Stage("script_persist_story_plan", "story_plan", "写入故事规划", 0.38,
              resource_type="book", resource_key="story_plan",
              artifact_path="cache/story_plan/story_plan.json",
              content_available=True, read_path="/api/v1/novel/books/{book_id}/story-plan"),
        Stage("agent_style", "style_profile", "生成风格档案", 0.70),
        Stage("script_persist_style_profile", "style_profile", "写入风格档案", 0.78,
              resource_type="book", resource_key="style_profile",
              artifact_path="cache/story_plan/style_profile.json",
              content_available=True, read_path="/api/v1/novel/books/{book_id}/style-profile"),
        Stage("script_render_style", "render_md", "渲染文档", 1.00),
    ],
    "outline_build": [
        Stage("script_sync_down", "prepare_context", "同步规划上下文", 0.10),
        Stage("agent_vo", "volume_outline", "生成卷纲", 0.45),
        Stage("script_sync_up_vo", "persist_volume", "写入卷纲", 0.60,
              resource_type="outline", resource_key="volume",
              content_available=True, read_path="/api/v1/novel/books/{book_id}/outlines/volume/latest"),
        Stage("agent_no", "near_term_outline", "生成近纲", 0.85),
        Stage("script_sync_up_no", "persist_near_term", "写入近纲", 1.00,
              resource_type="outline", resource_key="near_term",
              content_available=True, read_path="/api/v1/novel/books/{book_id}/outlines/near-term/latest"),
    ],
    "chapter_generate": [
        Stage("script_sync_down", "prepare_context", "同步创作上下文", 0.05),
        Stage("agent_we", "world_state", "推演本章世界状态", 0.12),
        Stage("sync_up_we", "world_ready", "写入世界推演", 0.18,
              resource_type="chapter", resource_key="world_state",
              content_available=True, read_path="/api/v1/novel/books/{book_id}/chapters/{chapter_number}/world"),
        Stage("agent_id", "intent_dispatch", "解析创作意图", 0.22),
        Stage("agent_od", "chapter_guide", "生成章节大纲", 0.32),
        Stage("sync_up_od", "guide_ready", "写入章节大纲", 0.38,
              resource_type="chapter", resource_key="guide",
              content_available=True, read_path="/api/v1/novel/books/{book_id}/chapters/{chapter_number}/guide"),
        Stage("agent_cm", "character_state", "更新角色状态", 0.42),
        Stage("agent_se", "storyboard", "生成章节设计", 0.55),
        Stage("agent_nw", "skeleton", "生成章节骨架", 0.65),
        Stage("agent_sw", "compose", "单写手生成章节", 0.85),
        Stage("agent_si", "compose", "整合章节正文", 0.90),
        Stage("sync_up_si", "body_ready", "写入章节正文", 1.00,
              resource_type="chapter", resource_key="body",
              content_available=True, read_path="/api/v1/novel/books/{book_id}/chapters/{chapter_number}"),
    ],
    "chapter_polish": [
        Stage("script_sync_down", "prepare_context", "同步章节正文", 0.10),
        Stage("agent_sc", "self_critique", "自审章节", 0.30),
        Stage("agent_pl", "humanize", "人文化润色", 0.60),
        Stage("agent_pp", "professional_polish", "专业润色", 0.85),
        Stage("script_sync_polish", "polish_ready", "写入润色版本", 1.00,
              resource_type="chapter", resource_key="body",
              content_available=True, read_path="/api/v1/novel/books/{book_id}/chapters/{chapter_number}"),
    ],
    "post_hoc": [
        Stage("script_sync_down", "prepare_context", "同步章节上下文", 0.10),
        Stage("agent_obs", "observe", "观察章节差异", 0.45),
        Stage("agent_arb", "arbitrate", "执行后验裁决", 0.80),
        Stage("script_sync_up", "post_hoc_ready", "写入后验状态", 1.00,
              resource_type="chapter", resource_key="state",
              content_available=True, read_path="/api/v1/novel/books/{book_id}/chapters/{chapter_number}/state"),
    ],
}
class ProgressMapper:
    def __init__(self, operation: str):
        self.operation = operation
        self._stages = OPERATION_STAGES.get(operation, [])
        self._by_node = {s.node_id: s for s in self._stages}

    def map_node(self, node_id: str, node_status: str) -> dict | None:
        stage = self._by_node.get(node_id)
        if stage is None:
            return None
        if node_status == "running":
            event = "stage_started"
        elif node_status in ("completed", "success"):
            event = "stage_completed"
        elif node_status == "failed":
            event = "stage_failed"
        else:
            return None
        if stage.content_available and node_status in ("completed", "success"):
            event = "stage_ready"
        return {
            "event_type": event,
            "stage_id": stage.stage_id,
            "stage_name": stage.name,
            "progress": stage.progress,
            "resource_type": stage.resource_type,
            "resource_key": stage.resource_key,
            "artifact_path": stage.artifact_path,
            "content_available": stage.content_available and node_status in ("completed", "success"),
            "read_path": stage.read_path,
        }

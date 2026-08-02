"""Resolve workflow IDs bundled with the Bishu Novel plugin."""

from __future__ import annotations

from collections.abc import Callable


BISHU_NOVEL_PLUGIN_ID = "bishu-novel"

OPERATION_WORKFLOW_LOCAL_IDS = {
    "world_build": "build",
    "character_build": "character",
    "story_plan_build": "story-plan",
    "outline_build": "outline",
    "chapter_generate": "mvp",
    "chapter_polish": "polish",
    "post_hoc": "post-hoc",
}

CORE_RESOURCE_RESOLVER_REQUIRED = (
    "bishu-novel 要求 DeterminFlow Core 提供 CoreRuntime.resolve_resource"
)

ResourceResolver = Callable[..., str]
_resource_resolver: ResourceResolver | None = None


def configure_resource_resolver(resolver: ResourceResolver | None) -> None:
    """Inject Core's public resource resolver."""
    global _resource_resolver
    _resource_resolver = resolver


def workflow_for_operation(operation: str) -> str:
    """Return the effective workflow ID for one public Novel operation."""
    local_id = OPERATION_WORKFLOW_LOCAL_IDS[operation]
    if _resource_resolver is None:
        raise RuntimeError(CORE_RESOURCE_RESOLVER_REQUIRED)
    return _resource_resolver(
        "workflow",
        local_id,
        plugin_id=BISHU_NOVEL_PLUGIN_ID,
    )

from __future__ import annotations

import pytest

from ai_company_plugin_bishu_novel.backend.novel import resource_ids


@pytest.fixture(autouse=True)
def _reset_resource_resolver():
    resource_ids.configure_resource_resolver(None)
    yield
    resource_ids.configure_resource_resolver(None)


def test_missing_core_resolver_fails_closed() -> None:
    with pytest.raises(
        RuntimeError,
        match=r"CoreRuntime\.resolve_resource",
    ):
        resource_ids.workflow_for_operation("world_build")


def test_new_core_resolves_cross_plugin_local_workflow_id() -> None:
    calls: list[tuple[str, str, str | None]] = []

    def resolve(
        resource_type: str,
        local_id: str,
        *,
        plugin_id: str | None = None,
    ) -> str:
        calls.append((resource_type, local_id, plugin_id))
        return f"custom-{local_id}"

    resource_ids.configure_resource_resolver(resolve)

    assert resource_ids.workflow_for_operation("world_build") == "custom-build"
    assert calls == [("workflow", "build", "bishu-novel")]


def test_resolver_failure_is_not_hidden() -> None:
    def resolve(*_args, **_kwargs) -> str:
        raise LookupError("missing resource")

    resource_ids.configure_resource_resolver(resolve)

    with pytest.raises(LookupError, match="missing resource"):
        resource_ids.workflow_for_operation("outline_build")

"""Workflow adapter for novel production operations."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from src.extension_api import WorkflowRuntime


@dataclass
class WorkflowHandle:
    workflow_id: str
    task_id: str


class WorkflowAdapter:
    """Thin boundary around the in-process WorkflowManager.

    Future split-out deployments should replace this class with an HTTP client
    without changing the Novel API service layer above it.
    """

    def __init__(self, manager: WorkflowRuntime):
        self.manager = manager

    def _merge_variable_defaults(
        self,
        workflow_id: str,
        parameter_values: dict[str, Any],
    ) -> dict[str, Any]:
        """Apply workflow variable defaults before creating a task.

        WorkflowManager.create_task() is the low-level API and does not copy
        variable defaults into task.parameter_values. The UI/pre-start path does
        this itself. Novel API uses create_task() directly, so it must preserve
        the same behavior here, especially for file variables such as
        meta/world_foundation.md.
        """
        wf_data = self.manager.get_workflow(workflow_id)
        definition = (wf_data or {}).get("definition") or {}
        merged: dict[str, Any] = {}
        for var in definition.get("variables", []):
            key = var.get("key")
            if not key:
                continue
            default = var.get("default")
            if default not in (None, ""):
                merged[key] = default
        merged.update(parameter_values or {})
        return merged

    def prepare_workflow(
        self,
        workflow_id: str,
        parameter_values: dict[str, Any],
        workspace_override: str | None = None,
    ) -> WorkflowHandle:
        """Create a durable pending Workflow task without executing it.

        Novel Job persistence and Workflow execution have different storage
        boundaries.  Keeping preparation separate lets the service bind the
        Core task identity to ``novel_job`` before any model call can start.
        """
        result = self.manager.create_task(
            workflow_id,
            parameter_values=self._merge_variable_defaults(
                workflow_id, parameter_values
            ),
            workspace_override=workspace_override,
        )
        if result is None:
            raise RuntimeError("创建工作流任务失败")
        return WorkflowHandle(workflow_id=workflow_id, task_id=result["task_id"])

    async def start_prepared_workflow(self, handle: WorkflowHandle) -> WorkflowHandle:
        """Start a Workflow task previously created by :meth:`prepare_workflow`."""
        run_result = await self.manager.run_task(handle.workflow_id, handle.task_id)
        if not run_result.get("success"):
            raise RuntimeError(run_result.get("message", "启动工作流任务失败"))
        return handle

    async def discard_prepared_workflow(self, handle: WorkflowHandle) -> bool:
        """Delete a pending task, or stop it if execution was partially started."""
        result = await self.manager.stop_task(handle.workflow_id, handle.task_id)
        return bool(result and result.get("success"))

    async def start_workflow(
        self,
        workflow_id: str,
        parameter_values: dict[str, Any],
        workspace_override: str | None = None,
    ) -> WorkflowHandle:
        """Compatibility helper for callers that do not need pre-start persistence."""
        handle = self.prepare_workflow(
            workflow_id,
            parameter_values=parameter_values,
            workspace_override=workspace_override,
        )
        try:
            return await self.start_prepared_workflow(handle)
        except Exception:
            await self.discard_prepared_workflow(handle)
            raise

    def get_task_snapshot(self, workflow_id: str, task_id: str) -> dict | None:
        return self.manager.get_task(workflow_id, task_id)

    async def cancel_task(self, workflow_id: str, task_id: str) -> bool:
        result = await self.manager.stop_task(workflow_id, task_id)
        return bool(result and result.get("success"))

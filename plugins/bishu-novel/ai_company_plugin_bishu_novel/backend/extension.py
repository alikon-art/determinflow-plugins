"""Bishu Novel engine extension entrypoint."""

import logging
from collections.abc import Mapping

from src.extension_api import ExtensionManifest

from . import config as backend_config
from .engine_auth_middleware import EngineAuthMiddleware
from .novel import db as database
from .novel.resource_ids import (
    CORE_RESOURCE_RESOLVER_REQUIRED,
    configure_resource_resolver,
)
from .routes import (
    configure_workflow_runtime,
    job_service,
    router,
    shutdown_background_tasks,
)

logger = logging.getLogger(__name__)


def _require_resource_resolver(runtime):
    resolver = getattr(runtime, "resolve_resource", None)
    if not callable(resolver):
        raise RuntimeError(CORE_RESOURCE_RESOLVER_REQUIRED)
    return resolver


class BishuNovelExtension:
    manifest = ExtensionManifest(
        extension_id="bishu-novel",
        name="Bishu Novel",
        version="0.1.0",
    )

    def register(self, registrar) -> None:
        self.manifest = registrar.manifest
        registrar.add_middleware(EngineAuthMiddleware)
        registrar.add_router(router)

    async def start(self, runtime) -> None:
        plugin_config = runtime.get_service("plugin_config", {})
        if not isinstance(plugin_config, Mapping):
            raise RuntimeError("plugin_config 必须是 object")
        resolver = _require_resource_resolver(runtime)
        backend_config.configure(plugin_config)
        database.configure(plugin_config)
        backend_config.validate_engine_signing_config()
        configure_workflow_runtime(runtime.workflow_runtime)
        configure_resource_resolver(resolver)
        try:
            await job_service.cleanup_zombie_jobs()
        except Exception as exc:
            logger.warning(
                "Novel 数据库初始化失败: %s",
                type(exc).__name__,
            )
            raise RuntimeError(
                f"Novel 数据库不可用: {type(exc).__name__}"
            ) from None

    async def stop(self) -> None:
        configure_workflow_runtime(None)
        configure_resource_resolver(None)
        await shutdown_background_tasks()
        await database.close_pool()


def create_extension() -> BishuNovelExtension:
    return BishuNovelExtension()

from fastapi import FastAPI

from ai_company_plugin_bishu_novel.backend.routes import router


def test_novel_openapi_operation_ids_are_unique():
    app = FastAPI()
    app.include_router(router)
    schema = app.openapi()
    operation_ids = [
        operation["operationId"]
        for methods in schema["paths"].values()
        for operation in methods.values()
        if isinstance(operation, dict) and "operationId" in operation
    ]

    assert len(operation_ids) == len(set(operation_ids))

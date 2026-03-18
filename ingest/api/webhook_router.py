from typing import Any, Callable

from fastapi import APIRouter, BackgroundTasks, Request


def build_webhook_router(
    webhook_handler_fn: Callable[[Request, BackgroundTasks], Any],
) -> APIRouter:
    router = APIRouter(tags=["webhook"])

    @router.post("/webhook")
    @router.post("/api/simple-webhook")
    async def simple_webhook(request: Request, background_tasks: BackgroundTasks):
        return await webhook_handler_fn(request, background_tasks)

    return router

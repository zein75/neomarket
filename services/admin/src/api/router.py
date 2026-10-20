from fastapi import APIRouter
from fastapi.routing import APIRoute

from src.services.audit_context import bind_request_context, reset_request_context


class AdminAPIRoute(APIRoute):
    def __init__(self, *args, **kwargs):
        if kwargs.get("response_model") is not None:
            kwargs["response_model_exclude_none"] = True
        super().__init__(*args, **kwargs)

    def get_route_handler(self):
        route_handler = super().get_route_handler()

        async def handle_with_audit_context(request):
            token = bind_request_context(getattr(request.state, "request_id", None))
            try:
                return await route_handler(request)
            finally:
                reset_request_context(token)

        return handle_with_audit_context


class AdminRouter(APIRouter):
    def __init__(self, *args, **kwargs):
        kwargs.setdefault("route_class", AdminAPIRoute)
        super().__init__(*args, **kwargs)

from uuid import uuid4
from .config_log import request_id_ctx 

class RequestIDMiddleware:
    """
    - Lấy X-Request-ID nếu client gửi, hoặc tự sinh.
    - Gắn vào ContextVar để filter logging pick up.
    - Phản hồi lại header X-Request-ID để client tiện tra log.
    """
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        rid = request.headers.get("X-Request-ID") or uuid4().hex[:12]
        token = request_id_ctx.set(rid)
        try:
            response = self.get_response(request)
        finally:
            request_id_ctx.reset(token)
        response["X-Request-ID"] = rid
        return response

from __future__ import annotations
import os
import logging
from logging.handlers import RotatingFileHandler
from pathlib import Path
import contextvars

# ==== Paths & env ====
BASE_DIR = Path(__file__).resolve().parent.parent
LOG_DIR = Path(os.getenv("LOG_DIR", BASE_DIR / "logs"))
LOG_DIR.mkdir(parents=True, exist_ok=True)

APP_LEVEL = os.getenv("LOG_LEVEL", "INFO").upper()
DJANGO_LEVEL = os.getenv("DJANGO_LOG_LEVEL", "INFO").upper()
SQL_DEBUG = os.getenv("SQL_LOG", "0") == "1"

# ==== Correlation / Request ID ====
request_id_ctx: contextvars.ContextVar[str] = contextvars.ContextVar("request_id", default="-")

class RequestIDFilter(logging.Filter):
    """Đính kèm request_id (nếu có) vào mọi record để dễ grep/log tập trung."""
    def filter(self, record: logging.LogRecord) -> bool:
        record.request_id = request_id_ctx.get("-")
        return True


SENSITIVE_KEYS = {
    "password", "access", "refresh", "token", "authorization", "secret", "client_secret",
    "api_key", "apikey", "key", "cookie", "cookies"
}
SCRUB_FIELDS = {"body", "payload", "params", "data", "headers", "query", "cookies"}

def scrub_for_log(obj, depth=0):
    if depth > 3:
        return "<deep>"
    try:
        if isinstance(obj, dict):
            out = {}
            for k, v in obj.items():
                if str(k).lower() in SENSITIVE_KEYS:
                    out[k] = "***"
                else:
                    out[k] = scrub_for_log(v, depth + 1)
            return out
        if isinstance(obj, (list, tuple)):
            return [scrub_for_log(x, depth + 1) for x in list(obj)[:50]]
        return obj
    except Exception:
        return "<unserializable>"

class ScrubFilter(logging.Filter):
    """
    - Tự động ẩn các field phổ biến khi dev truyền qua `extra={...}`:
      body, payload, params, data, headers, query, cookies.
    - Nếu record.args là dict/tuple chứa dict → cố gắng scrub luôn.
    """
    def filter(self, record: logging.LogRecord) -> bool:
        # extra fields
        for f in SCRUB_FIELDS:
            if hasattr(record, f):
                try:
                    setattr(record, f, scrub_for_log(getattr(record, f)))
                except Exception:
                    setattr(record, f, "<scrub_failed>")

        # args (format %s): trường hợp dev pass dict trong args
        args = getattr(record, "args", None)
        if isinstance(args, dict):
            record.args = {k: scrub_for_log(v) for k, v in args.items()}
        elif isinstance(args, tuple):
            record.args = tuple(scrub_for_log(v) for v in args)
        return True

# ==== Formatters ====
VERBOSE_FMT = (
    "[%(asctime)s] [%(levelname)s] [%(name)s] "
    "[req=%(request_id)s] %(message)s"
)
SIMPLE_FMT = "%(levelname)s: %(message)s"
DATE_FMT = "%Y-%m-%d %H:%M:%S"

# ==== LOGGING dict cho Django ====
LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,

    "filters": {
        "request_id": {
            "()": RequestIDFilter,  
        },
    },

    "formatters": {
        "verbose": {
            "format": VERBOSE_FMT,
            "datefmt": DATE_FMT,
        },
        "simple": {
            "format": SIMPLE_FMT,
        },
    },

    "handlers": {
        # Console: dùng khi dev / container
        "console": {
            "class": "logging.StreamHandler",
            "level": APP_LEVEL,
            "formatter": "verbose",
            "filters": ["request_id"],
        },

        # File chính cho app
        "app_file": {
            "class": "logging.handlers.RotatingFileHandler",
            "level": APP_LEVEL,
            "formatter": "verbose",
            "filters": ["request_id"],
            "filename": str(LOG_DIR / "app.log"),
            "maxBytes": 10 * 1024 * 1024,   #
            "backupCount": 5,
            "encoding": "utf-8",
        },

        # File lỗi (ERROR+)
        "error_file": {
            "class": "logging.handlers.RotatingFileHandler",
            "level": "ERROR",
            "formatter": "verbose",
            "filters": ["request_id"],
            "filename": str(LOG_DIR / "error.log"),
            "maxBytes": 10 * 1024 * 1024,
            "backupCount": 5,
            "encoding": "utf-8",
        },

        # (tuỳ chọn) SQL log khi bật SQL_LOG=1
        "sql_file": {
            "class": "logging.handlers.RotatingFileHandler",
            "level": "DEBUG",
            "formatter": "verbose",
            "filters": ["request_id"],
            "filename": str(LOG_DIR / "sql.log"),
            "maxBytes": 10 * 1024 * 1024,
            "backupCount": 3,
            "encoding": "utf-8",
        },
    },

    "loggers": {
        # Logger gốc của app mình — dùng __name__ trong code: logging.getLogger(__name__)
        "app": {
            "handlers": ["console", "app_file", "error_file"],
            "level": APP_LEVEL,
            "propagate": False,
        },

        # Django chung
        "django": {
            "handlers": ["console", "app_file", "error_file"],
            "level": DJANGO_LEVEL,
            "propagate": False,
        },

        # Request/response lỗi của Django (500…)
        "django.request": {
            "handlers": ["console", "error_file"],
            "level": "ERROR",
            "propagate": False,
        },

        # ORM SQL — chỉ bật khi SQL_LOG=1
        "django.db.backends": {
            "handlers": (["sql_file", "console"] if SQL_DEBUG else []),
            "level": "DEBUG" if SQL_DEBUG else "WARNING",
            "propagate": False,
        },

        # Root (các logger không đặt tên)
        "": {
            "handlers": ["console", "app_file", "error_file"],
            "level": APP_LEVEL,
        },
    },
}

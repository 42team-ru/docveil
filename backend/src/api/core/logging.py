"""Структурное логирование API: один формат на все хендлеры, request_id в каждой строке.

Раньше в веб-слое логов почти не было — необработанное исключение уходило
только в дефолтный traceback uvicorn без контекста запроса, и найти причину
500 можно было только гаданием (см. AGENTS.md — «очень слабое логирование»).
`configure_logging()` вызывается один раз при импорте `api.main`, до
создания приложения.
"""

from __future__ import annotations

import contextvars
import logging
import logging.config

#: ID текущего запроса — выставляется `RequestIdMiddleware` в `api.main` на
#: входе в обработку и снимается на выходе. `RequestIdFilter` подхватывает
#: его для форматтера, поэтому любая строка лога внутри обработки запроса
#: несёт один и тот же идентификатор — по нему сшиваются записи одного
#: запроса, даже когда между ними другие параллельные запросы.
request_id_var: contextvars.ContextVar[str | None] = contextvars.ContextVar(
    "request_id", default=None
)


class RequestIdFilter(logging.Filter):
    """Прикладывает `request_id` текущего запроса к каждой записи лога."""

    def filter(self, record: logging.LogRecord) -> bool:
        record.request_id = request_id_var.get() or "-"
        return True


def configure_logging(level: str = "INFO") -> None:
    """Настроить логирование процесса: единый формат, request_id, уровень из настроек.

    Переопределяет и логгеры uvicorn — иначе его access/error-строки идут в
    старом формате без `request_id` и путают вывод.
    """
    logging.config.dictConfig(
        {
            "version": 1,
            "disable_existing_loggers": False,
            "filters": {"request_id": {"()": RequestIdFilter}},
            "formatters": {
                "default": {
                    "format": "%(asctime)s %(levelname)s [%(request_id)s] %(name)s: %(message)s",
                },
            },
            "handlers": {
                "console": {
                    "class": "logging.StreamHandler",
                    "formatter": "default",
                    "filters": ["request_id"],
                },
            },
            "root": {"handlers": ["console"], "level": level},
            "loggers": {
                "uvicorn": {"handlers": ["console"], "level": level, "propagate": False},
                "uvicorn.access": {"handlers": ["console"], "level": level, "propagate": False},
                "uvicorn.error": {"handlers": ["console"], "level": level, "propagate": False},
            },
        }
    )

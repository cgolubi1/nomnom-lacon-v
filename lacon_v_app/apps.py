import logging

from django.apps import AppConfig

logger = logging.getLogger(__name__)


class ConventionAppConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "lacon_v_app"

    def ready(self) -> None:
        # Register signal handlers at startup
        try:
            from . import signals  # noqa: F401
        except Exception:
            logger.exception(
                "Failed to import lacon_v_app.signals in AppConfig.ready()"
            )
        return None

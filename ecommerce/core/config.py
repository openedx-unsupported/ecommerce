# pylint: disable=missing-module-docstring

from django.apps import AppConfig


class CoreAppConfig(AppConfig):  # pylint: disable=missing-class-docstring
    name = 'ecommerce.core'
    verbose_name = 'Core'

    def ready(self):
        super().ready()

        # Ensures that the initialized Celery app is loaded when Django starts.
        # Allows Celery tasks to bind themselves to an initialized instance of the Celery library.
        # noinspection PyUnresolvedReferences
        from ecommerce import celery_app  # pylint: disable=unused-import, import-outside-toplevel

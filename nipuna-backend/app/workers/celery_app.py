from celery import Celery

from app.config import get_settings


settings = get_settings()
broker_url = settings.effective_celery_broker_url

broker_transport_options: dict[str, object] = {}
if settings.is_production:
    broker_transport_options = {
        "region": settings.aws_region,
        "queue_name_prefix": "nipuna-",
    }

celery_app = Celery(
    "nipuna_ai_worker",
    broker=broker_url,
    backend=None if settings.is_production else broker_url,
    include=[
        "app.workers.alert_worker",
        "app.workers.sync_worker",
        "app.workers.scheduler_task",
    ],
)

celery_app.conf.update(
    broker_transport_options=broker_transport_options,
    beat_schedule={
        "run-all-alert-checks": {
            "task": "app.workers.alert_worker.run_all_alert_checks",
            "schedule": 3600.0,
        },
        "sync-all-integrations": {
            "task": "app.workers.sync_worker.sync_all_integrations",
            "schedule": 900.0,
        },
        "tick-workflow-scheduler": {
            "task": "app.workers.scheduler_task.tick_scheduled_workflows",
            "schedule": 60.0,
        },
    },
    task_serializer="json",
    task_default_queue="nipuna-jobs",
    accept_content=["json"],
    result_serializer="json",
    timezone="UTC",
    enable_utc=True,
    task_track_started=True,
    worker_prefetch_multiplier=1,
)

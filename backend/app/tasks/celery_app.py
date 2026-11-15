from celery import Celery

from app.config import Settings


def create_celery(settings: Settings) -> Celery:
    app = Celery("enterprise-knowledge-assistant", broker=settings.redis_url)
    app.conf.update(
        task_serializer="json",
        accept_content=["json"],
        result_serializer="json",
        task_ignore_result=True,
        task_acks_late=True,
        task_reject_on_worker_lost=True,
        worker_prefetch_multiplier=1,
        broker_connection_retry_on_startup=True,
        broker_connection_timeout=settings.dependency_timeout,
        task_publish_retry=False,
        broker_transport_options={
            "socket_connect_timeout": settings.dependency_timeout,
            "socket_timeout": settings.dependency_timeout,
            "visibility_timeout": 600,
        },
        task_routes={
            "documents.process": {"queue": "documents"},
            "graph.process": {"queue": "documents"},
            "maintenance.*": {"queue": "maintenance"},
        },
        beat_schedule={
            "recover-and-dispatch": {"task": "maintenance.dispatch", "schedule": 10.0},
            "cleanup-orphans": {"task": "maintenance.cleanup", "schedule": 3600.0},
        },
    )
    return app


celery_app = create_celery(Settings())


@celery_app.task(name="documents.process")
def process(job_id: str):
    from app.tasks.documents import process_document

    process_document(job_id)


@celery_app.task(name="maintenance.dispatch")
def dispatch():
    from app.tasks.dispatch import dispatch_pending, recover_expired

    settings = Settings()
    recover_expired(settings)
    return dispatch_pending(settings)


@celery_app.task(name="maintenance.cleanup")
def cleanup():
    from app.tasks.dispatch import cleanup_orphans

    return cleanup_orphans(Settings())


@celery_app.task(name="graph.process")
def graph_process(job_id: str):
    from uuid import UUID

    from app.tasks.dispatch import dispatch_pending
    from app.tasks.graph import process_graph

    settings = Settings()
    process_graph(job_id, settings)
    dispatch_pending(settings, job_ids=[UUID(job_id)])

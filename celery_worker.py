from celery import Celery

app = Celery(
    'upscale_service',
    broker='redis://redis:6379/0',
    backend='redis://redis:6379/0'
)

app.conf.update(
    task_serializer='json',
    result_serializer='json',
    accept_content=['json'],
    result_expires=3600,
    broker_connection_retry_on_startup=True,
    imports=['tasks'],
)

import os
import logging
import asyncio # Добавляем asyncio
from celery import Celery
from celery.signals import worker_process_init, worker_process_shutdown # Сигналы

from app.db import init_db_pool, close_db_pool # Импортируем функции пула

# --- Настройка логирования --- (Базовая)
LOG_FILE = "app_worker.log"
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler(LOG_FILE), # Вывод в файл
        logging.StreamHandler() # Вывод в консоль
    ]
)
logger = logging.getLogger(__name__)

# Загружаем конфигурацию Celery из переменных окружения
CELERY_BROKER_URL = os.getenv('CELERY_BROKER_URL', 'redis://redis:6379/0')
CELERY_RESULT_BACKEND = os.getenv('CELERY_RESULT_BACKEND', 'redis://redis:6379/0')

# Создаем экземпляр Celery
celery_app = Celery(
    'worker',
    broker=CELERY_BROKER_URL,
    backend=CELERY_RESULT_BACKEND,
    include=['tasks.orders', 'tasks.status_sync'] # Указываем модули с задачами
)

# Настройки Celery (можно вынести в отдельный конфиг)
celery_app.conf.update(
    task_serializer='json',
    accept_content=['json'],  # Допустимые форматы контента
    result_serializer='json',
    timezone='Europe/Moscow', # Пример таймзоны
    enable_utc=True,
    # Настройки для периодических задач (Beat)
    beat_schedule = {
        'retry-pending-orders-every-5-minutes': {
            'task': 'retry_pending_orders',
            'schedule': 300.0, # каждые 5 минут (в секундах)
        },
        # Раскомментируйте и настройте при необходимости
        'sync-statuses-ms-to-wc': {
            'task': 'sync_statuses_from_moysklad_task',
            'schedule': 900.0, # каждые 15 минут
        },
        'sync-statuses-wc-to-ms': {
            'task': 'sync_statuses_to_moysklad_task',
            'schedule': 3600.0, # каждый час
        },
    }
)

# --- Управление пулом соединений БД через сигналы Celery ---
@worker_process_init.connect
def on_worker_init(**kwargs):
    """Инициализация пула при старте воркера Celery."""
    logger.info("Worker process initializing... Setting up DB pool.")
    # Запускаем асинхронную функцию инициализации в event loop
    asyncio.get_event_loop().run_until_complete(init_db_pool())

@worker_process_shutdown.connect
def on_worker_shutdown(**kwargs):
    """Закрытие пула при остановке воркера Celery."""
    logger.info("Worker process shutting down... Closing DB pool.")
    asyncio.get_event_loop().run_until_complete(close_db_pool())

if __name__ == '__main__':
    celery_app.start() 
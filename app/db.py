import asyncpg
import os
import logging
import json # Добавляем импорт json

logger = logging.getLogger(__name__)

DATABASE_URL = os.getenv("DATABASE_URL")
DB_POOL = None # Глобальная переменная для пула

async def init_db_pool():
    """Инициализирует пул соединений asyncpg."""
    global DB_POOL
    if not DATABASE_URL:
        logger.error("DATABASE_URL is not set. Cannot initialize DB Pool.")
        return
    try:
        DB_POOL = await asyncpg.create_pool(
            dsn=DATABASE_URL,
            min_size=1, # Минимальное количество соединений
            max_size=10 # Максимальное количество соединений
        )
        logger.info("Database connection pool initialized.")
    except Exception as e:
        logger.exception("Failed to initialize database connection pool")
        DB_POOL = None

async def close_db_pool():
    """Закрывает пул соединений asyncpg."""
    global DB_POOL
    if DB_POOL:
        await DB_POOL.close()
        logger.info("Database connection pool closed.")
        DB_POOL = None

def get_connection():
    """Возвращает соединение из пула.
    Используется как async context manager: async with get_connection() as conn:
    """
    if not DB_POOL:
        logger.error("DB Pool is not initialized. Cannot get connection.")
        # В реальном приложении здесь лучше выбросить исключение или обработать иначе
        raise ConnectionError("Database pool not available")
    # Возвращаем контекстный менеджер соединения из пула
    return DB_POOL.acquire()

# Сохранение в таблицу отложенной синхронизации
async def save_to_pending(order_id: int, payload: dict, error: str = ""):
    """Сохраняет заказ в таблицу pending_sync при ошибке."""
    if not DB_POOL:
        logger.error("Cannot save to pending: DB Pool is not initialized.")
        return
    try:
        async with get_connection() as conn:
            await conn.execute("""
                INSERT INTO pending_sync (order_id, order_payload, error_message)
                VALUES ($1, $2, $3)
                ON CONFLICT (order_id) DO UPDATE SET
                    order_payload = EXCLUDED.order_payload,
                    error_message = EXCLUDED.error_message,
                    retry_count = pending_sync.retry_count + 1,
                    last_attempt = now();
            """, order_id, json.dumps(payload), error)
        logger.info(f"Order {order_id} saved/updated in pending_sync due to error: {error}")
    except Exception as e:
        logger.exception(f"Failed to save order {order_id} to pending_sync: {e}")

# Функция init_db удалена, так как схема управляется миграциями/SQL скриптами
# async def init_db():
#    conn = await get_connection()
#    await conn.execute("""
#        CREATE TABLE IF NOT EXISTS pending_sync (
#            id SERIAL PRIMARY KEY,
#            order_id INTEGER NOT NULL,
#            order_payload JSONB NOT NULL,
#            retry_count INTEGER DEFAULT 0,
#            last_attempt TIMESTAMP DEFAULT now(),
#            error_message TEXT,
#            created_at TIMESTAMP DEFAULT now()
#        )
#    """)
#    await conn.close() 
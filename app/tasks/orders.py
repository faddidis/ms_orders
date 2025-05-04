import json
import httpx # Используем httpx для асинхронных запросов
import asyncpg
import os
import logging
# Импортируем celery_app из модуля worker
from app.worker import celery_app
from app.db import get_connection # Импортируем функцию для получения соединения

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

# --- Константы и конфигурация ---
MOYSKLAD_API_URL = os.getenv("MOYSKLAD_API_URL", "https://online.moysklad.ru/api/remap/1.2")
MOYSKLAD_TOKEN = os.getenv("MOYSKLAD_TOKEN") # Убираем дефолтное значение, токен обязателен
DATABASE_URL = os.getenv("DATABASE_URL")

WC_API_URL = os.getenv("WC_API_URL") # Обязателен
WC_CONSUMER_KEY = os.getenv("WC_CONSUMER_KEY") # Обязателен
WC_CONSUMER_SECRET = os.getenv("WC_CONSUMER_SECRET") # Обязателен

# Максимальное количество попыток повторной синхронизации
MAX_RETRIES = 5
# Таймаут для HTTP запросов
HTTP_TIMEOUT = 15.0

# --- Вспомогательные функции ---

def validate_moysklad_response(response_json: dict) -> bool:
    """Проверяет, содержит ли ответ от МойСклад ожидаемые поля id и name."""
    try:
        if not isinstance(response_json, dict):
            return False
        # Проверяем наличие ключевых полей
        return "id" in response_json and "name" in response_json and "meta" in response_json and "href" in response_json["meta"]
    except Exception as e:
        logger.error(f"Error validating Moysklad response: {e}", exc_info=True)
        return False

async def save_to_pending(order_id: int, payload: dict, error: str = ""):
    """Сохраняет заказ в таблицу отложенной синхронизации."""
    try:
        async with get_connection() as conn:
            await conn.execute("""
                INSERT INTO pending_sync (order_id, order_payload, error_message, last_attempt)
                VALUES ($1, $2, $3, now())
                ON CONFLICT (order_id) DO UPDATE SET -- Если заказ уже есть, обновляем ошибку и время
                    order_payload = EXCLUDED.order_payload,
                    error_message = EXCLUDED.error_message,
                    last_attempt = now(),
                    retry_count = pending_sync.retry_count + 1 -- Увеличиваем счетчик при перезаписи ошибки
            """, order_id, json.dumps(payload), error)
        logger.info(f"Order {order_id} saved/updated in pending_sync due to error: {error}")
    except Exception as e:
        logger.exception(f"Failed to save order {order_id} to pending_sync: {e}")


async def update_wc_order_after_ms_sync(order_id: int, moysklad_uuid: str, moysklad_number: str) -> None:
    """Обновляет номер заказа и метаданные в WooCommerce после успешной синхронизации с МойСклад."""
    url = f"{WC_API_URL}/orders/{order_id}"
    auth = (WC_CONSUMER_KEY, WC_CONSUMER_SECRET)
    payload = {
        "number": moysklad_number, # Устанавливаем номер заказа WC равным номеру из МС
        "meta_data": [
            {"key": "_moysklad_uuid", "value": moysklad_uuid},
            {"key": "_moysklad_number", "value": moysklad_number} # Также сохраняем номер МС в метаданные
        ]
    }

    async with httpx.AsyncClient(timeout=HTTP_TIMEOUT) as client:
        response = await client.put(url, json=payload, auth=auth)
        response.raise_for_status() # Вызовет исключение для HTTP ошибок 4xx/5xx
    logger.info(f"WooCommerce order {order_id} updated with Moysklad number {moysklad_number} and UUID {moysklad_uuid}")

# --- Основная логика синхронизации (Асинхронная) ---

async def _process_order(order_id: int, order_payload: dict):
    """Асинхронно обрабатывает один заказ: отправляет в МойСклад и обновляет WooCommerce."""
    if not MOYSKLAD_TOKEN or not WC_API_URL or not WC_CONSUMER_KEY or not WC_CONSUMER_SECRET:
        logger.error("Missing required environment variables (MOYSKLAD_TOKEN, WC_API_URL, WC_CONSUMER_KEY, WC_CONSUMER_SECRET). Skipping order processing.")
        # Возможно, стоит сохранить в pending, но с особой пометкой об ошибке конфигурации
        await save_to_pending(order_id, order_payload, "Configuration Error: Missing API credentials or URLs.")
        return # Прекращаем обработку этого заказа

    headers = {
        "Authorization": f"Bearer {MOYSKLAD_TOKEN}",
        "Content-Type": "application/json",
        "Accept-Encoding": "gzip" # Рекомендуется для МойСклад API
    }
    ms_url = f"{MOYSKLAD_API_URL}/entity/customerorder"

    try:
        async with httpx.AsyncClient(timeout=HTTP_TIMEOUT) as client:
            logger.info(f"Sending order {order_id} to Moysklad...")
            response = await client.post(ms_url, json=order_payload, headers=headers)
            response.raise_for_status() # Проверка на HTTP ошибки

        data = response.json()

        if not validate_moysklad_response(data):
            error_msg = f"Invalid response format from Moysklad for order {order_id}: {data}"
            logger.error(error_msg)
            await save_to_pending(order_id, order_payload, "Invalid API response format")
            return

        moysklad_uuid = data["id"]
        moysklad_number = data["name"]

        # Обновляем заказ в WooCommerce
        await update_wc_order_after_ms_sync(order_id, moysklad_uuid, moysklad_number)

        logger.info(f"Successfully synced order {order_id} with Moysklad (UUID: {moysklad_uuid}, Number: {moysklad_number}) and updated WooCommerce.")

    except httpx.HTTPStatusError as e:
        error_body = e.response.text
        error_msg = f"HTTP error syncing order {order_id} to Moysklad/WooCommerce: {e.request.url} - {e.response.status_code} - Body: {error_body}"
        logger.error(error_msg, exc_info=True)
        await save_to_pending(order_id, order_payload, f"HTTP Error: {e.response.status_code}")
    except httpx.RequestError as e:
        error_msg = f"Network error syncing order {order_id}: {e.request.url} - {e}"
        logger.error(error_msg, exc_info=True)
        await save_to_pending(order_id, order_payload, f"Network Error: {e}")
    except Exception as e:
        logger.exception(f"Generic error syncing order {order_id}: {e}")
        await save_to_pending(order_id, order_payload, f"Unexpected Error: {str(e)}")


async def move_to_dead_letter(conn: asyncpg.Connection, row: asyncpg.Record):
    """Перемещает запись из pending_sync в dead_letter_sync."""
    logger.warning(f"Order {row['order_id']} (pending_id: {row['id']}) reached max retries ({MAX_RETRIES}). Moving to dead letter queue.")
    try:
        await conn.execute("""
            INSERT INTO dead_letter_sync (original_pending_id, order_id, order_payload, final_error_message, failed_at)
            VALUES ($1, $2, $3, $4, now())
        """, row['id'], row['order_id'], row['order_payload'], row['error_message'])

        await conn.execute("DELETE FROM pending_sync WHERE id = $1", row["id"])
        logger.info(f"Order {row['order_id']} moved to dead_letter_sync and removed from pending_sync.")
    except Exception as e:
        logger.exception(f"Failed to move order {row['order_id']} to dead_letter_sync for pending_id {row['id']}: {e}")
        # Важно: если перемещение не удалось, запись остается в pending_sync,
        # но может быть выбрана снова. Рассмотреть добавление флага is_dead или другой механизм.

# --- Задачи Celery ---

@celery_app.task(name="process_order", bind=True, max_retries=3, default_retry_delay=60)
async def process_order_task(self, order_id: int, order_payload: dict):
    """Задача Celery для асинхронной обработки заказа."""
    try:
        await _process_order(order_id, order_payload)
    except Exception as exc:
         # Используем механизм ретраев Celery для временных ошибок
        logger.warning(f"Retrying task for order {order_id} due to exception: {exc}")
        raise self.retry(exc=exc)


@celery_app.task(name="retry_pending_orders")
async def retry_pending_orders_task():
    """Задача Celery для повторной попытки синхронизации отложенных заказов."""
    logger.info("Running retry_pending_orders task")
    processed_ids = set() # Отслеживаем ID, обработанные в этом запуске

    try:
        async with get_connection() as conn: # Используем пул
            retry_rows = await conn.fetch("""
                SELECT id, order_id, order_payload, retry_count
                FROM pending_sync
                WHERE retry_count < $1
                ORDER BY last_attempt ASC -- Обрабатываем сначала старые
                LIMIT 20 -- Обрабатываем пачками
            """, MAX_RETRIES)

            if not retry_rows:
                logger.info("No pending orders to retry.")
            else:
                logger.info(f"Found {len(retry_rows)} pending orders to retry.")

                for row in retry_rows:
                    order_id = row["order_id"]
                    pending_id = row["id"]
                    processed_ids.add(pending_id) # Добавляем ID в обработанные

                    try:
                        order_payload_dict = json.loads(row["order_payload"])
                    except json.JSONDecodeError:
                        logger.error(f"Failed to decode JSON payload for pending sync record id {pending_id}, order_id {order_id}. Moving to dead letter queue.")
                        # Перемещаем некорректный JSON сразу в dead letter
                        await move_to_dead_letter(conn, row)
                        continue

                    try:
                        logger.info(f"Retrying order {order_id} (Attempt: {row['retry_count'] + 1})")
                        await _process_order(order_id, order_payload_dict)
                        # Если успешно, удаляем из очереди
                        await conn.execute("DELETE FROM pending_sync WHERE id = $1", pending_id)
                        logger.info(f"Order {order_id} retried successfully and removed from pending_sync")
                    except Exception as e:
                        # Ошибка при ретрае, _process_order должен был сохранить ошибку в pending_sync.
                        # Обновляем счетчик здесь на всякий случай, если _process_order упал до save_to_pending
                        error_msg = f"Retry attempt failed for order {order_id} (in retry task): {str(e)}"
                        logger.error(error_msg)
                        await conn.execute("""
                            UPDATE pending_sync
                            SET retry_count = retry_count + 1,
                                last_attempt = now(),
                                error_message = $1
                            WHERE id = $2
                        """, error_msg, pending_id)

            # 2. Обрабатываем заказы, достигшие лимита ретраев (уже или после неудачной попытки выше)
            dead_letter_rows = await conn.fetch("""
                SELECT id, order_id, order_payload, retry_count, error_message
                FROM pending_sync
                WHERE retry_count >= $1
                LIMIT 50 -- Обрабатываем пачками
            """, MAX_RETRIES)

            for row in dead_letter_rows:
                if row['id'] not in processed_ids: # Проверяем, не обработали ли уже в этом запуске
                    await move_to_dead_letter(conn, row)

    except Exception as e:
         logger.exception(f"Retry task failed globally: {e}") 
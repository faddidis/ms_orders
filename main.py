import json
import requests
import asyncpg
import os
import logging
from celery import Celery

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

MOYSKLAD_API_URL = "https://online.moysklad.ru/api/remap/1.2"
MOYSKLAD_TOKEN = os.getenv("MOYSKLAD_TOKEN", "your_token")
DATABASE_URL = os.getenv("DATABASE_URL", "postgresql://user:pass@localhost:5432/mydb")

WC_API_URL = os.getenv("WC_API_URL", "http://localhost/wp-json/wc/v3")
WC_CONSUMER_KEY = os.getenv("WC_CONSUMER_KEY", "ck_xxx")
WC_CONSUMER_SECRET = os.getenv("WC_CONSUMER_SECRET", "cs_xxx")

celery_app = Celery("worker", broker=os.getenv("CELERY_BROKER_URL", "redis://redis:6379/0"))

def validate_moysklad_response(response_json: dict) -> bool:
    try:
        if not isinstance(response_json, dict):
            return False
        return "id" in response_json and "meta" in response_json and "href" in response_json["meta"]
    except Exception:
        return False

async def save_to_pending(order_id: int, payload: dict, error: str = ""):
    conn = await asyncpg.connect(DATABASE_URL)
    await conn.execute("""
        INSERT INTO pending_sync (order_id, order_payload, error_message)
        VALUES ($1, $2, $3)
    """, order_id, json.dumps(payload), error)
    await conn.close()
    logger.info(f"Order {order_id} saved to pending_sync due to error")

@celery_app.task(name="process_order")
def process_order(order_id: int, order_payload: dict):
    import asyncio
    asyncio.run(_process_order(order_id, order_payload))

async def _process_order(order_id: int, order_payload: dict):
    try:
        headers = {
            "Authorization": f"Bearer {MOYSKLAD_TOKEN}",
            "Content-Type": "application/json"
        }

        logger.info(f"Sending order {order_id} to Moysklad...")
        response = requests.post(
            f"{MOYSKLAD_API_URL}/entity/customerorder",
            json=order_payload,
            headers=headers,
            timeout=10
        )

        response.raise_for_status()
        data = response.json()

        if not validate_moysklad_response(data):
            logger.error(f"Invalid response from Moysklad for order {order_id}: {data}")
            await save_to_pending(order_id, order_payload, "Invalid API response format")
            return

        # ✅ Получаем UUID и номер из МойСклад
        moysklad_uuid = data.get("id")
        moysklad_number = data.get("name")

        # ✅ Обновляем заказ в WooCommerce
        wc_update_url = f"{WC_API_URL}/orders/{order_id}"
        wc_auth = (WC_CONSUMER_KEY, WC_CONSUMER_SECRET)
        wc_update_payload = {
            "meta_data": [
                {"key": "_moysklad_uuid", "value": moysklad_uuid},
                {"key": "_moysklad_number", "value": moysklad_number}
            ]
        }

        wc_response = requests.put(wc_update_url, auth=wc_auth, json=wc_update_payload)
        wc_response.raise_for_status()

        logger.info(f"Successfully synced order {order_id} with Moysklad and updated WooCommerce metadata")

    except Exception as e:
        logger.exception(f"Failed to sync order {order_id}: {e}")
        await save_to_pending(order_id, order_payload, str(e))

@celery_app.task(name="retry_pending_orders")
def retry_pending_orders():
    import asyncio
    asyncio.run(_retry_pending_orders())

async def _retry_pending_orders():
    logger.info("Running retry_pending_orders task")
    try:
        conn = await asyncpg.connect(DATABASE_URL)
        rows = await conn.fetch("""
            SELECT id, order_id, order_payload, retry_count
            FROM pending_sync
            ORDER BY created_at ASC
            LIMIT 20
        """)

        for row in rows:
            try:
                await _process_order(row["order_id"], row["order_payload"])
                await conn.execute("DELETE FROM pending_sync WHERE id = $1", row["id"])
                logger.info(f"Order {row['order_id']} retried and removed from pending_sync")
            except Exception as e:
                await conn.execute("""
                    UPDATE pending_sync
                    SET retry_count = retry_count + 1,
                        last_attempt = now(),
                        error_message = $1
                    WHERE id = $2
                """, str(e), row["id"])
                logger.error(f"Retry failed for order {row['order_id']}: {e}")

        await conn.close()
    except Exception as e:
        logger.exception(f"Retry task failed: {e}")

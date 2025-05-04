import os
import logging
import requests
from datetime import datetime, timedelta
from celery import Celery

logger = logging.getLogger(__name__)

MOYSKLAD_API_URL = "https://online.moysklad.ru/api/remap/1.2"
MOYSKLAD_TOKEN = os.getenv("MOYSKLAD_TOKEN")
WOOCOMMERCE_API_URL = os.getenv("WOOCOMMERCE_API_URL")
WOOCOMMERCE_USER = os.getenv("WOOCOMMERCE_USER")
WOOCOMMERCE_PASSWORD = os.getenv("WOOCOMMERCE_PASSWORD")

celery_app = Celery("statuses")

@celery_app.task(name="sync_statuses_task")
def sync_statuses_task():
    try:
        orders = get_recent_moysklad_orders()
        for order in orders:
            if "attributes" in order:
                for attr in order["attributes"]:
                    if attr.get("name") == "WooCommerce ID":
                        woo_id = attr.get("value")
                        ms_status = order.get("state", {}).get("name")
                        if woo_id and ms_status:
                            wc_status = map_status(ms_status)
                            update_woocommerce_status(woo_id, wc_status)
    except Exception as e:
        logger.exception(f"Failed to sync statuses: {e}")

def get_recent_moysklad_orders(minutes=10):
    since = (datetime.utcnow() - timedelta(minutes=minutes)).isoformat()
    url = f"{MOYSKLAD_API_URL}/entity/customerorder?updatedFrom={since}"
    headers = {"Authorization": f"Bearer {MOYSKLAD_TOKEN}"}
    response = requests.get(url, headers=headers, timeout=10)
    response.raise_for_status()
    return response.json().get("rows", [])

def map_status(ms_status):
    mapping = {
        "Новый": "pending",
        "Подтверждён": "processing",
        "Отгружен": "completed",
        "Отменён": "cancelled"
    }
    return mapping.get(ms_status, "on-hold")

def update_woocommerce_status(order_id, new_status):
    url = f"{WOOCOMMERCE_API_URL}/wp-json/wc/v3/orders/{order_id}"
    auth = (WOOCOMMERCE_USER, WOOCOMMERCE_PASSWORD)
    response = requests.put(url, json={"status": new_status}, auth=auth, timeout=10)
    if response.status_code != 200:
        logger.error(f"Failed to update status for WooCommerce order {order_id}: {response.text}")
        return False
    logger.info(f"Updated WooCommerce order {order_id} to status '{new_status}'")
    return True

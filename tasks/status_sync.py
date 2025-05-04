# tasks/status_sync.py

import asyncpg
import os
import logging
from db import get_connection
from utils.woocommerce import update_wc_order_status, get_wc_orders_for_status_sync
from utils.moysklad import fetch_moysklad_orders, update_moysklad_order_status

logger = logging.getLogger(__name__)

async def get_status_mapping():
    conn = await get_connection()
    rows = await conn.fetch("SELECT moysklad_status, woocommerce_status FROM status_mapping")
    await conn.close()
    return {
        "ms_to_wc": {row["moysklad_status"]: row["woocommerce_status"] for row in rows},
        "wc_to_ms": {row["woocommerce_status"]: row["moysklad_status"] for row in rows}
    }

async def sync_statuses_from_moysklad():
    mapping = await get_status_mapping()
    ms_to_wc = mapping["ms_to_wc"]

    orders = await fetch_moysklad_orders()

    for order in orders:
        wc_order_id = order.get("externalCode")
        ms_status_name = order.get("state", {}).get("name")

        if wc_order_id and ms_status_name in ms_to_wc:
            new_status = ms_to_wc[ms_status_name]
            logger.info(f"Updating WC order {wc_order_id} to status {new_status} from MS status {ms_status_name}")
            await update_wc_order_status(wc_order_id, new_status)

async def sync_statuses_to_moysklad():
    mapping = await get_status_mapping()
    wc_to_ms = mapping["wc_to_ms"]

    orders = await get_wc_orders_for_status_sync()

    for order in orders:
        wc_id = order["id"]
        ms_uuid = order.get("meta", {}).get("moysklad_uuid")
        wc_status = order["status"]

        if ms_uuid and wc_status in wc_to_ms:
            ms_status = wc_to_ms[wc_status]
            logger.info(f"Updating MS order {ms_uuid} to status {ms_status} from WC order {wc_id}")
            await update_moysklad_order_status(ms_uuid, ms_status)

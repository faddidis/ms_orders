# Файл db.py добавлен: он содержит подключение к PostgreSQL и инициализацию таблицы pending_sync.
# Содержимое db.py

import asyncpg
import os

DATABASE_URL = os.getenv("DATABASE_URL")

async def get_connection():
    return await asyncpg.connect(DATABASE_URL)

async def init_db():
    conn = await get_connection()
    await conn.execute("""
        CREATE TABLE IF NOT EXISTS pending_sync (
            id SERIAL PRIMARY KEY,
            order_id INTEGER NOT NULL,
            order_payload JSONB NOT NULL,
            retry_count INTEGER DEFAULT 0,
            last_attempt TIMESTAMP DEFAULT now(),
            error_message TEXT,
            created_at TIMESTAMP DEFAULT now()
        )
    """)
    await conn.close()

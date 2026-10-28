"""Finboard v2 settings, read from environment variables (relaxdev panel or local .env)."""

import os
from dotenv import load_dotenv

load_dotenv()

# Empty DATABASE_URL = local SQLite file (development only).
DATABASE_URL = os.getenv("DATABASE_URL", "").strip()
SQLITE_URL = "sqlite:///finboard.db"

# Master key for encrypting marketplace API keys stored in the database.
APP_SECRET = os.getenv("APP_SECRET", "")

# Owner login. Empty = no password (only for local runs).
OWNER_PASSWORD = os.getenv("OWNER_PASSWORD", "")

TIMEZONE = os.getenv("SCHEDULER_TIMEZONE", "Europe/Moscow")
SYNC_HOUR = int(os.getenv("SYNC_HOUR", "6"))

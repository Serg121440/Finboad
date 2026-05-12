import os
from dotenv import load_dotenv

load_dotenv()

GOOGLE_SHEETS_CREDENTIALS_JSON = os.getenv("GOOGLE_SHEETS_CREDENTIALS_JSON", "credentials.json")
GOOGLE_SPREADSHEET_ID = os.getenv("GOOGLE_SPREADSHEET_ID", "1tBId8FD7JaYUrxIBzffxHXQJUtl97reN")

WB_API_TOKEN = os.getenv("WB_API_TOKEN", "")
WB_BASE_URL = "https://statistics-api.wildberries.ru"

OZON_CLIENT_ID = os.getenv("OZON_CLIENT_ID", "")
OZON_API_KEY = os.getenv("OZON_API_KEY", "")
OZON_BASE_URL = "https://api-seller.ozon.ru"

DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///finboard.db")

SCHEDULER_TIMEZONE = os.getenv("SCHEDULER_TIMEZONE", "Europe/Moscow")
SCHEDULER_HOUR = 6
SCHEDULER_MINUTE = 0

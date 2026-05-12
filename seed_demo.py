"""Seed demo data for testing the dashboard without real API keys."""

import sys
import os

sys.path.insert(0, os.path.dirname(__file__))

import random
from datetime import date, timedelta
from database.db import init_db, upsert_records

random.seed(42)

PRODUCTS = [
    ("SKU-001", "Футболка базовая белая", "Одежда"),
    ("SKU-002", "Футболка базовая чёрная", "Одежда"),
    ("SKU-003", "Джинсы slim fit", "Одежда"),
    ("SKU-004", "Кроссовки беговые", "Обувь"),
    ("SKU-005", "Рюкзак городской 20л", "Аксессуары"),
    ("SKU-006", "Толстовка с капюшоном", "Одежда"),
    ("SKU-007", "Носки спортивные (5 пар)", "Одежда"),
    ("SKU-008", "Сумка через плечо", "Аксессуары"),
    ("SKU-009", "Кепка летняя", "Аксессуары"),
    ("SKU-010", "Шорты пляжные", "Одежда"),
]

MARKETPLACES = ["wb", "ozon"]

records = []
today = date.today()

for days_ago in range(60):
    day = today - timedelta(days=days_ago)
    for mp in MARKETPLACES:
        for sku, name, category in PRODUCTS:
            if random.random() < 0.7:
                qty = random.randint(1, 30)
                price = random.uniform(500, 5000)
                rev = qty * price
                return_qty = random.randint(0, max(1, qty // 5))
                ret = return_qty * price
                commission_rate = 0.15 if mp == "wb" else 0.12
                logistics_rate = 0.07 if mp == "wb" else 0.05
                commission = rev * commission_rate
                logistics = qty * random.uniform(50, 150)
                net = rev - ret - commission - logistics

                records.append({
                    "marketplace": mp,
                    "date": day,
                    "sku": sku,
                    "product_name": name,
                    "category": category,
                    "revenue": round(rev, 2),
                    "returns": round(ret, 2),
                    "commission": round(commission, 2),
                    "logistics": round(logistics, 2),
                    "net_profit": round(net, 2),
                    "quantity": qty,
                    "return_quantity": return_qty,
                    "source": "demo",
                })

init_db()
n = upsert_records(records)
print(f"Загружено {len(records)} демо-записей ({n} новых) за 60 дней")
print("Запусти дашборд: streamlit run dashboard/app.py")

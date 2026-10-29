"""Wildberries realization report rows -> ledger rows.

Accepts rows from the statistics API `reportDetailByPeriod` (snake_case), the
cabinet JSON (camelCase) or the weekly detail xlsx (Russian column names); all
are first mapped to one canonical set of fields.

Seller revenue = «Цена розничная с учетом согласованной скидки» × quantity, i.e.
the seller's price before WB's own discount (СПП is paid by WB and comes back in
«К перечислению»). So commission = signed «К перечислению» − seller revenue.
"""

from datetime import date, datetime

# canonical field -> aliases (API snake_case, cabinet camelCase, xlsx header)
FIELDS = {
    "report_id": ("realizationreport_id", "reportId", "Номер отчёта"),
    "rrd_id": ("rrd_id", "rrdId", "№"),
    "doc_type": ("doc_type_name", "docTypeName", "Тип документа"),
    "oper": ("supplier_oper_name", "sellerOperName", "Обоснование для оплаты"),
    "bonus_type": ("bonus_type_name", "bonusTypeName", "Виды доставок, штрафов и корректировок ВВ",
                   "Виды логистики, штрафов и корректировок ВВ"),
    "nm_id": ("nm_id", "nmId", "Код номенклатуры"),
    "article": ("sa_name", "vendorCode", "Артикул поставщика"),
    "subject": ("subject_name", "subjectName", "Предмет"),
    "title": ("title", "Название"),
    "qty": ("quantity", "Кол-во"),
    "price_with_disc": ("retail_price_withdisc_rub", "retailPriceWithDisc",
                        "Цена розничная с учетом согласованной скидки"),
    "for_pay": ("ppvz_for_pay", "forPay", "К перечислению Продавцу за реализованный Товар"),
    "acquiring": ("acquiring_fee", "acquiringFee", "Эквайринг/Комиссии за организацию платежей"),
    "delivery": ("delivery_rub", "deliveryService", "Услуги по доставке товара покупателю"),
    "penalty": ("penalty", "Общая сумма штрафов"),
    "storage": ("storage_fee", "paidStorage", "Хранение"),
    "acceptance": ("acceptance", "paidAcceptance", "Платная приемка", "Услуга по обработке Товара"),
    "deduction": ("deduction", "Удержания"),
    "rebill_logistics": ("rebill_logistic_cost", "rebillLogisticCost",
                         "Возмещение издержек по перемещению и операционной обработке товара"),
    "additional_payment": ("additional_payment", "additionalPayment", "Доплаты"),
    "loyalty_comp": ("cashback_discount", "cashbackDiscount", "Компенсация скидки по программе лояльности"),
    "loyalty_cost": ("cashback_amount", "cashbackAmount", "Стоимость участия в программе лояльности"),
    "loyalty_points": ("cashback_commission_change", "cashbackCommissionChange",
                       "Сумма баллов, удержанных по программе лояльности"),
    "rr_date": ("rr_dt", "rrDate", "Дата продажи"),
    "order_date": ("order_dt", "orderDt", "Дата заказа покупателем"),
    "srid": ("srid", "Srid"),
}

SALE_OPERS = {"Продажа", "Корректная продажа", "Коррекция продаж", "Сторно возвратов"}
RETURN_OPERS = {"Возврат", "Корректный возврат", "Коррекция возвратов", "Сторно продаж"}


def canonical(row: dict) -> dict:
    out = {}
    for key, aliases in FIELDS.items():
        v = None
        for a in aliases:
            if a in row and row[a] is not None and str(row[a]) != "nan":
                v = row[a]
                break
        out[key] = v
    return out


def _f(v) -> float:
    if v in (None, ""):
        return 0.0
    try:
        return float(str(v).replace(",", ".").replace("\xa0", "").replace(" ", ""))
    except ValueError:
        return 0.0


def _day(v) -> date | None:
    if v in (None, ""):
        return None
    if isinstance(v, datetime):
        return v.date()
    if isinstance(v, date):
        return v
    return date.fromisoformat(str(v)[:10])


def normalize_article(v) -> str:
    """«сг000006534» -> «СГ000006534», «00000002479» -> «2479»."""
    s = str(v or "").strip().upper()
    return str(int(s)) if s.isdigit() else s


def _deduction_category(bonus_type: str) -> str:
    b = (bonus_type or "").lower()
    if "продвижен" in b or "реклам" in b:
        return "ads_wb_deduction"     # paid ads: counted from the ad cabinet instead
    if "джем" in b or "подписк" in b or "аналитик" in b:
        return "subscriptions"
    return "penalties"


def rows_to_ledger(rows: list[dict], key_prefix: str = "") -> list[dict]:
    out = []
    for i, raw in enumerate(rows):
        r = canonical(raw)
        d = _day(r["rr_date"])
        if d is None:
            continue
        sku = str(int(_f(r["nm_id"]))) if _f(r["nm_id"]) else None
        oper = str(r["oper"] or "").strip()
        doc = str(r["doc_type"] or "").strip()
        bonus = str(r["bonus_type"] or "")
        base = f"{key_prefix}{r['report_id'] or ''}:{r['rrd_id'] or i}"
        n = 0

        def add(category, amount, qty=0):
            nonlocal n
            amount = round(amount, 2)
            if not amount and not qty:
                return
            out.append({"date": d, "sku": sku, "category": category, "amount": amount,
                        "qty": qty, "posting": str(r["srid"] or ""), "raw_type": oper or bonus,
                        "source_key": f"{base}:{n}"})
            n += 1

        qty = int(_f(r["qty"]))
        price = _f(r["price_with_disc"])
        for_pay = _f(r["for_pay"])
        if oper in SALE_OPERS or oper in RETURN_OPERS:
            sg = 1 if oper in SALE_OPERS else -1
            revenue = sg * price * qty
            add("sale" if sg > 0 else "return", revenue, sg * qty)
            # «К перечислению» is net of both: split acquiring out of the commission
            acquiring = sg * _f(r["acquiring"])
            add("commission", sg * for_pay - revenue + acquiring)
            add("acquiring", -acquiring)
        elif for_pay:
            sg = -1 if doc == "Возврат" else 1
            low = oper.lower()
            if "лояльност" in low or "баллов" in low:
                add("loyalty", sg * for_pay)
            elif "эквайринг" in low:
                add("acquiring", sg * for_pay)
            else:
                add("compensation", sg * for_pay)

        delivery = _f(r["delivery"])
        if delivery:
            b = bonus.lower().strip()
            back = b.startswith("от клиента") or ("возврат" in b and not b.startswith("к клиенту"))
            add("logistics_return" if back else "logistics", -delivery)
        add("logistics", -_f(r["rebill_logistics"]))
        add("penalties", -_f(r["penalty"]))
        add("storage", -_f(r["storage"]))
        add("fbo_services", -_f(r["acceptance"]))
        if _f(r["deduction"]):
            add(_deduction_category(bonus), -_f(r["deduction"]))
        add("compensation", _f(r["additional_payment"]))
        add("loyalty", _f(r["loyalty_comp"]) - _f(r["loyalty_cost"]))
    return out


def products_from_rows(rows: list[dict]) -> dict[str, dict]:
    out = {}
    for raw in rows:
        r = canonical(raw)
        if not _f(r["nm_id"]):
            continue
        sku = str(int(_f(r["nm_id"])))
        out.setdefault(sku, {"sku": sku, "offer_id": normalize_article(r["article"]),
                             "name": str(r["title"] or ""), "category": str(r["subject"] or "")})
    return out


def read_report(path_or_buffer) -> list[dict]:
    import pandas as pd
    df = pd.read_excel(path_or_buffer)
    return df.to_dict("records")

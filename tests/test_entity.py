"""Legal entity from Ozon seller info."""

import threading

from sqlalchemy import delete, select

from core.db import init_db, session
from core.models import Cabinet, LegalEntity
from sync import runner


class FakeSeller:
    def __init__(self, inn="7700000001"):
        self.inn = inn

    def seller_info(self):
        return {"legal_name": "ООО \"ТЕСТ\"", "ownership_form": "ООО", "inn": self.inn, "tax_system": "OSNO"}


def _cabinets(n):
    init_db()
    with session() as s:
        s.execute(delete(Cabinet).where(Cabinet.name.like("ent-test-%")))
        s.execute(delete(LegalEntity).where(LegalEntity.inn.in_(["7700000001", "7700000002"])))
        cabs = [Cabinet(marketplace="ozon", name=f"ent-test-{i}", secrets="") for i in range(n)]
        s.add_all(cabs)
        s.flush()
        return [c.id for c in cabs]


def test_cabinets_of_one_company_share_one_entity():
    ids = _cabinets(4)
    threads = [threading.Thread(target=runner.ensure_entity, args=(i, FakeSeller())) for i in ids]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    with session() as s:
        ents = s.scalars(select(LegalEntity).where(LegalEntity.inn == "7700000001")).all()
        links = {s.get(Cabinet, i).entity_id for i in ids}
    assert len(ents) == 1 and links == {ents[0].id}
    assert ents[0].kind == "ooo" and ents[0].mp_tax_system == "OSNO"


def test_relink_only_when_asked():
    (cid,) = _cabinets(1)
    first = runner.ensure_entity(cid, FakeSeller("7700000001"))
    assert runner.ensure_entity(cid, FakeSeller("7700000002")) == first
    second = runner.ensure_entity(cid, FakeSeller("7700000002"), relink=True)
    assert second != first


def test_link_made_during_lookup_is_kept():
    (cid,) = _cabinets(1)

    class SlowSeller(FakeSeller):
        def seller_info(self):
            with session() as s:  # the user assigns an entity meanwhile
                e = LegalEntity(name="выбрано вручную", kind="ip", inn="7700000002")
                s.add(e)
                s.flush()
                s.get(Cabinet, cid).entity_id = self.picked = e.id
            return super().seller_info()

    seller = SlowSeller()
    assert runner.ensure_entity(cid, seller) == seller.picked

import json

import httpx
import pytest

from app.ingest import natlot, sync
from app.ingest.natlot import InvalidDraw, parse_draw
from conftest import load_into, make_raw, synthetic_draws

T = 1_700_000_000_000


def test_parse_valid_lotto(lotto):
    d = parse_draw(make_raw(lotto, 1, T, [31, 5, 6, 8, 9, 16], bonus=20, tiers={"6": 0, "5+1": 3}), lotto)
    assert d["numbers"] == [5, 6, 8, 9, 16, 31]
    assert d["bonus"] == 20
    assert {t["tier"] for t in d["tiers"]} == {"6", "5+1"}


def test_parse_handles_padded_drawtype(euromillions):
    raw = make_raw(euromillions, 1, T, [1, 2, 3, 4, 5], extras=[1, 2], tiers={"2+0": 10}, pad_drawtype=True)
    assert parse_draw(raw, euromillions)["tiers"][0]["tier"] == "2+0"


@pytest.mark.parametrize("nums,bonus,msg", [
    ([1, 2, 3, 4, 5], 9, "6"),            # wrong count
    ([1, 1, 3, 4, 5, 6], 9, "doublon"),   # duplicate
    ([1, 2, 3, 4, 5, 46], 9, "hors"),     # out of range
    ([1, 2, 3, 4, 5, 6], 6, "bonus"),     # bonus among main numbers
])
def test_parse_rejects_invalid(lotto, nums, bonus, msg):
    with pytest.raises(InvalidDraw, match=msg):
        parse_draw(make_raw(lotto, 1, T, nums, bonus=bonus), lotto)


def test_parse_rejects_non_final_and_rule_change(lotto):
    raw = make_raw(lotto, 1, T, [1, 2, 3, 4, 5, 6], bonus=7)
    raw["status"] = "OPEN"
    with pytest.raises(InvalidDraw):
        parse_draw(raw, lotto)
    raw = make_raw(lotto, 1, T, [1, 2, 3, 4, 5, 6], bonus=7)
    raw["gameRuleSet"]["primarySelectionsHighNumber"] = 49
    with pytest.raises(InvalidDraw, match="règle"):
        parse_draw(raw, lotto)


def test_no_duplicates(db, lotto):
    raws = synthetic_draws(lotto, 5)
    load_into(db, lotto, raws)
    load_into(db, lotto, raws)
    assert db.count_draws(lotto.key) == 5


def _client(handler):
    return httpx.Client(transport=httpx.MockTransport(handler))


def test_sync_incremental_and_logged(db, lotto, monkeypatch):
    raws = synthetic_draws(lotto, 8)
    calls = []

    def handler(request: httpx.Request):
        calls.append(request.url)
        assert request.url.host == "apim.prd.natlot.be"
        return httpx.Response(200, json={"draws": raws})

    monkeypatch.setattr(sync, "maybe_verify_xlsx", lambda *a, **k: None)
    r1 = sync.sync_game(db, lotto, "scheduler", client=_client(handler))
    r2 = sync.sync_game(db, lotto, "scheduler", client=_client(handler))
    assert r1["new_draws"] == 8 and r2["new_draws"] == 0
    assert db.count_draws(lotto.key) == 8
    assert db.last_sync(lotto.key)["status"] == "ok"


def test_sync_source_down_is_reported(db, lotto, monkeypatch):
    def handler(request):
        return httpx.Response(503)

    r = sync.sync_game(db, lotto, "scheduler", client=_client(handler))
    assert r["status"] == "error" and "503" in r["message"]
    assert db.last_sync(lotto.key)["status"] == "error"
    assert db.count_draws(lotto.key) == 0


def test_manual_sync_is_throttled(db, lotto, monkeypatch):
    monkeypatch.setattr(sync, "maybe_verify_xlsx", lambda *a, **k: None)
    sync._last_manual.clear()
    handler = lambda request: httpx.Response(200, json={"draws": []})  # noqa: E731
    sync.sync_game(db, lotto, "manual", client=_client(handler))
    with pytest.raises(sync.SyncThrottled):
        sync.sync_game(db, lotto, "manual", client=_client(handler))


def test_repair_tiers_from_raw(db, euromillions):
    raw = make_raw(euromillions, 1, T, [1, 2, 3, 4, 5], extras=[1, 2], tiers={"2+0": 10})
    d = parse_draw(raw, euromillions)
    d["tiers"] = []  # simulate an older parser that missed the tiers
    db.insert_draw(d)
    assert sync.repair_tiers_from_raw(db, euromillions) == 1
    assert db.tiers_for_game(euromillions.key)[0]["winners"] == 10


def test_xlsx_link_discovery():
    from app.ingest import xlsx_verify

    html = 'x href="/content/dam/opp/draw-games/lotto/brand-assets/documents/fr/statistiques-lotto-10-26.xlsx" y'
    assert xlsx_verify.find_xlsx_url(html).endswith("statistiques-lotto-10-26.xlsx")
    assert xlsx_verify.find_xlsx_url(html).startswith("https://www.loterie-nationale.be/")
    with pytest.raises(natlot.SourceError):
        xlsx_verify.find_xlsx_url('href="https://evil.example/statistiques-lotto-1.xlsx"')


def test_raw_is_kept_for_audit(db, lotto):
    raws = synthetic_draws(lotto, 1)
    load_into(db, lotto, raws)
    stored = db.query("SELECT raw FROM draws")[0]["raw"]
    assert json.loads(stored)["id"] == raws[0]["id"]

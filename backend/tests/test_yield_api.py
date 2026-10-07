"""出成率验收：定义仓/当前单/历史单分套落库，保存要么整张重写要么整张退回。"""
import json
import threading

from sqlalchemy import select

from app.database import SessionLocal
from app.models.models import PrepRun


def _bom_rows(client):
    return client.get("/api/bom").json()


def _line_id(client, ingredient_name):
    return next(r for r in _bom_rows(client) if r["ingredient_name"] == ingredient_name)["id"]


def _dish_id(client):
    return next(r for r in client.get("/api/dishes").json() if r["code"] == "D-HS")["id"]


def _needs(client):
    data = client.get("/api/prep/latest?order_id=1").json()
    return {l["ingredient_name"]: l["need_qty"] for l in data["prep_lines"]}


def _save(client, lines=None, dishes=None):
    return client.put("/api/bom/yield-rates",
                      json={"lines": lines or [], "dishes": dishes or []})


# 基线（出成率从未写过 = 1）：五花肉10 茄子9 鸡肉6 大米10.5 面条10 生抽1.75 食用油1.95
BASE_NEEDS = {"五花肉": 10.0, "茄子": 9.0, "鸡肉": 6.0, "大米": 10.5,
              "面条": 10.0, "生抽": 1.75, "食用油": 1.95}


def test_latest_404_before_any_run_no_fabrication(client):
    """禁止打开备料台按定义现算冒充已落单。"""
    res = client.get("/api/prep/latest?order_id=1")
    assert res.status_code == 404
    res = client.get("/api/prep/shortages?order_id=1")
    assert res.status_code == 200
    body = res.json()
    assert body["has_run"] is False and body["shortages"] == []


def test_run_persists_and_latest_reads_back(client):
    run = client.post("/api/prep/run?order_id=1").json()
    latest = client.get("/api/prep/latest?order_id=1").json()
    assert latest["id"] == run["id"]
    assert _needs(client) == BASE_NEEDS


def test_save_yield_rate_rewrites_whole_current_sheet(client):
    """出成率改小 → 当前单需求变大；整张重写，其余行保持一层展开口径。"""
    client.post("/api/prep/run?order_id=1")
    res = _save(client, lines=[{"id": _line_id(client, "五花肉"), "yield_rate": 0.5}])
    assert res.status_code == 200, res.text
    assert res.json()["rewritten"], "当前有效单必须跟着定义仓整张重写"
    needs = _needs(client)
    assert needs["五花肉"] == 20.0  # 10 / 0.5
    for name, qty in BASE_NEEDS.items():
        if name != "五花肉":
            assert needs[name] == qty
    shortages = client.get("/api/prep/shortages?order_id=1").json()
    pr = next(s for s in shortages["shortages"] if s["ingredient_name"] == "五花肉")
    assert pr["shortage"] == 12.0  # 缺料贴跟着新率重写


def test_yield_rate_one_or_unset_matches_plain_explode(client):
    client.post("/api/prep/run?order_id=1")
    res = _save(client, lines=[{"id": _line_id(client, "五花肉"), "yield_rate": 1.0}])
    assert res.status_code == 200
    assert _needs(client) == BASE_NEEDS
    # 清空回「从未写过」也与一层展开一致
    res = _save(client, lines=[{"id": _line_id(client, "五花肉"), "yield_rate": None}])
    assert res.status_code == 200
    assert _needs(client) == BASE_NEEDS


def test_dish_yield_rate_also_writable(client):
    """出品（菜品）也能写出成率，与用料率连乘。"""
    client.post("/api/prep/run?order_id=1")
    res = _save(client, dishes=[{"id": _dish_id(client), "yield_rate": 0.5}])
    assert res.status_code == 200, res.text
    needs = _needs(client)
    assert needs["五花肉"] == 20.0   # 红烧肉套餐整品减半率
    assert needs["大米"] == 16.5     # 12(HS/0.5) + 4.5(YC)
    assert needs["生抽"] == 2.55     # 1.6 + 0.45 + 0.5
    assert needs["食用油"] == 3.15   # 2.4 + 0.75
    assert needs["茄子"] == 9.0      # 别的菜不动


def test_invalid_yield_rate_rolls_back_everything(client):
    """0 或大于 1：定义、当前单、缺料贴全部退回保存前；失败说明不提结存。"""
    client.post("/api/prep/run?order_id=1")
    bom_before = _bom_rows(client)
    latest_before = client.get("/api/prep/latest?order_id=1").json()
    shortages_before = client.get("/api/prep/shortages?order_id=1").json()

    for bad in (0, 1.5, -0.2):
        res = _save(client, lines=[{"id": _line_id(client, "五花肉"), "yield_rate": bad}])
        assert res.status_code == 400
        detail = res.json()["detail"]
        assert "出成率" in detail
        assert "结存" not in detail and "库存不足" not in detail
    res = _save(client, dishes=[{"id": _dish_id(client), "yield_rate": 0}])
    assert res.status_code == 400

    assert _bom_rows(client) == bom_before                       # 定义仓退回
    assert client.get("/api/prep/latest?order_id=1").json() == latest_before   # 当前单退回
    assert client.get("/api/prep/shortages?order_id=1").json() == shortages_before  # 缺料贴退回


def test_save_does_not_touch_inventory(client):
    """库存页结存保存前后必须同一个数，禁止把保存做成领料。"""
    client.post("/api/prep/run?order_id=1")
    before = client.get("/api/inventory").json()
    _save(client, lines=[{"id": _line_id(client, "五花肉"), "yield_rate": 0.5}])
    _save(client, dishes=[{"id": _dish_id(client), "yield_rate": 0.8}])
    assert client.get("/api/inventory").json() == before


def test_archived_runs_untouched_current_rewritten(client):
    """已钉死历史单禁止跟着保存改字；当前有效单整张重写。"""
    client.post("/api/prep/run?order_id=1")
    client.post("/api/prep/run?order_id=1")
    db = SessionLocal()
    try:
        archived = db.scalars(select(PrepRun).where(PrepRun.status == "archived")).all()
        assert len(archived) == 1
        archived_json_before = archived[0].result_json
        current_before = db.scalars(select(PrepRun).where(PrepRun.status == "current")).one()
        current_id, current_json_before = current_before.id, current_before.result_json
    finally:
        db.close()

    _save(client, lines=[{"id": _line_id(client, "五花肉"), "yield_rate": 0.5}])

    db = SessionLocal()
    try:
        archived_after = db.scalars(select(PrepRun).where(PrepRun.status == "archived")).all()
        assert len(archived_after) == 1
        assert archived_after[0].result_json == archived_json_before  # 历史单一个字不改
        current_after = db.scalars(select(PrepRun).where(PrepRun.status == "current")).one()
        assert current_after.id == current_id                          # 当前单原地整张重写
        assert current_after.result_json != current_json_before
        assert json.loads(current_after.result_json)["prep_lines"]
    finally:
        db.close()
    assert _needs(client)["五花肉"] == 20.0


def test_unknown_line_or_dish_rejected_without_side_effects(client):
    client.post("/api/prep/run?order_id=1")
    before = client.get("/api/prep/latest?order_id=1").json()
    assert _save(client, lines=[{"id": 99999, "yield_rate": 0.5}]).status_code == 404
    assert _save(client, dishes=[{"id": 99999, "yield_rate": 0.5}]).status_code == 404
    assert client.get("/api/prep/latest?order_id=1").json() == before
    assert all(r["yield_rate"] is None for r in _bom_rows(client))


def test_save_and_run_race_single_consistent_outcome(client):
    """定额保存与「生成备料单」抢同一瞬间：最终当前单必须与已落库定义同一套。"""
    client.post("/api/prep/run?order_id=1")
    pr_line = _line_id(client, "五花肉")
    errors = []

    def do_save():
        try:
            r = _save(client, lines=[{"id": pr_line, "yield_rate": 0.5}])
            assert r.status_code == 200, r.text
        except Exception as e:  # noqa: BLE001
            errors.append(e)

    def do_run():
        try:
            r = client.post("/api/prep/run?order_id=1")
            assert r.status_code == 200, r.text
        except Exception as e:  # noqa: BLE001
            errors.append(e)

    threads = [threading.Thread(target=do_save), threading.Thread(target=do_run)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert not errors
    # 无论谁先谁后，最终当前有效单必须整张跟着定义仓（五花肉新率 0.5 → 20）
    needs = _needs(client)
    assert needs["五花肉"] == 20.0
    for name, qty in BASE_NEEDS.items():
        if name != "五花肉":
            assert needs[name] == qty

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session
from app.database import get_db
from app.models.models import BomLine, Dish, Ingredient, KitchenOrder
from app.services.prep_service import prep_sheet_mutex, rewrite_current_run

router = APIRouter(prefix="/bom", tags=["bom"])

# 出成率校验失败说明：只讲出成率本身，禁止写成结存不够
YIELD_RATE_ERROR = "出成率必须在 0 到 1 之间（不含 0），留空表示未设置"


class YieldLineIn(BaseModel):
    id: int
    yield_rate: float | None = None


class YieldDishIn(BaseModel):
    id: int
    yield_rate: float | None = None


class YieldSaveIn(BaseModel):
    lines: list[YieldLineIn] = []
    dishes: list[YieldDishIn] = []


def _valid_rate(y: float | None) -> bool:
    return y is None or (0 < y <= 1)


@router.get("")
def list_bom(db: Session = Depends(get_db)):
    dishes = {d.id: d for d in db.scalars(select(Dish)).all()}
    ings = {i.id: i for i in db.scalars(select(Ingredient)).all()}
    rows = db.scalars(select(BomLine).order_by(BomLine.dish_id, BomLine.id)).all()
    return [{"id": r.id, "dish_id": r.dish_id, "dish_name": dishes[r.dish_id].name,
             "dish_code": dishes[r.dish_id].code, "dish_yield_rate": dishes[r.dish_id].yield_rate,
             "ingredient_id": r.ingredient_id, "ingredient_name": ings[r.ingredient_id].name,
             "qty_per_portion": r.qty_per_portion, "yield_rate": r.yield_rate,
             "unit": ings[r.ingredient_id].unit} for r in rows]


@router.get("/tree")
def bom_tree(db: Session = Depends(get_db)):
    dishes = db.scalars(select(Dish).order_by(Dish.id)).all()
    ings = {i.id: i for i in db.scalars(select(Ingredient)).all()}
    lines = db.scalars(select(BomLine)).all()
    tree = []
    for d in dishes:
        children = [{"ingredient": ings[l.ingredient_id].name, "qty": l.qty_per_portion,
                     "unit": ings[l.ingredient_id].unit, "yield_rate": l.yield_rate}
                    for l in lines if l.dish_id == d.id]
        tree.append({"dish": d.name, "code": d.code, "yield_rate": d.yield_rate, "children": children})
    return tree


@router.put("/yield-rates")
def save_yield_rates(payload: YieldSaveIn, db: Session = Depends(get_db)):
    """定额页保存出成率：定义仓与当前有效单同一事务，要么整张重写，要么整张退回。

    - 任一出成率为 0 或大于 1 → 定义、当前单、缺料贴全部退回保存前；
    - 库存结存一个字不动（保存不是领料）；
    - 已钉死历史单不跟着改字。
    """
    for item in [*payload.lines, *payload.dishes]:
        if not _valid_rate(item.yield_rate):
            raise HTTPException(400, YIELD_RATE_ERROR)

    line_rows = {i.id: db.get(BomLine, i.id) for i in payload.lines}
    dish_rows = {i.id: db.get(Dish, i.id) for i in payload.dishes}
    for iid, row in line_rows.items():
        if row is None:
            raise HTTPException(404, f"BOM行 {iid} 不存在")
    for iid, row in dish_rows.items():
        if row is None:
            raise HTTPException(404, f"菜品 {iid} 不存在")

    open_orders = db.scalars(
        select(KitchenOrder).where(KitchenOrder.status == "open").order_by(KitchenOrder.id)
    ).all()

    rewritten = []
    with prep_sheet_mutex(db, [o.id for o in open_orders]):
        for item in payload.lines:
            line_rows[item.id].yield_rate = item.yield_rate
        for item in payload.dishes:
            dish_rows[item.id].yield_rate = item.yield_rate
        db.flush()
        for order in open_orders:
            run = rewrite_current_run(db, order.id)
            if run is not None:
                rewritten.append({"order_id": order.id, "run_id": run.id})
        db.commit()
    return {"ok": True, "rewritten": rewritten}

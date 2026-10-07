"""备料单落库语义：当前有效单（current）与已钉死历史单（archived）分套存放。

- 生成备料单：旧当前单钉死为 archived，新单按定义仓当前出成率整张落库。
- 定额页保存出成率：当前有效单按定义仓整张重写（占用列 + 缺料贴），历史单不动。
- 读取备料台只读落库结果，禁止按定义现算冒充已落单。
- 定额保存与生成备料单抢同一瞬间：prep_sheet_mutex 串行化，只许同一套成败。
"""
from __future__ import annotations

import json
import threading
from contextlib import contextmanager

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.models import BomLine, Dish, Ingredient, KitchenOrder, OrderLine, PrepRun
from app.services.bom_engine import explode_and_merge, result_to_dict

# 无行锁方言（SQLite 等）下的进程内互斥；PostgreSQL 走行锁，见 lock_orders
_order_locks: dict[int, threading.Lock] = {}
_order_locks_guard = threading.Lock()


def lock_orders(db: Session, order_ids: list[int]) -> None:
    """PostgreSQL：对订单行 SELECT ... FOR UPDATE，锁持有到事务结束。"""
    if not order_ids:
        return
    if db.get_bind().dialect.name == "postgresql":
        db.execute(
            select(KitchenOrder.id)
            .where(KitchenOrder.id.in_(sorted(order_ids)))
            .with_for_update()
        )


@contextmanager
def prep_sheet_mutex(db: Session, order_ids: list[int]):
    """把「读定义 → 算 → 写当前单 → 提交」包成互斥区，保证保存与生成不交叉。"""
    ids = sorted(set(order_ids))
    if db.get_bind().dialect.name == "postgresql":
        lock_orders(db, ids)
        yield
        return
    with _order_locks_guard:
        locks = [_order_locks.setdefault(i, threading.Lock()) for i in ids]
    for lock in locks:
        lock.acquire()
    try:
        yield
    finally:
        for lock in locks:
            lock.release()


def compute_order_result(db: Session, order_id: int) -> dict:
    """按定义仓当前出成率整张展开一张备料单（不落库，落库由调用方负责）。"""
    order = db.get(KitchenOrder, order_id)
    if not order:
        raise HTTPException(404, "订单不存在")
    dish_yield = {d.id: d.yield_rate for d in db.scalars(select(Dish)).all()}
    ols = [
        {"dish_id": l.dish_id, "portions": l.portions, "dish_yield_rate": dish_yield.get(l.dish_id)}
        for l in db.scalars(select(OrderLine).where(OrderLine.order_id == order_id)).all()
    ]
    bom = [
        {"dish_id": b.dish_id, "ingredient_id": b.ingredient_id,
         "qty_per_portion": b.qty_per_portion, "yield_rate": b.yield_rate}
        for b in db.scalars(select(BomLine)).all()
    ]
    ings = {
        i.id: {"code": i.code, "name": i.name, "unit": i.unit, "stock_qty": i.stock_qty}
        for i in db.scalars(select(Ingredient)).all()
    }
    result = result_to_dict(explode_and_merge(ols, bom, ings))
    result["order"] = {"id": order.id, "code": order.code, "outlet": order.outlet}
    return result


def get_current_run(db: Session, order_id: int) -> PrepRun | None:
    return db.scalars(
        select(PrepRun)
        .where(PrepRun.order_id == order_id, PrepRun.status == "current")
        .order_by(PrepRun.id.desc())
    ).first()


def rewrite_current_run(db: Session, order_id: int) -> PrepRun | None:
    """把当前有效单按定义仓整张重写（占用列与缺料贴一起换）；没有当前单则不动。"""
    run = get_current_run(db, order_id)
    if not run:
        return None
    result = compute_order_result(db, order_id)
    run.result_json = json.dumps(result, ensure_ascii=False)
    db.flush()
    return run

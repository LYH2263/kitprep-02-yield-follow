import json
from datetime import datetime
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session
from app.database import get_db
from app.models.models import KitchenOrder, PrepRun
from app.services.prep_service import compute_order_result, get_current_run, prep_sheet_mutex

router = APIRouter(prefix="/prep", tags=["prep"])

EMPTY_STATS = {"ingredient_count": 0, "shortage_count": 0, "total_shortage_qty": 0}


@router.post("/run")
def run_prep(order_id: int = 1, db: Session = Depends(get_db)):
    """生成备料单：旧当前单钉死为历史单，新单按定义仓当前出成率整张落库。"""
    order = db.get(KitchenOrder, order_id)
    if not order:
        raise HTTPException(404, "订单不存在")
    with prep_sheet_mutex(db, [order_id]):
        result = compute_order_result(db, order_id)
        for old in db.scalars(
            select(PrepRun).where(PrepRun.order_id == order_id, PrepRun.status == "current")
        ).all():
            old.status = "archived"
        run = PrepRun(order_id=order_id, status="current",
                      created_at=datetime.utcnow(), result_json=json.dumps(result, ensure_ascii=False))
        db.add(run)
        db.commit()
    db.refresh(run)
    return {"id": run.id, **result}


@router.get("/latest")
def latest(order_id: int = 1, db: Session = Depends(get_db)):
    """只读已落库的当前有效单；没有就 404，禁止按定义现算冒充已落单。"""
    run = get_current_run(db, order_id)
    if not run:
        raise HTTPException(404, "尚未生成备料单")
    return {"id": run.id, **json.loads(run.result_json)}


@router.get("/shortages")
def shortages(order_id: int = 1, db: Session = Depends(get_db)):
    """缺料贴只读当前有效单的落库内容。"""
    run = get_current_run(db, order_id)
    if not run:
        return {"order_id": order_id, "has_run": False, "shortages": [], "stats": EMPTY_STATS}
    data = json.loads(run.result_json)
    return {"order_id": order_id, "has_run": True,
            "shortages": data.get("shortages", []), "stats": data.get("stats", EMPTY_STATS)}

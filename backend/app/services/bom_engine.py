"""Central kitchen BOM explode: order lines × BOM qty, merge ingredients, shortage = need - stock.

出成率（yield rate）：出品（dish_yield_rate）与用料（yield_rate）均可写，取值 (0, 1]，
未写过（None）按 1 处理。需求 = 份数 × 定额 ÷ (出品率 × 用料率)，率改小需求变大。
"""
from __future__ import annotations
from dataclasses import asdict, dataclass

@dataclass
class NeedLine:
    ingredient_id: int
    ingredient_code: str
    ingredient_name: str
    unit: str
    need_qty: float
    stock_qty: float
    shortage: float

def _yield(value) -> float:
    """None → 1（从未写过）；<= 0 非法，直接拒绝。"""
    if value is None:
        return 1.0
    v = float(value)
    if v <= 0:
        raise ValueError("yield rate must be positive")
    return v

def explode_and_merge(
    order_lines: list[dict],
    bom_lines: list[dict],
    ingredients: dict[int, dict],
) -> list[NeedLine]:
    """order_lines: dish_id, portions, dish_yield_rate?;
    bom_lines: dish_id, ingredient_id, qty_per_portion, yield_rate?."""
    need: dict[int, float] = {}
    for ol in order_lines:
        dish_y = _yield(ol.get("dish_yield_rate"))
        for bl in bom_lines:
            if bl["dish_id"] != ol["dish_id"]:
                continue
            eff = dish_y * _yield(bl.get("yield_rate"))
            need[bl["ingredient_id"]] = need.get(bl["ingredient_id"], 0.0) + ol["portions"] * bl["qty_per_portion"] / eff
    lines: list[NeedLine] = []
    for iid, qty in sorted(need.items()):
        ing = ingredients[iid]
        stock = float(ing.get("stock_qty", 0))
        shortage = max(0.0, qty - stock)
        lines.append(NeedLine(
            ingredient_id=iid,
            ingredient_code=ing["code"],
            ingredient_name=ing["name"],
            unit=ing.get("unit", ""),
            need_qty=round(qty, 3),
            stock_qty=round(stock, 3),
            shortage=round(shortage, 3),
        ))
    return lines

def result_to_dict(lines: list[NeedLine]) -> dict:
    return {
        "prep_lines": [asdict(l) for l in lines],
        "shortages": [asdict(l) for l in lines if l.shortage > 0],
        "stats": {
            "ingredient_count": len(lines),
            "shortage_count": sum(1 for l in lines if l.shortage > 0),
            "total_shortage_qty": round(sum(l.shortage for l in lines), 3),
        },
    }

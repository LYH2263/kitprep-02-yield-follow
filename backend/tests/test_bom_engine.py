from app.services.bom_engine import explode_and_merge

def test_explode_merge():
    order_lines = [{"dish_id": 1, "portions": 10}, {"dish_id": 2, "portions": 5}]
    bom = [
        {"dish_id": 1, "ingredient_id": 1, "qty_per_portion": 0.2},
        {"dish_id": 1, "ingredient_id": 2, "qty_per_portion": 0.1},
        {"dish_id": 2, "ingredient_id": 1, "qty_per_portion": 0.3},
    ]
    ings = {
        1: {"code": "A", "name": "肉", "unit": "kg", "stock_qty": 1.0},
        2: {"code": "B", "name": "米", "unit": "kg", "stock_qty": 5.0},
    }
    lines = explode_and_merge(order_lines, bom, ings)
    by_id = {l.ingredient_id: l for l in lines}
    assert by_id[1].need_qty == 3.5  # 10*0.2 + 5*0.3
    assert by_id[1].shortage == 2.5
    assert by_id[2].need_qty == 1.0
    assert by_id[2].shortage == 0.0

def test_no_negative_shortage():
    order_lines = [{"dish_id": 1, "portions": 1}]
    bom = [{"dish_id": 1, "ingredient_id": 1, "qty_per_portion": 1.0}]
    ings = {1: {"code": "A", "name": "油", "unit": "L", "stock_qty": 10.0}}
    lines = explode_and_merge(order_lines, bom, ings)
    assert lines[0].shortage == 0.0

def test_yield_rate_smaller_means_bigger_need():
    order_lines = [{"dish_id": 1, "portions": 10}]
    bom = [{"dish_id": 1, "ingredient_id": 1, "qty_per_portion": 0.2, "yield_rate": 0.5}]
    ings = {1: {"code": "A", "name": "肉", "unit": "kg", "stock_qty": 0.0}}
    lines = explode_and_merge(order_lines, bom, ings)
    assert lines[0].need_qty == 4.0  # 10*0.2/0.5，率改小需求变大

def test_yield_rate_one_or_unset_matches_plain_explode():
    order_lines = [{"dish_id": 1, "portions": 10}]
    ings = {1: {"code": "A", "name": "肉", "unit": "kg", "stock_qty": 0.0}}
    plain = explode_and_merge(order_lines, [{"dish_id": 1, "ingredient_id": 1, "qty_per_portion": 0.2}], ings)
    one = explode_and_merge(order_lines, [{"dish_id": 1, "ingredient_id": 1, "qty_per_portion": 0.2, "yield_rate": 1.0}], ings)
    assert plain[0].need_qty == one[0].need_qty == 2.0

def test_dish_yield_rate_multiplies_with_line_yield():
    order_lines = [{"dish_id": 1, "portions": 10, "dish_yield_rate": 0.5}]
    bom = [{"dish_id": 1, "ingredient_id": 1, "qty_per_portion": 0.2, "yield_rate": 0.5}]
    ings = {1: {"code": "A", "name": "肉", "unit": "kg", "stock_qty": 0.0}}
    lines = explode_and_merge(order_lines, bom, ings)
    assert lines[0].need_qty == 8.0  # 10*0.2/(0.5*0.5)

def test_zero_yield_rate_rejected():
    import pytest
    order_lines = [{"dish_id": 1, "portions": 1}]
    bom = [{"dish_id": 1, "ingredient_id": 1, "qty_per_portion": 0.2, "yield_rate": 0}]
    ings = {1: {"code": "A", "name": "肉", "unit": "kg", "stock_qty": 0.0}}
    with pytest.raises(ValueError):
        explode_and_merge(order_lines, bom, ings)

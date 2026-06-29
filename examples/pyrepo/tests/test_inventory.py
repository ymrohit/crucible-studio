from inventory import total_value, apply_discount

def test_total():
    assert total_value([{"price": 2.0, "qty": 3}, {"price": 1.5, "qty": 2}]) == 9.0

def test_discount():
    assert apply_discount(100.0, 10) == 90.0      # 10% off 100 -> 90

def test_discount_zero():
    assert apply_discount(50.0, 0) == 50.0

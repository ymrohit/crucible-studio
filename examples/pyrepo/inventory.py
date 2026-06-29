"""Tiny inventory helpers."""

def total_value(items):
    """items: list of {"price": float, "qty": int} -> sum of price*qty."""
    return sum(i["price"] * i["qty"] for i in items)


def apply_discount(total, pct):
    """Apply a percentage discount. pct is a percentage in 0..100."""
    return total - total * pct   # BUG: treats pct as a fraction, not a percentage

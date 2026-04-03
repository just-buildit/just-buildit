from calc._core import add, multiply


def add_and_multiply(a: int, b: int) -> tuple[int, int]:
    """Return (a+b, a*b)."""
    return add(a, b), multiply(a, b)

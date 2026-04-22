from collage_web.utils import calculate_grid

def test_grid_for_one():
    assert calculate_grid(1) == (1, 1)

def test_grid_for_ten():
    cols, rows = calculate_grid(10)
    assert cols * rows >= 10

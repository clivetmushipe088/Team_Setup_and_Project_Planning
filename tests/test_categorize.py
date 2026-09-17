from etl import categorize


def test_categorize_exists():
    assert callable(categorize.categorize)

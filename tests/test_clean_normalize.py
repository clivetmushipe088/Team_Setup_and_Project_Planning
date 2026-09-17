from etl import clean_normalize


def test_clean_functions_exist():
    assert callable(clean_normalize.clean_amount)
    assert callable(clean_normalize.clean_date)
    assert callable(clean_normalize.clean_phone)

from etl import parse_xml


def test_parse_xml_exists():
    assert callable(parse_xml.parse_xml)

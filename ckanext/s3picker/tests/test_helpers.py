from ckanext.s3picker import helpers


def test_number_has_thousands_separators():
    assert helpers.s3picker_number(0) == '0'
    assert helpers.s3picker_number(999) == '999'
    assert helpers.s3picker_number(100000) == '100,000'
    assert helpers.s3picker_number(14371) == '14,371'
    assert helpers.s3picker_number(None) == '0'


def test_filesize():
    assert helpers.s3picker_filesize(500) == '500 B'
    assert helpers.s3picker_filesize(168.5 * 1024) == '168.5 KB'

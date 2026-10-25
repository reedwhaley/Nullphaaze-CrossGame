from nullphaaze_crossgame import catalog
import pytest

def test_gc_catalog_contains_only_resource_identifiers():
    data = catalog("corruption_gc_catalog")
    assert len(data) == 30
    assert all(len(ids) == 2 and type(ids[0]) is int and 0 <= ids[0] < 2**64
               and (ids[1] is None or (type(ids[1]) is int and 0 <= ids[1] < 2**64))
               for ids in data.values())

def test_import_catalog_retains_expected_metadata_inventory():
    data = catalog()
    assert len(data["prime_catalog"]) == 47
    assert len(data["presentation"]) == 93
    assert len(data["expected_files"]) == 770

def test_unknown_catalog_is_rejected():
    with pytest.raises(ValueError, match="Unknown"):
        catalog("../private")

from dxrk.version import Version


def test_version_matches_go():
    assert Version == "4.0.0"


def test_version_is_str():
    assert isinstance(Version, str)

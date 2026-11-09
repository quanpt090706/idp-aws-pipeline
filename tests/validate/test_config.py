import pytest

from config import Settings, load_settings


def test_settings_read_required_and_optional_env():
    cfg = load_settings({
        "DOCUMENTS_TABLE": "documents", "QUEUE_URL": "queue",
        "MAX_FILE_SIZE_BYTES": "32", "UPLOAD_PREFIX": "incoming/",
        "UPLOAD_BUCKET": "bucket",
    })
    assert cfg == Settings("documents", "queue", 32, "incoming/", "bucket")


@pytest.mark.parametrize("env", [{}, {"DOCUMENTS_TABLE": "d"}])
def test_missing_required_env(env):
    with pytest.raises(KeyError):
        load_settings(env)


@pytest.mark.parametrize("kwargs", [
    {"max_file_size_bytes": 0}, {"max_file_size_bytes": -1},
    {"upload_prefix": ""}, {"upload_prefix": "uploads"},
])
def test_invalid_configuration(kwargs):
    with pytest.raises(ValueError):
        Settings("documents", "queue", **kwargs)

import io
import json
import urllib.error

import pytest

from taq.exceptions import NetworkError, PackageNotFoundError
from taq.pypi import PyPIClient


class _FakeResponse:
    def __init__(self, payload):
        self._data = json.dumps(payload).encode("utf-8")

    def read(self):
        return self._data

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def test_get_package_info_parses_releases(monkeypatch):
    payload = {
        "info": {"name": "foo", "version": "1.2.0", "summary": "Foo package"},
        "releases": {
            "1.0.0": [
                {
                    "filename": "foo-1.0.0-py3-none-any.whl",
                    "url": "http://x/foo-1.0.0-py3-none-any.whl",
                    "size": 100,
                    "packagetype": "bdist_wheel",
                    "python_version": "py3",
                    "requires_python": None,
                    "digests": {"sha256": "abc"},
                }
            ],
            "0.9.0": [],  # yanked/empty releases should be skipped
        },
    }

    monkeypatch.setattr("urllib.request.urlopen", lambda *a, **k: _FakeResponse(payload))

    client = PyPIClient()
    info = client.get_package_info("foo")

    assert info.name == "foo"
    assert info.latest_version == "1.2.0"
    assert "1.0.0" in info.releases
    assert "0.9.0" not in info.releases
    assert info.files_for("1.0.0")[0].is_wheel
    assert info.files_for("1.0.0")[0].sha256 == "abc"


def test_404_raises_package_not_found(monkeypatch):
    def raise_404(*a, **k):
        raise urllib.error.HTTPError("http://x", 404, "Not Found", {}, io.BytesIO(b""))

    monkeypatch.setattr("urllib.request.urlopen", raise_404)

    client = PyPIClient()
    with pytest.raises(PackageNotFoundError):
        client.get_package_info("this-package-does-not-exist")


def test_connection_error_raises_network_error(monkeypatch):
    def raise_url_error(*a, **k):
        raise urllib.error.URLError("no network")

    monkeypatch.setattr("urllib.request.urlopen", raise_url_error)

    client = PyPIClient()
    with pytest.raises(NetworkError):
        client.get_package_info("foo")

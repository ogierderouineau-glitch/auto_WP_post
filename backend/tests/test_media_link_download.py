"""Tests for downloading a media link (SSRF guard, type check, size limit, redirects)."""
import pytest

from backend.app.storage import step_02_uploads as uploads


class FakeResponse:
    def __init__(self, status=200, headers=None, body=b"x" * 10):
        self.status_code, self.headers, self.body = status, headers or {}, body
        self.is_redirect = status in (301, 302)
        self.ok = status < 400

    def __enter__(self):
        return self

    def __exit__(self, *args):
        pass

    def iter_content(self, size):
        yield self.body


def patch_network(monkeypatch, responses, address="93.184.216.34"):
    monkeypatch.setattr(uploads.socket, "getaddrinfo", lambda *a: [(0, 0, 0, "", (address, 0))])
    queue = iter(responses)
    monkeypatch.setattr(uploads.requests, "get", lambda *a, **k: next(queue))


def test_downloads_image_and_adds_extension(monkeypatch, tmp_path):
    patch_network(monkeypatch, [FakeResponse(headers={"Content-Type": "image/jpeg"})])
    assert uploads.download_media_url("https://cdn.example/photo", tmp_path / "f", 100) == ("image/jpeg", "photo.jpg")
    assert (tmp_path / "f").stat().st_size == 10


@pytest.mark.parametrize("url,address", [("ftp://example.com/a.jpg", "93.184.216.34"), ("http://intranet/a.jpg", "10.0.0.5"), ("http://localhost/a.jpg", "127.0.0.1")])
def test_rejects_non_http_and_private_hosts(monkeypatch, tmp_path, url, address):
    patch_network(monkeypatch, [FakeResponse(headers={"Content-Type": "image/png"})], address)
    with pytest.raises(ValueError):
        uploads.download_media_url(url, tmp_path / "f", 100)


def test_rejects_html_page_and_oversize(monkeypatch, tmp_path):
    patch_network(monkeypatch, [FakeResponse(headers={"Content-Type": "text/html"})])
    with pytest.raises(ValueError, match="directly"):
        uploads.download_media_url("https://example.com/share", tmp_path / "f", 100)
    patch_network(monkeypatch, [FakeResponse(headers={"Content-Type": "image/png"})])
    with pytest.raises(ValueError, match="limit"):
        uploads.download_media_url("https://example.com/a.png", tmp_path / "f", 5)


def test_redirect_is_followed_and_rechecked(monkeypatch, tmp_path):
    patch_network(monkeypatch, [FakeResponse(302, {"Location": "/b.mp4"}), FakeResponse(headers={"Content-Type": "video/mp4"})])
    assert uploads.download_media_url("https://example.com/a", tmp_path / "f", 100) == ("video/mp4", "b.mp4")

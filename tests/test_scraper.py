import threading
import time
from http.server import BaseHTTPRequestHandler, HTTPServer

import pytest

from dxrk.scraper import Result, extract_domain, scrape


class ScrapeHandler(BaseHTTPRequestHandler):
    def do_GET(self):  # noqa: N802
        if self.path == "/slow":
            time.sleep(0.5)
            return
        body = (
            b"<html><head><title>Test Page</title></head>"
            b"<body><h1>Hello</h1>"
            b'<a href="/one">One</a><a href="/two">Two</a>'
            b"</body></html>"
        )
        self.send_response(200)
        self.send_header("Content-Type", "text/html")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, format, *args):
        pass


@pytest.fixture
def server():
    httpd = HTTPServer(("127.0.0.1", 0), ScrapeHandler)
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    yield f"http://127.0.0.1:{httpd.server_address[1]}"
    httpd.shutdown()


def test_scrape(server):
    res = scrape(server, 5.0)
    assert isinstance(res, Result)
    assert res.url == server
    assert res.title == "Test Page"
    assert "Hello" in res.content
    assert res.links == ["/one", "/two"]


def test_scrape_timeout(server):
    url = f"{server}/slow"
    with pytest.raises(RuntimeError, match=f"^scrape {url}:"):
        scrape(url, 0.1)


def test_scrape_invalid_url():
    with pytest.raises(RuntimeError, match="^scrape"):
        scrape("://not-a-url", 1.0)


def test_extract_domain():
    assert extract_domain("https://example.com/path?q=1") == "example.com"
    assert extract_domain("http://127.0.0.1:8080/x") == "127.0.0.1"
    assert extract_domain("://bad") == ""

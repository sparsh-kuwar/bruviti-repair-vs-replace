"""Fixtures for the browser tests: a real server process and real browsers.

The server is started exactly as in production (uvicorn, one process, serving
API and page). Each test runs in Chromium, Firefox and WebKit unless
E2E_BROWSERS narrows it, e.g. E2E_BROWSERS=webkit.
"""

from __future__ import annotations

import os
import socket
import subprocess
import sys
import time
import urllib.request
from pathlib import Path
from urllib.parse import urlparse

import pytest
from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parent.parent
BROWSERS = [b for b in os.environ.get("E2E_BROWSERS", "chromium,firefox,webkit").split(",") if b]


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@pytest.fixture(scope="session")
def base_url():
    port = _free_port()
    proc = subprocess.Popen(
        [sys.executable, "-m", "uvicorn", "app.main:app", "--host", "127.0.0.1", "--port", str(port)],
        cwd=ROOT, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )
    url = f"http://127.0.0.1:{port}"
    for _ in range(100):
        try:
            if urllib.request.urlopen(url + "/health", timeout=1).status == 200:
                break
        except OSError:
            time.sleep(0.1)
    else:
        proc.terminate()
        raise RuntimeError("server did not start")
    yield url
    proc.terminate()
    proc.wait(timeout=10)


@pytest.fixture(scope="session")
def playwright_instance():
    with sync_playwright() as p:
        yield p


@pytest.fixture(scope="session", params=BROWSERS)
def browser(request, playwright_instance):
    b = getattr(playwright_instance, request.param).launch()
    yield b
    b.close()


@pytest.fixture
def browser_name(browser):
    return browser.browser_type.name


@pytest.fixture
def page(browser, base_url):
    """A fresh page at 1440x1000. Fails the test if the page requests anything
    that is not this local server (no CDNs, fonts, images or external APIs)."""
    context = browser.new_context(viewport={"width": 1440, "height": 1000})
    external = []

    def record(req):
        host = urlparse(req.url).hostname
        if req.url.startswith(("data:", "about:")):
            return
        if host not in ("127.0.0.1", "localhost"):
            external.append(req.url)

    context.on("request", record)
    pg = context.new_page()
    pg.goto(base_url + "/")
    pg.wait_for_selector("#engine-status.pill-ok")
    yield pg
    context.close()
    assert not external, f"page made external requests: {external}"

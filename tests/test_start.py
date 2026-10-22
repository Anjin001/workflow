import io
import json
import socket

import start


def test_startup_selects_another_port_when_requested_port_is_busy():
    with socket.socket() as occupied:
        occupied.bind(("127.0.0.1", 0))
        port = occupied.getsockname()[1]
        with start.bind_socket(port) as selected:
            assert selected.getsockname()[0] == "127.0.0.1"
            assert selected.getsockname()[1] != port


def test_existing_service_is_reused_without_starting_another(tmp_path, monkeypatch):
    instance = tmp_path / "instance.json"
    instance.write_text(json.dumps({"port": 8765, "pid": 123}))
    monkeypatch.setattr(start, "INSTANCE_FILE", instance)
    monkeypatch.setattr(
        start.urllib.request,
        "urlopen",
        lambda *args, **kwargs: io.BytesIO(
            json.dumps({"app": "code-review-workflow", "pid": 123}).encode()
        ),
    )
    opened = []
    monkeypatch.setattr(start.webbrowser, "open", opened.append)
    assert start.main([]) == 0
    assert opened == ["http://127.0.0.1:8765"]


def test_stale_instance_file_is_ignored(tmp_path, monkeypatch):
    instance = tmp_path / "instance.json"
    instance.write_text("not json")
    monkeypatch.setattr(start, "INSTANCE_FILE", instance)
    assert start.existing_instance() is None


def test_browser_opens_only_after_health_endpoint_is_ready(monkeypatch):
    monkeypatch.setattr(start.urllib.request, "urlopen", lambda *args, **kwargs: io.BytesIO(b"{}"))
    opened = []
    monkeypatch.setattr(start.webbrowser, "open", opened.append)
    start.open_when_ready("http://127.0.0.1:8765")
    assert opened == ["http://127.0.0.1:8765"]

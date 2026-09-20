"""The server, over a real socket, with no hardware anywhere near it."""

import json
import threading
import urllib.error
import urllib.request

import pytest

import iio_browse


@pytest.fixture(scope="module")
def server(tools_root):
    import os
    path = os.path.join(tools_root, "fixtures", "m2k-snapshot.json")
    snapshot = iio_browse.load_snapshot(path)
    import iio_explain
    handler = iio_browse.make_handler(snapshot, iio_explain.annotate(snapshot),
                                      path)
    from http.server import ThreadingHTTPServer
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), handler)
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    yield "http://127.0.0.1:%d" % httpd.server_address[1]
    httpd.shutdown()
    httpd.server_close()


def get(base, route):
    with urllib.request.urlopen(base + route) as response:
        return response.status, response.read()


def post(base, route, payload):
    request = urllib.request.Request(
        base + route, data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json"}, method="POST")
    with urllib.request.urlopen(request) as response:
        return response.status, json.loads(response.read())


def test_page_and_assets_are_served(server):
    for route, needle in (("/", b"IIO Browser"),
                          ("/app.js", b"api/emit"),
                          ("/style.css", b"chip")):
        status, body = get(server, route)
        assert status == 200
        assert needle in body


def test_tree_is_the_annotated_capture(server):
    status, body = get(server, "/api/tree")
    payload = json.loads(body)
    assert status == 200
    assert payload["source"] == "m2k-snapshot.json"
    assert payload["defaults"]["buffer_size"] == 32768
    device = payload["capture"]["devices"][0]
    assert device["label"] == "m2k-adc"
    assert device["channels"][0]["data_format"]["shorthand"]


def test_emit_turns_a_selection_into_block_fields(server):
    status, payload = post(server, "/api/emit", {
        "device": "m2k-adc", "channels": ["voltage0"],
        "settings": [{"channel": None, "attr": "oversampling_ratio",
                      "value": "4"}]})
    assert status == 200
    assert payload["fields"]["channels"] == ["voltage0"]
    assert payload["params"] == ["oversampling_ratio=4"]
    assert payload["make"].startswith("iio.device_source(")


def test_bad_input_is_refused_not_crashed(server):
    request = urllib.request.Request(
        server + "/api/emit", data=b"{not json",
        headers={"Content-Type": "application/json"}, method="POST")
    with pytest.raises(urllib.error.HTTPError) as caught:
        urllib.request.urlopen(request)
    assert caught.value.code == 400

    with pytest.raises(urllib.error.HTTPError) as caught:
        urllib.request.urlopen(server + "/api/nope")
    assert caught.value.code == 404


def test_a_capture_that_is_not_one_is_rejected(tmp_path):
    path = tmp_path / "bogus.json"
    path.write_text('{"hello": "world"}')
    with pytest.raises(ValueError):
        iio_browse.load_snapshot(str(path))

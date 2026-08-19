"""Tests for the LCSC/EasyEDA importer."""

from unittest.mock import patch

from zaptrace.core.models import LayerSet, PadShape
from zaptrace.ee.imports.lcsc import import_lcsc_component, parse_easyeda_footprint

MOCK_FOOTPRINT = {
    "dataStr": {
        "head": {"x": 4000, "y": 3000, "c_para": {"package": "SOIC-8"}},
        "shape": [
            "PAD~RECT~4008.661~3000~7.874~7.874~1~1~0~0~path~180~id1~1~~Y~0~0~0.2~id1",
            "PAD~RECT~3991.339~3000~7.874~7.874~1~2~0~0~path~180~id2~2~~Y~0~0~0.2~id2",
            "CIRCLE~4000~3000~10~1~id",
        ],
    }
}

MOCK_SYMBOL = {
    "dataStr": {
        "shape": [
            (
                "P~show~0~1~-20~0~180~id1~0~-20~0~M -20 0 h 15~#800~0~-1~0~0~C~start~#800~"
                "0~-9~-4~0~1~end~#800~0~-8~0~0~M -5 3 L -2 0 L -5 -3"
            ),
            "PL~-5 8 -5 -8~#880000~1~0~none~id2~0",
        ]
    }
}


@patch("zaptrace.ee.imports.lcsc.fetch_lcsc_component")
def test_import_lcsc_component(mock_fetch):
    mock_fetch.return_value = (MOCK_SYMBOL, MOCK_FOOTPRINT)

    fp, sym = import_lcsc_component("C12345")

    assert fp is not None
    assert len(fp.pads) == 2
    assert "LCSC:C12345" in fp.description
    assert fp.pads[0].id == "1"
    assert fp.pads[1].id == "2"

    assert sym is not None
    assert len(sym.pins) == 1
    assert len(sym.body) == 1


@patch("zaptrace.ee.imports.lcsc.fetch_lcsc_component")
def test_import_lcsc_component_fail(mock_fetch):
    mock_fetch.return_value = None
    fp, sym = import_lcsc_component("C12345")
    assert fp is None
    assert sym is None


def test_parse_easyeda_footprint_track():
    mock_data = {
        "dataStr": {
            "head": {"x": 4000, "y": 3000, "c_para": {"package": "TEST"}},
            "shape": ["TRACK~1~1~net~4000 3000 4010 3000"],
        }
    }
    fp = parse_easyeda_footprint(mock_data)
    assert len(fp.outline) == 1
    assert fp.outline[0].type == "line"


def test_parse_easyeda_footprint_pad_oval_circle():
    mock_data = {
        "dataStr": {
            "head": {"x": 4000, "y": 3000, "c_para": {"package": "TEST"}},
            "shape": [
                "PAD~CIRCLE~4000~3000~10~10~1~1~0~0~path~180~id1~1~~Y~0~0~0.2~id1",
                "PAD~OVAL~4000~3000~10~20~1~2~0~0~path~180~id2~2~~Y~0~0~0.2~id2",
                "PAD~ELLIPSE~4000~3000~10~20~11~3~10~0~path~180~id3~3~~Y~0~0~0.2~id3",
            ],
        }
    }

    fp = parse_easyeda_footprint(mock_data)
    assert len(fp.pads) == 3
    assert fp.pads[0].shape == PadShape.CIRCLE
    assert fp.pads[1].shape == PadShape.OVAL
    assert fp.pads[2].shape == PadShape.OVAL
    assert fp.pads[2].layer == LayerSet.ALL
    assert fp.pads[2].drill is not None


def test_parse_easyeda_symbol_misc():
    from zaptrace.ee.imports.lcsc import parse_easyeda_symbol

    mock_data = {
        "dataStr": {
            "shape": [
                (
                    "P~show~0~1~-20~0~180~id1~0~-20~0~M -20 0 h 15~#800~0~-1~0~0~C~start~#800~"
                    "0~-9~-4~0~1~end~#800~0~-8~0~0~M -5 3 L -2 0 L -5 -3"
                ),
                "PL~-5 8 -5 -8~#880000~1~0~none~id2~0",
                "PT~svg path~...",
                "P~invalid",
                "PL~invalid",
                "UNKNOWN~123",
                (
                    "P~show~0~1~invalid~0~180~id1~0~-20~0~M -20 0 h 15~#800~0~-1~0~0~C~start~#800~"
                    "0~-9~-4~0~1~end~#800~0~-8~0~0~M -5 3 L -2 0 L -5 -3"
                ),
            ]
        }
    }
    sym = parse_easyeda_symbol(mock_data)
    assert len(sym.pins) == 1
    assert len(sym.body) == 1


def test_parse_easyeda_footprint_misc():
    mock_data = {
        "dataStr": {
            "head": {"x": 4000, "y": 3000, "c_para": {"package": "TEST"}},
            "shape": [
                "PAD~RECT~invalid~3000~7.874~7.874~1~1~0~0~path~180~id1~1~~Y~0~0~0.2~id1",
                "TRACK~invalid~1~net~4000 3000 4010 3000",
                "CIRCLE~invalid~3000~10~1~id",
                "UNKNOWN~123",
            ],
        }
    }
    fp = parse_easyeda_footprint(mock_data)
    assert len(fp.pads) == 0
    assert len(fp.outline) == 0


@patch("httpx.Client")
def test_fetch_lcsc_component_httpx_post_fail(mock_httpx):
    import httpx

    from zaptrace.ee.imports.lcsc import fetch_lcsc_component

    mock_client = mock_httpx.return_value.__enter__.return_value
    mock_client.post.side_effect = httpx.RequestError("Failed to fetch")

    # Needs a dummy cache dir patch ideally, or we ensure it's not cached
    res = fetch_lcsc_component("C99999123_not_cached")
    assert res is None


@patch("httpx.Client")
def test_fetch_lcsc_component_httpx_post_empty_res(mock_httpx):
    from zaptrace.ee.imports.lcsc import fetch_lcsc_component

    mock_client = mock_httpx.return_value.__enter__.return_value
    mock_response = mock_client.post.return_value
    mock_response.json.return_value = {"result": {"lists": {"lcsc": []}}}

    res = fetch_lcsc_component("C99999123_not_cached2")
    assert res is None


@patch("httpx.Client")
def test_fetch_lcsc_component_httpx_get_fail(mock_httpx):
    import httpx

    from zaptrace.ee.imports.lcsc import fetch_lcsc_component

    mock_client = mock_httpx.return_value.__enter__.return_value

    # First post succeeds
    mock_response_post = mock_client.post.return_value
    mock_response_post.json.return_value = {
        "result": {"lists": {"lcsc": [{"uuid": "sym_uuid", "dataStr": {"head": {"puuid": "fp_uuid"}}}]}}
    }

    # Get fails
    mock_client.get.side_effect = httpx.RequestError("Failed to fetch")

    res = fetch_lcsc_component("C99999123_not_cached_get")
    # Even if GET fails, fetch_lcsc_component catches the error and moves on,
    # but since both symbol and footprint fail, it returns None.
    assert res is None


@patch("httpx.Client")
def test_fetch_lcsc_component_caches_footprint_only_result(mock_httpx, tmp_path, monkeypatch):
    from zaptrace.ee.imports import lcsc

    monkeypatch.setattr(lcsc, "CACHE_DIR", tmp_path)
    mock_client = mock_httpx.return_value.__enter__.return_value
    mock_client.post.return_value.json.return_value = {
        "result": {"lists": {"lcsc": [{"uuid": "sym_uuid", "dataStr": {"head": {"puuid": "fp_uuid"}}}]}}
    }
    mock_client.get.side_effect = [
        type("Response", (), {"raise_for_status": lambda self: None, "json": lambda self: {"success": False}})(),
        type(
            "Response",
            (),
            {"raise_for_status": lambda self: None, "json": lambda self: {"success": True, "result": {"shape": []}}},
        )(),
    ]

    result = lcsc.fetch_lcsc_component("C_FOOTPRINT_ONLY")

    assert result == ({}, {"shape": []})
    assert (tmp_path / "C_FOOTPRINT_ONLY.json").is_file()


@patch("httpx.Client")
def test_fetch_lcsc_component_httpx_cache_hit(mock_httpx):
    import json

    from zaptrace.ee.imports.lcsc import CACHE_DIR, fetch_lcsc_component

    test_id = "C_TEST_CACHE_HIT"
    cache_file = CACHE_DIR / f"{test_id}.json"

    with open(cache_file, "w") as f:
        json.dump({"symbol": {"cached": "sym"}, "footprint": {"cached": "fp"}}, f)

    try:
        res = fetch_lcsc_component(test_id)
        assert res is not None
        assert res[0] == {"cached": "sym"}
        assert res[1] == {"cached": "fp"}
        mock_httpx.assert_not_called()
    finally:
        cache_file.unlink()

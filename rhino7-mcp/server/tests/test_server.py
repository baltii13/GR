import asyncio

from rhino_mcp import server

EXPECTED = {
    "ping", "get_document_info", "get_objects", "get_object_info", "get_selected_objects",
    "create_object", "delete_objects", "transform_objects", "set_object_attributes",
    "boolean_operation", "list_layers", "create_layer", "set_current_layer", "select_objects",
    "run_rhino_command", "execute_python", "capture_viewport", "zoom_extents", "undo",
}


def test_tools_registered():
    tools = asyncio.run(server.mcp.list_tools())
    assert EXPECTED <= {t.name for t in tools}


def test_call_drops_none(monkeypatch):
    seen = {}
    monkeypatch.setattr(server._conn, "send", lambda c, p=None: seen.update(c=c, p=p) or "ok")
    server.get_objects(layer="A")
    assert seen["c"] == "get_objects" and "name" not in seen["p"] and seen["p"]["layer"] == "A"

"""MCP server exposing Rhino 7 tools. Talks to the listener running inside Rhino."""

from __future__ import annotations

import base64
import logging
import sys
from typing import Any

from mcp.server.fastmcp import FastMCP, Image

from .connection import RhinoConnection, RhinoError

# stdout is the MCP stdio transport: log to stderr only.
logging.basicConfig(level=logging.INFO, stream=sys.stderr,
                    format="%(asctime)s %(name)s %(levelname)s: %(message)s")
log = logging.getLogger("rhino_mcp")

mcp = FastMCP("rhino7")
_conn = RhinoConnection()

Point = list[float]
Color = list[int]


def _call(command: str, **params: Any) -> Any:
    """Send a command to Rhino, dropping parameters that are None."""
    clean = {k: v for k, v in params.items() if v is not None}
    return _conn.send(command, clean)


# ---------------------------------------------------------------------------
# Inspection
# ---------------------------------------------------------------------------

@mcp.tool()
def ping() -> Any:
    """Check the connection to Rhino. Returns Rhino and listener versions."""
    return _call("ping")


@mcp.tool()
def get_document_info() -> Any:
    """Get info on the active Rhino document: file path, model units, absolute
    tolerance, object count, layer summary (with object counts) and the
    bounding box of all objects. Call this FIRST to learn the units and scale."""
    return _call("get_document_info")


@mcp.tool()
def get_objects(layer: str | None = None, object_type: str | None = None,
                name: str | None = None, selected_only: bool = False,
                limit: int = 200) -> Any:
    """List objects in the document with id, name, type, layer, color and bounding box.

    Args:
        layer: only objects on this layer (full path such as "Parent::Child", or name).
        object_type: Rhino object type, case-insensitive: point, curve, surface,
            brep (polysurface/solid), extrusion, mesh, annotation (text), subd, hatch...
        name: only objects with exactly this name.
        selected_only: only currently selected objects.
        limit: max objects returned (default 200).
    """
    return _call("get_objects", layer=layer, object_type=object_type, name=name,
                 selected_only=selected_only, limit=limit)


@mcp.tool()
def get_object_info(id: str) -> Any:
    """Detailed info for one object: attributes plus geometry data (point
    coordinates; curve start/end/length/closed; brep/extrusion area, volume and
    centroid when solid; mesh counts; text) and user text."""
    return _call("get_object_info", id=id)


@mcp.tool()
def get_selected_objects() -> Any:
    """Summaries of the objects currently selected in Rhino."""
    return _call("get_selected_objects")


# ---------------------------------------------------------------------------
# Creation and editing
# ---------------------------------------------------------------------------

@mcp.tool()
def create_object(type: str, params: dict[str, Any], name: str | None = None,
                  layer: str | None = None, color: Color | None = None) -> Any:
    """Create one geometric object and return its id. Coordinates are [x, y, z]
    in model units (z optional, defaults to 0). Angles are in degrees.

    `type` and the required `params` keys:
      point:   {"point": [x,y,z]}
      line:    {"start": [..], "end": [..]}
      polyline:{"points": [[..],[..],...], "closed": false}
      circle:  {"center": [..], "radius": r, "normal": [0,0,1]?}
      arc:     {"center": [..], "radius": r, "start_angle_degrees": 0, "end_angle_degrees": 90, "normal"?}
               or {"points": [start, through, end]}
      rectangle: {"corner": [..], "width": w (x), "height": h (y), "normal"?}   (closed polyline)
      box:     {"corner": [..], "width": x-size, "depth": y-size, "height": z-size}  (solid)
      sphere:  {"center": [..], "radius": r}  (solid)
      cylinder:{"base": [..], "radius": r, "height": h, "normal": [0,0,1]?, "cap": true}  (solid)
      cone:    {"base": [..], "radius": r, "height": h, "normal"?, "cap": true}  (base center; apex up)
      surface_from_points: {"points": [[row of points],[row],...]} (grid, >=2x2) or
               flat list + "u_count","v_count"; optional "u_degree","v_degree"
      text:    {"text": "...", "point": [..], "height": 1.0, "font": "Arial"}

    Optional: name, layer (created if missing; "Parent::Child" paths work if
    the parent exists), color [r,g,b] 0-255.
    """
    p = dict(params or {})
    p["type"] = type
    return _call("create_object", **p, name=name, layer=layer, color=color)


@mcp.tool()
def delete_objects(ids: list[str]) -> Any:
    """Delete objects by id. Undoable with `undo`."""
    return _call("delete_objects", ids=ids)


@mcp.tool()
def transform_objects(ids: list[str], operation: str, vector: Point | None = None,
                      angle_degrees: float | None = None, axis: Point | None = None,
                      center: Point | None = None, scale: float | list[float] | None = None,
                      plane_origin: Point | None = None, plane_normal: Point | None = None,
                      copy: bool | None = None) -> Any:
    """Transform objects and return the resulting ids (ids may change!).

    operation:
      move:   requires `vector` [dx,dy,dz]
      copy:   requires `vector`; originals stay, returns ids of the copies
      rotate: requires `angle_degrees`; optional `axis` (default [0,0,1]) and `center` (default origin)
      scale:  requires `scale` (number, or [sx,sy,sz]); optional `center` (default origin)
      mirror: requires `plane_origin` and `plane_normal`; pass copy=true to keep the original
    `copy` (optional) forces copy vs. in-place for any operation.
    """
    return _call("transform_objects", ids=ids, operation=operation, vector=vector,
                 angle_degrees=angle_degrees, axis=axis, center=center, scale=scale,
                 plane_origin=plane_origin, plane_normal=plane_normal, copy=copy)


@mcp.tool()
def set_object_attributes(ids: list[str], name: str | None = None, layer: str | None = None,
                          color: Color | None = None,
                          user_text: dict[str, str] | None = None) -> Any:
    """Set name, layer (created if missing), color [r,g,b] and/or user text
    key/values on the given objects. Omitted fields are left unchanged."""
    return _call("set_object_attributes", ids=ids, name=name, layer=layer, color=color,
                 user_text=user_text)


@mcp.tool()
def boolean_operation(operation: str, ids_a: list[str], ids_b: list[str] | None = None,
                      delete_input: bool = True) -> Any:
    """Boolean on closed solids (breps/extrusions). operation is union,
    difference (A minus B) or intersection. For union, ids_a and ids_b are all
    merged (ids_b optional). Returns the new object ids. Fails if inputs are not
    valid closed solids that overlap."""
    return _call("boolean_operation", operation=operation, ids_a=ids_a, ids_b=ids_b,
                 delete_input=delete_input)


# ---------------------------------------------------------------------------
# Layers and selection
# ---------------------------------------------------------------------------

@mcp.tool()
def list_layers() -> Any:
    """List all layers (full path, color, visibility, lock, parent) and the current layer."""
    return _call("list_layers")


@mcp.tool()
def create_layer(name: str, color: Color | None = None, parent: str | None = None) -> Any:
    """Create a layer (optionally with color [r,g,b] and a parent layer path).
    If it already exists it is returned with created=false."""
    return _call("create_layer", name=name, color=color, parent=parent)


@mcp.tool()
def set_current_layer(name: str) -> Any:
    """Make an existing layer current (new geometry from manual commands goes there)."""
    return _call("set_current_layer", name=name)


@mcp.tool()
def select_objects(ids: list[str], clear_existing: bool = True) -> Any:
    """Select objects by id, optionally keeping the existing selection."""
    return _call("select_objects", ids=ids, clear_existing=clear_existing)


# ---------------------------------------------------------------------------
# Power tools
# ---------------------------------------------------------------------------

@mcp.tool()
def run_rhino_command(command: str, echo: bool = True) -> Any:
    """Run a Rhino command string like the command line would, e.g.
    "_-Fillet 2 ..." or "_SelAll _Enter". Prefix with underscore and use the
    dash form (-Command) to avoid dialogs; a command waiting for interactive
    input blocks Rhino. WARNING: runs arbitrary Rhino commands."""
    return _call("run_rhino_command", command=command, echo=echo)


@mcp.tool()
def execute_python(code: str) -> Any:
    """Execute IronPython 2.7 code inside Rhino 7 (NOT Python 3: no f-strings,
    use print(...) with `from __future__ import print_function` if needed).
    Available names: rs (rhinoscriptsyntax), sc (scriptcontext), Rhino, System,
    doc (active RhinoDoc), math, json. Printed output is returned; assign to a
    variable named `result` to return a value (Guids/points/colors are
    serialized). Runs on the UI thread inside one undo step.
    WARNING: arbitrary code execution."""
    return _call("execute_python", code=code)


@mcp.tool()
def capture_viewport(view: str | None = None, width: int = 800, height: int = 600,
                     display_mode: str | None = None) -> Image:
    """Capture a viewport as a PNG image. `view` is a viewport name such as
    "Perspective", "Top", "Front" (default: active view). `display_mode` e.g.
    "Wireframe", "Shaded", "Rendered", "Ghosted" (restored afterwards). Use this
    to verify your modeling results visually."""
    res = _call("capture_viewport", view=view, width=width, height=height,
                display_mode=display_mode)
    return Image(data=base64.b64decode(res["image_base64"]), format="png")


@mcp.tool()
def zoom_extents(view: str | None = None, all_views: bool = False) -> Any:
    """Zoom the given view (default: active) or all views to show all objects."""
    return _call("zoom_extents", view=view, all_views=all_views)


@mcp.tool()
def undo(steps: int = 1) -> Any:
    """Undo the last N steps in Rhino."""
    return _call("undo", steps=steps)


# ---------------------------------------------------------------------------
# Prompt
# ---------------------------------------------------------------------------

@mcp.prompt()
def rhino_modeling_workflow() -> str:
    """Short guide for modeling in Rhino 7 through this server."""
    return (
        "You control Rhino 7 through MCP tools. Workflow:\n"
        "1. Call get_document_info first: check units, tolerance and existing layers/objects.\n"
        "2. Organize with layers: create_layer, then pass layer=... to create_object.\n"
        "3. Build geometry step by step (create_object, transform_objects, boolean_operation); "
        "give objects meaningful names.\n"
        "4. Object ids can change after transform/boolean: always use the ids returned.\n"
        "5. After significant steps call zoom_extents and capture_viewport to verify visually; "
        "use get_object_info for numbers (volume, length).\n"
        "6. Prefer the dedicated tools; use execute_python (IronPython 2.7, rs/Rhino available) "
        "or run_rhino_command only when they are not enough.\n"
        "7. Every change is one undo step: use undo if something went wrong."
    )


def main() -> None:
    mcp.run()


if __name__ == "__main__":
    main()

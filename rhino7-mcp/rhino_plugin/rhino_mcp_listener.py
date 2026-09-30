# -*- coding: utf-8 -*-
"""Rhino 7 MCP listener (IronPython 2.7).

Run this script INSIDE Rhino 7 (command _RunPythonScript, or EditPythonScript
-> Run).  It starts a TCP server on 127.0.0.1:1999 in a background thread.
Running the script again while the server is active STOPS it (toggle).

Protocol: newline-delimited JSON, UTF-8.
  request : {"id": "...", "command": "name", "params": {...}}\\n
  response: {"id": "...", "status": "ok", "result": ...}\\n
         or {"id": "...", "status": "error", "message": "..."}\\n

All RhinoCommon document access is marshalled to the Rhino UI thread.
Code must stay valid Python 2.7 (IronPython): no f-strings, no annotations.
"""
from __future__ import print_function

import base64  # noqa: F401  (kept for clarity; base64 is done with System.Convert)
import json
import math
import socket
import sys
import threading
import traceback

try:
    from StringIO import StringIO
except ImportError:  # pragma: no cover (Python 3, only for py_compile / tests)
    from io import StringIO

import System
import System.Drawing
import Rhino
import scriptcontext as sc
import rhinoscriptsyntax as rs

HOST = "127.0.0.1"
PORT = 1999
UI_TIMEOUT = 60.0
STICKY_KEY = "rhino_mcp_listener_server"
LISTENER_VERSION = "1.0.0"

try:
    _STR = basestring  # noqa: F821
except NameError:
    _STR = str
try:
    _INTS = (int, long)  # noqa: F821
except NameError:
    _INTS = (int,)


def log(msg):
    try:
        Rhino.RhinoApp.WriteLine("[rhino-mcp] " + str(msg))
    except Exception:
        pass
    print("[rhino-mcp] " + str(msg))


# ---------------------------------------------------------------------------
# Serialization helpers
# ---------------------------------------------------------------------------

def pt(p):
    return [p.X, p.Y, p.Z]


def col(c):
    return [c.R, c.G, c.B]


def gid(g):
    return str(g)


def bbox_to_json(bb):
    try:
        if not bb.IsValid:
            return None
        return {"min": pt(bb.Min), "max": pt(bb.Max)}
    except Exception:
        return None


def js(v):
    """Convert (nearly) anything into something json.dumps can handle."""
    if v is None or isinstance(v, bool):
        return v
    if isinstance(v, _INTS):
        return v
    if isinstance(v, float):
        if v != v or v in (float("inf"), float("-inf")):
            return None
        return v
    if isinstance(v, _STR):
        return v
    if isinstance(v, System.Guid):
        return str(v)
    if isinstance(v, (Rhino.Geometry.Point3d, Rhino.Geometry.Vector3d)):
        return pt(v)
    if isinstance(v, System.Drawing.Color):
        return col(v)
    if isinstance(v, Rhino.Geometry.BoundingBox):
        return bbox_to_json(v)
    if isinstance(v, dict):
        return dict((str(k), js(x)) for k, x in v.items())
    if isinstance(v, (list, tuple, set)):
        return [js(x) for x in v]
    try:
        if isinstance(v, System.Collections.IEnumerable):
            return [js(x) for x in v]
    except Exception:
        pass
    return str(v)


def to_pt(v):
    if v is None or len(v) < 2:
        raise ValueError("A point must be [x, y] or [x, y, z], got: %r" % (v,))
    z = float(v[2]) if len(v) > 2 else 0.0
    return Rhino.Geometry.Point3d(float(v[0]), float(v[1]), z)


def to_vec(v):
    p = to_pt(v)
    return Rhino.Geometry.Vector3d(p.X, p.Y, p.Z)


def to_color(v):
    if v is None or len(v) < 3:
        raise ValueError("A color must be [r, g, b], got: %r" % (v,))
    return System.Drawing.Color.FromArgb(int(v[0]), int(v[1]), int(v[2]))


def to_guid(s):
    try:
        return System.Guid(str(s))
    except Exception:
        raise ValueError("Invalid object id: %r" % (s,))


def need(params, key):
    if key not in params or params[key] is None:
        raise ValueError("Missing required parameter: %s" % key)
    return params[key]


def get_doc():
    doc = Rhino.RhinoDoc.ActiveDoc
    if doc is None:
        raise RuntimeError("There is no active Rhino document.")
    sc.doc = doc
    return doc


# ---------------------------------------------------------------------------
# Document helpers
# ---------------------------------------------------------------------------

def iter_objects(doc, include_hidden=True):
    s = Rhino.DocObjects.ObjectEnumeratorSettings()
    s.NormalObjects = True
    s.LockedObjects = True
    s.HiddenObjects = include_hidden
    s.DeletedObjects = False
    return list(doc.Objects.GetObjectList(s))


def find_object(doc, id_str):
    obj = doc.Objects.FindId(to_guid(id_str))
    if obj is None:
        raise ValueError("Object not found: %s" % id_str)
    return obj


def find_objects(doc, ids):
    if not ids:
        raise ValueError("'ids' must be a non-empty list of object ids.")
    return [find_object(doc, i) for i in ids]


def layer_path(doc, index):
    try:
        layer = doc.Layers[index]
        try:
            return layer.FullPath
        except Exception:
            return layer.Name
    except Exception:
        return None


def find_layer_index(doc, name):
    """Layer index by full path or name (case-insensitive), or -1."""
    low = str(name).lower()
    for layer in doc.Layers:
        if layer.IsDeleted:
            continue
        full = layer.Name
        try:
            full = layer.FullPath
        except Exception:
            pass
        if full.lower() == low:
            return layer.Index
    for layer in doc.Layers:
        if not layer.IsDeleted and layer.Name.lower() == low:
            return layer.Index
    return -1


def ensure_layer(doc, name):
    idx = find_layer_index(doc, name)
    if idx >= 0:
        return idx
    layer = Rhino.DocObjects.Layer()
    layer.Name = str(name)
    idx = doc.Layers.Add(layer)
    if idx < 0:
        raise RuntimeError("Could not create layer: %s" % name)
    return idx


def object_color(doc, obj):
    try:
        return col(obj.Attributes.DrawColor(doc))
    except Exception:
        try:
            return col(obj.Attributes.ObjectColor)
        except Exception:
            return None


def object_type_name(obj):
    return str(obj.ObjectType)


def summary(doc, obj):
    return {
        "id": gid(obj.Id),
        "name": obj.Attributes.Name or "",
        "type": object_type_name(obj),
        "layer": layer_path(doc, obj.Attributes.LayerIndex),
        "color": object_color(doc, obj),
        "bbox": bbox_to_json(obj.Geometry.GetBoundingBox(True)),
    }


def union_bbox(objs):
    bb = Rhino.Geometry.BoundingBox.Unset
    for o in objs:
        b = o.Geometry.GetBoundingBox(True)
        if not b.IsValid:
            continue
        bb = b if not bb.IsValid else Rhino.Geometry.BoundingBox.Union(bb, b)
    return bb


def to_brep(geom):
    if isinstance(geom, Rhino.Geometry.Brep):
        return geom
    if isinstance(geom, Rhino.Geometry.Extrusion):
        return geom.ToBrep()
    if isinstance(geom, Rhino.Geometry.Surface):
        return geom.ToBrep()
    return None


def apply_attributes(doc, obj, name=None, layer=None, color=None, user_text=None):
    attrs = obj.Attributes.Duplicate()
    if name is not None:
        attrs.Name = str(name)
    if layer is not None:
        attrs.LayerIndex = ensure_layer(doc, layer)
    if color is not None:
        attrs.ObjectColor = to_color(color)
        attrs.ColorSource = Rhino.DocObjects.ObjectColorSource.ColorFromObject
    if user_text:
        for k, v in user_text.items():
            attrs.SetUserString(str(k), str(v))
    doc.Objects.ModifyAttributes(obj, attrs, True)


# ---------------------------------------------------------------------------
# UI-thread marshalling
# ---------------------------------------------------------------------------

def run_on_ui(fn, timeout=UI_TIMEOUT):
    """Run fn() on the Rhino UI thread; return its value or raise its error."""
    box = {}
    done = threading.Event()

    def wrapper():
        try:
            box["result"] = fn()
        except Exception as ex:
            box["error"] = "%s: %s" % (ex.__class__.__name__, ex)
            box["tb"] = traceback.format_exc()
        finally:
            done.set()

    Rhino.RhinoApp.InvokeOnUiThread(System.Action(wrapper))
    done.wait(timeout)
    if not done.is_set():
        raise RuntimeError("Timed out after %s s waiting for the Rhino UI thread "
                           "(is a command or dialog blocking Rhino?)." % timeout)
    if "error" in box:
        raise RuntimeError(box["error"] + "\n" + box["tb"])
    return box.get("result")


# ---------------------------------------------------------------------------
# Commands.  Each handler is fn(doc, params) -> JSON-able value.
# ---------------------------------------------------------------------------

COMMANDS = {}
MUTATING = set()


def command(name, mutating=False):
    def deco(fn):
        COMMANDS[name] = fn
        if mutating:
            MUTATING.add(name)
        return fn
    return deco


@command("get_document_info")
def cmd_get_document_info(doc, params):
    objs = iter_objects(doc)
    counts = {}
    for o in objs:
        i = o.Attributes.LayerIndex
        counts[i] = counts.get(i, 0) + 1
    layers = []
    for layer in doc.Layers:
        if layer.IsDeleted:
            continue
        layers.append({"name": layer_path(doc, layer.Index), "color": col(layer.Color),
                       "object_count": counts.get(layer.Index, 0)})
    return {
        "name": doc.Name,
        "path": doc.Path,
        "units": str(doc.ModelUnitSystem),
        "tolerance": doc.ModelAbsoluteTolerance,
        "angle_tolerance_degrees": doc.ModelAngleToleranceDegrees,
        "object_count": len(objs),
        "current_layer": layer_path(doc, doc.Layers.CurrentLayerIndex),
        "layers": layers,
        "bbox": bbox_to_json(union_bbox(objs)),
    }


_TYPE_ALIASES = {"polysurface": "brep", "text": "annotation", "solid": "brep",
                 "line": "curve", "polyline": "curve", "circle": "curve", "arc": "curve"}


@command("get_objects")
def cmd_get_objects(doc, params):
    limit = int(params.get("limit") or 200)
    layer = params.get("layer")
    otype = params.get("object_type")
    name = params.get("name")
    if params.get("selected_only"):
        objs = list(doc.Objects.GetSelectedObjects(False, False))
    else:
        objs = iter_objects(doc)
    if otype:
        t = str(otype).lower()
        t = _TYPE_ALIASES.get(t, t)
        objs = [o for o in objs if object_type_name(o).lower() == t]
    if layer:
        low = str(layer).lower()
        objs = [o for o in objs if (layer_path(doc, o.Attributes.LayerIndex) or "").lower() == low]
    if name:
        low = str(name).lower()
        objs = [o for o in objs if (o.Attributes.Name or "").lower() == low]
    total = len(objs)
    return {"total_matching": total, "returned": min(total, limit),
            "objects": [summary(doc, o) for o in objs[:limit]]}


def geometry_details(geom):
    d = {}
    G = Rhino.Geometry
    if isinstance(geom, G.Point):
        d["point"] = pt(geom.Location)
    elif isinstance(geom, G.Curve):
        d["start"] = pt(geom.PointAtStart)
        d["end"] = pt(geom.PointAtEnd)
        d["length"] = geom.GetLength()
        d["closed"] = geom.IsClosed
        d["planar"] = geom.IsPlanar()
        d["degree"] = geom.Degree
        try:
            ok, circle = geom.TryGetCircle()
            if ok:
                d["circle"] = {"center": pt(circle.Center), "radius": circle.Radius,
                               "normal": pt(circle.Plane.Normal)}
        except Exception:
            pass
        try:
            if isinstance(geom, G.PolylineCurve):
                d["point_count"] = geom.PointCount
        except Exception:
            pass
    elif isinstance(geom, (G.Brep, G.Extrusion, G.Surface)):
        brep = to_brep(geom)
        if brep is not None:
            d["is_solid"] = brep.IsSolid
            d["face_count"] = brep.Faces.Count
            d["is_valid"] = brep.IsValid
            amp = G.AreaMassProperties.Compute(brep)
            if amp is not None:
                d["area"] = amp.Area
            if brep.IsSolid:
                vmp = G.VolumeMassProperties.Compute(brep)
                if vmp is not None:
                    d["volume"] = vmp.Volume
                    d["centroid"] = pt(vmp.Centroid)
    elif isinstance(geom, G.Mesh):
        d["vertex_count"] = geom.Vertices.Count
        d["face_count"] = geom.Faces.Count
        d["closed"] = geom.IsClosed
    else:
        try:
            d["text"] = geom.PlainText
        except Exception:
            pass
    return d


@command("get_object_info")
def cmd_get_object_info(doc, params):
    obj = find_object(doc, need(params, "id"))
    info = summary(doc, obj)
    info["geometry_class"] = obj.Geometry.GetType().Name
    info["visible"] = obj.Visible
    info["locked"] = obj.IsLocked
    info["selected"] = obj.IsSelected(False) != 0
    info["geometry"] = geometry_details(obj.Geometry)
    ut = {}
    coll = obj.Attributes.GetUserStrings()
    if coll is not None:
        for k in coll.AllKeys:
            ut[str(k)] = str(coll[k])
    info["user_text"] = ut
    return info


@command("get_selected_objects")
def cmd_get_selected_objects(doc, params):
    objs = list(doc.Objects.GetSelectedObjects(False, False))
    return {"count": len(objs), "objects": [summary(doc, o) for o in objs]}


def _plane(origin, normal):
    if normal is None:
        return Rhino.Geometry.Plane(origin, Rhino.Geometry.Vector3d.ZAxis)
    return Rhino.Geometry.Plane(origin, to_vec(normal))


def _grid_points(params):
    pts = need(params, "points")
    if pts and isinstance(pts[0][0], (list, tuple)):
        rows = pts
        u_count, v_count = len(rows), len(rows[0])
        flat = [p for row in rows for p in row]
    else:
        flat = pts
        u_count = int(need(params, "u_count"))
        v_count = int(need(params, "v_count"))
    if u_count * v_count != len(flat):
        raise ValueError("points count (%d) != u_count*v_count (%d)" % (len(flat), u_count * v_count))
    return flat, u_count, v_count


@command("create_object", mutating=True)
def cmd_create_object(doc, params):
    """Create geometry.  params: type + type-specific keys (see server docs)."""
    G = Rhino.Geometry
    t = str(need(params, "type")).lower()
    o = doc.Objects
    if t == "point":
        g = o.AddPoint(to_pt(need(params, "point")))
    elif t == "line":
        g = o.AddLine(to_pt(need(params, "start")), to_pt(need(params, "end")))
    elif t == "polyline":
        pts = [to_pt(p) for p in need(params, "points")]
        if len(pts) < 2:
            raise ValueError("polyline needs at least 2 points")
        if params.get("closed") and pts[0].DistanceTo(pts[-1]) > 1e-12:
            pts.append(pts[0])
        lst = System.Collections.Generic.List[G.Point3d]()
        for p in pts:
            lst.Add(p)
        g = o.AddPolyline(lst)
    elif t == "circle":
        plane = _plane(to_pt(need(params, "center")), params.get("normal"))
        g = o.AddCircle(G.Circle(plane, float(need(params, "radius"))))
    elif t == "arc":
        if params.get("points"):
            p = params["points"]
            if len(p) != 3:
                raise ValueError("arc 'points' must be [start, through, end]")
            arc = G.Arc(to_pt(p[0]), to_pt(p[1]), to_pt(p[2]))
        else:
            plane = _plane(to_pt(need(params, "center")), params.get("normal"))
            circle = G.Circle(plane, float(need(params, "radius")))
            a0 = math.radians(float(params.get("start_angle_degrees", 0.0)))
            a1 = math.radians(float(need(params, "end_angle_degrees")))
            arc = G.Arc(circle, G.Interval(a0, a1))
        if not arc.IsValid:
            raise ValueError("Invalid arc parameters")
        g = o.AddArc(arc)
    elif t == "rectangle":
        c = to_pt(need(params, "corner"))
        w = float(need(params, "width"))
        h = float(need(params, "height"))
        pl = G.Plane(c, G.Vector3d.XAxis, G.Vector3d.YAxis)
        if params.get("normal") is not None:
            pl = G.Plane(c, to_vec(params["normal"]))
        pts = [c, pl.PointAt(w, 0), pl.PointAt(w, h), pl.PointAt(0, h), c]
        lst = System.Collections.Generic.List[G.Point3d]()
        for p in pts:
            lst.Add(p)
        g = o.AddPolyline(lst)
    elif t == "box":
        c = to_pt(need(params, "corner"))
        pl = G.Plane(c, G.Vector3d.XAxis, G.Vector3d.YAxis)
        box = G.Box(pl, G.Interval(0, float(need(params, "width"))),
                    G.Interval(0, float(need(params, "depth"))),
                    G.Interval(0, float(need(params, "height"))))
        g = o.AddBrep(box.ToBrep())
    elif t == "sphere":
        sph = G.Sphere(to_pt(need(params, "center")), float(need(params, "radius")))
        g = o.AddBrep(G.Brep.CreateFromSphere(sph))
    elif t == "cylinder":
        plane = _plane(to_pt(need(params, "base")), params.get("normal"))
        circle = G.Circle(plane, float(need(params, "radius")))
        cyl = G.Cylinder(circle, float(need(params, "height")))
        g = o.AddBrep(cyl.ToBrep(bool(params.get("cap", True)), bool(params.get("cap", True))))
    elif t == "cone":
        # RhinoCommon cones: Plane.Origin is the apex and the base sits at
        # Origin + Height * ZAxis, so build the plane at the apex pointing down.
        base = to_pt(need(params, "base"))
        height = float(need(params, "height"))
        axis = to_vec(params.get("normal")) if params.get("normal") is not None else G.Vector3d.ZAxis
        axis.Unitize()
        apex = base + axis * height
        cone = G.Cone(G.Plane(apex, -axis), height, float(need(params, "radius")))
        g = o.AddBrep(G.Brep.CreateFromCone(cone, bool(params.get("cap", True))))
    elif t == "surface_from_points":
        flat, u, v = _grid_points(params)
        pts = System.Collections.Generic.List[G.Point3d]()
        for p in flat:
            pts.Add(to_pt(p))
        ud = int(params.get("u_degree") or min(3, u - 1))
        vd = int(params.get("v_degree") or min(3, v - 1))
        srf = G.NurbsSurface.CreateFromPoints(pts, u, v, ud, vd)
        if srf is None:
            raise ValueError("Could not create a surface from those points")
        g = o.AddSurface(srf)
    elif t == "text":
        g = rs.AddText(str(need(params, "text")), to_pt(need(params, "point")),
                       float(params.get("height", 1.0)), str(params.get("font", "Arial")))
        g = to_guid(g) if g is not None else System.Guid.Empty
    else:
        raise ValueError("Unknown object type: %s" % t)
    if g == System.Guid.Empty:
        raise RuntimeError("Rhino could not add the '%s' object to the document." % t)
    obj = doc.Objects.FindId(g)
    apply_attributes(doc, obj, params.get("name"), params.get("layer"), params.get("color"))
    return {"id": gid(g)}


@command("delete_objects", mutating=True)
def cmd_delete_objects(doc, params):
    ids = need(params, "ids")
    n = 0
    for i in ids:
        if doc.Objects.Delete(to_guid(i), True):
            n += 1
    return {"deleted": n, "requested": len(ids)}


@command("transform_objects", mutating=True)
def cmd_transform_objects(doc, params):
    G = Rhino.Geometry
    ids = need(params, "ids")
    op = str(need(params, "operation")).lower()
    copy = params.get("copy")
    if op == "move" or op == "copy":
        xf = G.Transform.Translation(to_vec(need(params, "vector")))
    elif op == "rotate":
        center = to_pt(params.get("center") or [0, 0, 0])
        axis = to_vec(params.get("axis") or [0, 0, 1])
        xf = G.Transform.Rotation(math.radians(float(need(params, "angle_degrees"))), axis, center)
    elif op == "scale":
        center = to_pt(params.get("center") or [0, 0, 0])
        f = need(params, "scale")
        if isinstance(f, (list, tuple)):
            pl = G.Plane(center, G.Vector3d.XAxis, G.Vector3d.YAxis)
            xf = G.Transform.Scale(pl, float(f[0]), float(f[1]), float(f[2]))
        else:
            xf = G.Transform.Scale(center, float(f))
    elif op == "mirror":
        xf = G.Transform.Mirror(to_pt(need(params, "plane_origin")), to_vec(need(params, "plane_normal")))
    else:
        raise ValueError("operation must be move|copy|rotate|scale|mirror")
    if copy is None:
        copy = (op == "copy")
    result = []
    for i in ids:
        find_object(doc, i)
        new = doc.Objects.Transform(to_guid(i), xf, not copy)
        if new == System.Guid.Empty:
            raise RuntimeError("Transform failed for object %s" % i)
        result.append(gid(new))
    return {"ids": result}


@command("set_object_attributes", mutating=True)
def cmd_set_object_attributes(doc, params):
    ids = need(params, "ids")
    objs = find_objects(doc, ids)
    for obj in objs:
        apply_attributes(doc, obj, params.get("name"), params.get("layer"),
                         params.get("color"), params.get("user_text"))
    return {"updated": len(objs)}


@command("boolean_operation", mutating=True)
def cmd_boolean_operation(doc, params):
    G = Rhino.Geometry
    op = str(need(params, "operation")).lower()
    ids_a = need(params, "ids_a")
    ids_b = params.get("ids_b") or []
    delete_input = params.get("delete_input", True)
    objs_a = find_objects(doc, ids_a)
    objs_b = [find_object(doc, i) for i in ids_b]
    tol = doc.ModelAbsoluteTolerance

    def breps(objs):
        out = []
        for o in objs:
            b = to_brep(o.Geometry)
            if b is None:
                raise ValueError("Object %s is not a surface/polysurface/solid" % gid(o.Id))
            out.append(b)
        return System.Array[G.Brep](out)

    a = breps(objs_a)
    b = breps(objs_b)
    if op == "union":
        allb = System.Array[G.Brep](list(a) + list(b))
        if len(allb) < 2:
            raise ValueError("union needs at least 2 objects")
        res = G.Brep.CreateBooleanUnion(allb, tol)
    elif op == "difference":
        if not len(b):
            raise ValueError("difference needs ids_b")
        res = G.Brep.CreateBooleanDifference(a, b, tol)
    elif op == "intersection":
        if not len(b):
            raise ValueError("intersection needs ids_b")
        res = G.Brep.CreateBooleanIntersection(a, b, tol)
    else:
        raise ValueError("operation must be union|difference|intersection")
    if res is None or len(res) == 0:
        raise RuntimeError("Boolean %s failed. Inputs must be closed, valid solids that "
                           "actually overlap/touch." % op)
    attrs = objs_a[0].Attributes.Duplicate()
    new_ids = [gid(doc.Objects.AddBrep(r, attrs)) for r in res]
    if delete_input:
        for ob in objs_a + objs_b:
            doc.Objects.Delete(ob.Id, True)
    return {"ids": new_ids}


def layer_info(doc, layer):
    parent = None
    if layer.ParentLayerId != System.Guid.Empty:
        pl = doc.Layers.FindId(layer.ParentLayerId)
        parent = pl.FullPath if pl is not None else None
    return {"name": layer_path(doc, layer.Index), "id": gid(layer.Id), "index": layer.Index,
            "color": col(layer.Color), "visible": layer.IsVisible, "locked": layer.IsLocked,
            "parent": parent}


@command("list_layers")
def cmd_list_layers(doc, params):
    cur = doc.Layers.CurrentLayerIndex
    layers = [layer_info(doc, l) for l in doc.Layers if not l.IsDeleted]
    return {"current": layer_path(doc, cur), "layers": layers}


@command("create_layer", mutating=True)
def cmd_create_layer(doc, params):
    name = str(need(params, "name"))
    parent = params.get("parent")
    full = (str(parent) + "::" + name) if parent else name
    existing = find_layer_index(doc, full)
    if existing >= 0:
        info = layer_info(doc, doc.Layers[existing])
        info["created"] = False
        return info
    layer = Rhino.DocObjects.Layer()
    layer.Name = name
    if params.get("color"):
        layer.Color = to_color(params["color"])
    if parent:
        pidx = find_layer_index(doc, parent)
        if pidx < 0:
            raise ValueError("Parent layer not found: %s" % parent)
        layer.ParentLayerId = doc.Layers[pidx].Id
    idx = doc.Layers.Add(layer)
    if idx < 0:
        raise RuntimeError("Could not create layer %s" % full)
    info = layer_info(doc, doc.Layers[idx])
    info["created"] = True
    return info


@command("set_current_layer")
def cmd_set_current_layer(doc, params):
    name = need(params, "name")
    idx = find_layer_index(doc, name)
    if idx < 0:
        raise ValueError("Layer not found: %s" % name)
    doc.Layers.SetCurrentLayerIndex(idx, True)
    return {"current": layer_path(doc, idx)}


@command("select_objects")
def cmd_select_objects(doc, params):
    ids = need(params, "ids")
    if params.get("clear_existing", True):
        doc.Objects.UnselectAll()
    n = 0
    for i in ids:
        if doc.Objects.Select(to_guid(i)):
            n += 1
    return {"selected": n, "requested": len(ids)}


@command("run_rhino_command")
def cmd_run_rhino_command(doc, params):
    cmd = str(need(params, "command"))
    echo = bool(params.get("echo", True))
    ok = Rhino.RhinoApp.RunScript(cmd, echo)
    return {"success": bool(ok), "command": cmd}


@command("execute_python", mutating=True)
def cmd_execute_python(doc, params):
    code = need(params, "code")
    ns = {"rs": rs, "sc": sc, "Rhino": Rhino, "System": System, "doc": doc,
          "math": math, "json": json, "__name__": "rhino_mcp_exec"}
    old = sys.stdout
    buf = StringIO()
    sys.stdout = buf
    err = None
    try:
        try:
            exec(code, ns)
        except Exception:
            err = traceback.format_exc()
    finally:
        sys.stdout = old
    output = buf.getvalue()
    if err:
        raise RuntimeError("Script error:\n%s\nOutput before error:\n%s" % (err, output))
    return {"output": output, "result": js(ns.get("result"))}


def _find_view(doc, name):
    if name:
        v = doc.Views.Find(str(name), False)
        if v is None:
            names = [str(x.ActiveViewport.Name) for x in doc.Views.GetViewList(True, False)]
            raise ValueError("View not found: %s (available: %s)" % (name, ", ".join(names)))
        return v
    v = doc.Views.ActiveView
    if v is None:
        raise RuntimeError("No active view")
    return v


@command("capture_viewport")
def cmd_capture_viewport(doc, params):
    view = _find_view(doc, params.get("view"))
    width = int(params.get("width") or 800)
    height = int(params.get("height") or 600)
    vp = view.ActiveViewport
    old_mode = vp.DisplayMode
    mode_name = params.get("display_mode")
    try:
        if mode_name:
            mode = Rhino.Display.DisplayModeDescription.FindByName(str(mode_name))
            if mode is None:
                raise ValueError("Unknown display mode: %s" % mode_name)
            vp.DisplayMode = mode
        bmp = view.CaptureToBitmap(System.Drawing.Size(width, height))
        if bmp is None:
            raise RuntimeError("CaptureToBitmap returned nothing")
        ms = System.IO.MemoryStream()
        try:
            bmp.Save(ms, System.Drawing.Imaging.ImageFormat.Png)
            b64 = System.Convert.ToBase64String(ms.ToArray())
        finally:
            ms.Dispose()
            bmp.Dispose()
    finally:
        if mode_name:
            vp.DisplayMode = old_mode
    return {"image_base64": b64, "width": width, "height": height, "view": vp.Name}


@command("zoom_extents")
def cmd_zoom_extents(doc, params):
    if params.get("all_views"):
        views = list(doc.Views.GetViewList(True, False))
    else:
        views = [_find_view(doc, params.get("view"))]
    for v in views:
        v.ActiveViewport.ZoomExtents()
        v.Redraw()
    return {"views": len(views)}


@command("undo")
def cmd_undo(doc, params):
    steps = int(params.get("steps") or 1)
    for _ in range(steps):
        Rhino.RhinoApp.RunScript("_Undo", False)
    return {"undone": steps}


def _ui_execute(name, params):
    doc = get_doc()
    handler = COMMANDS[name]
    if name in MUTATING:
        sn = doc.BeginUndoRecord("MCP: " + name)
        try:
            return handler(doc, params)
        finally:
            doc.EndUndoRecord(sn)
            doc.Views.Redraw()
    result = handler(doc, params)
    doc.Views.Redraw()
    return result


def dispatch(request):
    """Turn a request dict into a response dict. Never raises."""
    rid = request.get("id") if isinstance(request, dict) else None
    try:
        if not isinstance(request, dict):
            raise ValueError("Request must be a JSON object")
        name = request.get("command")
        params = request.get("params") or {}
        if name == "ping":
            try:
                ver = str(Rhino.RhinoApp.Version)
            except Exception:
                ver = None
            return {"id": rid, "status": "ok",
                    "result": {"pong": True, "rhino_version": ver, "listener_version": LISTENER_VERSION}}
        if name not in COMMANDS:
            raise ValueError("Unknown command: %s. Available: ping, %s" % (name, ", ".join(sorted(COMMANDS))))
        result = run_on_ui(lambda: js(_ui_execute(name, params)))
        return {"id": rid, "status": "ok", "result": result}
    except Exception as ex:
        return {"id": rid, "status": "error", "message": str(ex)}


# ---------------------------------------------------------------------------
# TCP server
# ---------------------------------------------------------------------------

class McpServer(object):
    def __init__(self, host, port):
        self.host = host
        self.port = port
        self.running = False
        self.sock = None
        self.thread = None
        self.clients = []
        self.lock = threading.Lock()

    def start(self):
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        s.bind((self.host, self.port))
        s.listen(5)
        s.settimeout(1.0)
        self.sock = s
        self.running = True
        self.thread = threading.Thread(target=self._accept_loop)
        self.thread.daemon = True
        self.thread.start()

    def stop(self):
        self.running = False
        try:
            if self.sock is not None:
                self.sock.close()
        except Exception:
            pass
        with self.lock:
            clients = list(self.clients)
        for c in clients:
            try:
                c.close()
            except Exception:
                pass

    def _accept_loop(self):
        while self.running:
            try:
                conn, addr = self.sock.accept()
            except socket.timeout:
                continue
            except Exception:
                if self.running:
                    log("accept error: " + traceback.format_exc())
                break
            t = threading.Thread(target=self._client_loop, args=(conn,))
            t.daemon = True
            t.start()

    def _client_loop(self, conn):
        with self.lock:
            self.clients.append(conn)
        conn.settimeout(1.0)
        buf = b""
        try:
            while self.running:
                try:
                    data = conn.recv(65536)
                except socket.timeout:
                    continue
                if not data:
                    break
                buf += data
                while b"\n" in buf:
                    line, buf = buf.split(b"\n", 1)
                    if not line.strip():
                        continue
                    self._handle_line(conn, line)
        except Exception:
            if self.running:
                log("client error: " + traceback.format_exc())
        finally:
            with self.lock:
                if conn in self.clients:
                    self.clients.remove(conn)
            try:
                conn.close()
            except Exception:
                pass

    def _handle_line(self, conn, line):
        try:
            text = line if isinstance(line, _STR) and not isinstance(line, bytes) else line.decode("utf-8")
            request = json.loads(text)
            response = dispatch(request)
        except Exception as ex:
            response = {"id": None, "status": "error", "message": "Bad request: %s" % ex}
        try:
            out = json.dumps(response) + "\n"
            if not isinstance(out, bytes):
                out = out.encode("utf-8")
            conn.sendall(out)
        except Exception:
            # response could not be serialized/sent
            try:
                fallback = json.dumps({"id": response.get("id"), "status": "error",
                                       "message": "Could not serialize response"}) + "\n"
                conn.sendall(fallback.encode("utf-8") if not isinstance(fallback, bytes) else fallback)
            except Exception:
                pass


def main():
    existing = sc.sticky.get(STICKY_KEY)
    if existing is not None and existing.running:
        existing.stop()
        del sc.sticky[STICKY_KEY]
        log("Listener was RUNNING on %s:%s -> now STOPPED. Run the script again to start it." %
            (existing.host, existing.port))
        return
    if existing is not None:
        del sc.sticky[STICKY_KEY]
    server = McpServer(HOST, PORT)
    try:
        server.start()
    except Exception as ex:
        log("Could not start listener on %s:%s: %s (is the port already in use?)" % (HOST, PORT, ex))
        return
    sc.sticky[STICKY_KEY] = server
    log("Listener STARTED on %s:%s. Run this script again to stop it." % (HOST, PORT))


if __name__ == "__main__":
    main()

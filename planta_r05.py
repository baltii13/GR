"""Planta tipo de un nucleo (R-05.01) y su insercion en la pagina 14 de la Entrega 1.

Uso: python planta_r05.py Entrega1_R05_AnderAlfaro.pdf [salida.pdf]
"""
import sys
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.patches import Rectangle, Arc

GREEN, BG, ACC = "#1e3b2f", "#f4f6f4", "#b08d3c"
BOX = (43, 159, 606, 259)            # hueco de la pagina 14 (x, y, ancho, alto) en pt
EXT, INT = 2.4, 0.9

fig = plt.figure(figsize=(BOX[2] / 72, BOX[3] / 72), facecolor=BG)
ax = fig.add_axes([0, 0, 1, 1]); ax.set_facecolor(BG)
ax.set_xlim(-1.6, 42.4); ax.set_ylim(-3.3, 15.5); ax.set_aspect("equal"); ax.axis("off")

GAL = 1.6                       # galeria abierta al jardin
Y_TOP = 13.6                    # fachada a calle
Y_DAY, Y_MID, Y_COR = 9.6, 7.2, 6.1   # limites de bandas


def wall(x0, y0, x1, y1, lw=INT):
    ax.plot([x0, x1], [y0, y1], color="k", lw=lw, solid_capstyle="projecting", zorder=2)


def gap(x, y, vertical, w):
    r = (x - 0.13, y - w / 2, 0.26, w) if vertical else (x - w / 2, y - 0.13, w, 0.26)
    ax.add_patch(Rectangle(r[:2], r[2], r[3], color="w", zorder=3))


def door(x, y, vertical, w=0.8, s=1):
    gap(x, y, vertical, w)
    if vertical:
        ax.plot([x, x + s * w], [y - w / 2] * 2, "k", lw=0.5, zorder=4)
        ax.add_patch(Arc((x, y - w / 2), 2 * w, 2 * w, theta1=0 if s > 0 else 90, theta2=90 if s > 0 else 180, lw=0.35, zorder=4))
    else:
        ax.plot([x - w / 2] * 2, [y, y + s * w], "k", lw=0.5, zorder=4)
        ax.add_patch(Arc((x - w / 2, y), 2 * w, 2 * w, theta1=0 if s > 0 else 270, theta2=90 if s > 0 else 360, lw=0.35, zorder=4))


def window(x, y, w):
    ax.add_patch(Rectangle((x - w / 2, y - 0.14), w, 0.28, fc="w", ec="k", lw=0.4, zorder=3))
    ax.plot([x - w / 2, x + w / 2], [y, y], "k", lw=0.3, zorder=4)


def txt(x, y, s, size=4.6, **kw):
    ax.text(x, y, s, ha="center", va="center", fontsize=size, zorder=5, **kw)


def unit(tag, m2, x0, w, ybot, dorms, wet, access_left, d4=None, terr=10):
    x1 = x0 + w
    ax.add_patch(Rectangle((x0, ybot), w, Y_TOP - ybot, color="w", zorder=0))
    for a, b, c, d in [(x0, ybot, x1, ybot), (x0, Y_TOP, x1, Y_TOP)]:
        wall(a, b, c, d, EXT)
    wall(x0, ybot, x0, Y_TOP, 1.8); wall(x1, ybot, x1, Y_TOP, 1.8)
    wall(x0, Y_DAY, x1, Y_DAY); wall(x0, Y_MID, x1, Y_MID); wall(x0, Y_COR, x1, Y_COR)
    # banda noche (jardin): dormitorios + acceso
    u = x0
    for i, (n, dw) in enumerate(dorms):
        if i: wall(u, ybot, u, Y_COR)
        cx = u + dw / 2
        if n == "acc":
            ent_x = cx
        else:
            txt(cx, (ybot + Y_COR) / 2, n, weight="bold")
            window(cx, ybot, min(1.4, dw - 0.6))
            door(cx, Y_COR, False, 0.75, -1)
        u += dw
    # entrada
    if ybot > 0:
        door(ent_x, ybot, False, 0.9, 1)
    else:
        door(x0 if access_left else x1, GAL / 2 + 0.1, True, 0.9, 1 if access_left else -1)
    txt(ent_x, (ybot + Y_COR) / 2 + (0 if ybot > 0 else -0.6), "Acceso", 4, style="italic", rotation=90)
    txt((x0 + x1) / 2, (Y_COR + Y_MID) / 2, "Paso", 4, style="italic", color="#555")
    # banda humeda
    u = x0
    for i, (n, dw) in enumerate(wet):
        if i: wall(u, Y_MID, u, Y_DAY)
        txt(u + dw / 2, (Y_MID + Y_DAY) / 2, n, 4.2)
        if n == "Recibidor":
            gap(u + dw / 2, Y_MID, False, min(1.4, dw - 0.3)); gap(u + dw / 2, Y_DAY, False, min(1.2, dw - 0.3))
        else:
            door(u + dw / 2, Y_MID, False, 0.65, 1)
        u += dw
    # banda dia (calle)
    ew = w - (d4 or 0)
    ex0 = x0 if not d4 or not access_left else x0 + d4
    if d4:
        dx = x0 if access_left else x1 - d4
        wall(dx + (d4 if not access_left else 0) if False else (x1 - d4 if not access_left else x0 + d4), Y_DAY, x1 - d4 if not access_left else x0 + d4, Y_TOP)
        txt(dx + d4 / 2, (Y_DAY + Y_TOP) / 2, "Dorm. 4", weight="bold")
        window(dx + d4 / 2, Y_TOP, 1.4)
        door(dx + d4 / 2, Y_DAY, False, 0.75, 1)
    txt(ex0 + ew / 2, (Y_DAY + Y_TOP) / 2 + 0.3, "Estar-comedor-cocina", weight="bold")
    ax.add_patch(Rectangle((ex0 + 0.3, Y_DAY + 0.15), min(3.2, ew - 0.6), 0.65, fc="none", ec="k", lw=0.4, zorder=3))
    window(ex0 + ew / 2, Y_TOP, ew - 1.2)
    # terraza en voladizo a calle
    tw = min(terr / 1.5, ew - 0.4)
    ax.add_patch(Rectangle((ex0 + (ew - tw) / 2, Y_TOP), tw, 1.5, fc="#e3e9e5", ec=GREEN, lw=0.6, hatch="////", zorder=1))
    txt(ex0 + ew / 2, Y_TOP + 0.75, f"Terraza {terr} m²", 4, color=GREEN, bbox=dict(fc="#e3e9e5", ec="none", pad=0.4))
    # etiqueta
    txt((x0 + x1) / 2, -0.95 if ybot > 0 else -0.95, f"{tag}", 6.2, weight="bold", color=GREEN)
    txt((x0 + x1) / 2, -1.75, f"{m2} m² útiles · {w:.1f} m".replace(".", ","), 4.6, color=GREEN)


# viviendas: 2D | 3D | nucleo | 3D | 4D
unit("2 DORM.", 67, 0.0, 7.3, 0.0,
     [("Dorm. ppal.", 3.5), ("Dorm. 2", 2.6), ("acc", 1.2)],
     [("Baño suite", 1.9), ("Lavadero", 1.5), ("Baño", 1.8), ("Recibidor", 2.1)], access_left=False, terr=10)
unit("3 DORM.", 86, 7.3, 9.0, GAL,
     [("Dorm. 3", 2.5), ("Dorm. 2", 2.7), ("acc", 1.1), ("Dorm. ppal.", 2.7)],
     [("Baño", 1.9), ("Lavadero", 1.6), ("Recibidor", 2.5), ("Baño suite", 3.0)], access_left=False, terr=14)
unit("3 DORM.", 86, 21.3, 9.0, GAL,
     [("Dorm. ppal.", 2.7), ("acc", 1.1), ("Dorm. 2", 2.7), ("Dorm. 3", 2.5)],
     [("Baño suite", 3.0), ("Recibidor", 2.5), ("Lavadero", 1.6), ("Baño", 1.9)], access_left=True, terr=14)
unit("4 DORM.", 102, 30.3, 10.6, 0.0,
     [("acc", 1.2), ("Dorm. ppal.", 3.6), ("Dorm. 2", 3.0), ("Dorm. 3", 2.8)],
     [("Recibidor", 2.2), ("Baño suite", 2.4), ("Lavadero", 1.6), ("Baño", 1.8), ("Aseo", 2.6)],
     access_left=True, d4=2.8, terr=16)

# nucleo
cx0, cx1 = 16.3, 21.3
ax.add_patch(Rectangle((cx0, GAL), cx1 - cx0, Y_TOP - GAL, color="#dfe5e1", zorder=0))
wall(cx0, Y_TOP, cx1, Y_TOP, EXT)
for i in range(16):
    y = 6.2 + i * 0.28
    ax.plot([cx0 + 0.1, cx0 + 1.2], [y, y], "k", lw=0.3); ax.plot([cx0 + 1.4, cx0 + 2.5], [y, y], "k", lw=0.3)
ax.plot([cx0 + 1.3] * 2, [6.2, 10.4], "k", lw=0.6)
wall(cx0 + 2.6, 6.0, cx0 + 2.6, Y_TOP, 1.2); wall(cx0, 6.0, cx0 + 2.6, 6.0, 1.2)
for x in (cx0 + 2.8, cx0 + 3.95):
    ax.add_patch(Rectangle((x, 10.9), 1.05, 2.4, fill=False, lw=0.6))
    ax.plot([x, x + 1.05], [10.9, 13.3], "k", lw=0.3); ax.plot([x, x + 1.05], [13.3, 10.9], "k", lw=0.3)
wall(cx0 + 2.6, 10.8, cx1, 10.8, 1.2)
txt(cx0 + 1.3, 11.9, "Escalera", 4.2, rotation=90)
txt(cx0 + 3.8, 8.0, "Rellano", 4.4, weight="bold")
txt((cx0 + cx1) / 2, 14.3, "NÚCLEO", 5, weight="bold", color=GREEN)

# galeria abierta al jardin
ax.add_patch(Rectangle((7.3, 0), 23.0, GAL, fc="#e8ece9", ec="none", zorder=0))
ax.plot([7.3, 30.3], [0, 0], color=GREEN, lw=0.8, ls=(0, (4, 2)), zorder=2)
txt(18.8, 0.8, "GALERÍA ABIERTA AL JARDÍN", 4.6, weight="bold", color=GREEN)

# rotulos de orientacion
txt(20.4, 15.1 + 0.2, "CALLE  ·  zona de día", 5.2, color="#555", style="italic")
txt(20.4, -2.7, "JARDÍN INTERIOR  ·  zona de noche", 5.2, color="#555", style="italic")

# escala grafica
for i in range(5):
    ax.add_patch(Rectangle((-1.2 + i, -3.0), 1, 0.22, fc="k" if i % 2 == 0 else "w", ec="k", lw=0.4))
txt(1.0, -2.45, "0        5 m", 4)

fig.savefig("planta_r05.pdf", facecolor=BG)
fig.savefig("planta_r05.png", dpi=250, facecolor=BG)

if len(sys.argv) > 1:
    from pypdf import PdfReader, PdfWriter, Transformation
    src = sys.argv[1]
    dst = sys.argv[2] if len(sys.argv) > 2 else src.replace(".pdf", "_con_planta.pdf")
    wtr = PdfWriter(clone_from=src)
    plan = PdfReader("planta_r05.pdf").pages[0]
    wtr.pages[13].merge_transformed_page(plan, Transformation().translate(BOX[0], BOX[1]))
    wtr.compress_identical_objects()
    with open(dst, "wb") as f:
        wtr.write(f)
    print("ok ->", dst)

"""Genera una planta tipo (A4 apaisado, E 1:150) y opcionalmente la anade a un PDF.

Uso:
  python planta_tipo.py                      -> crea planta_tipo.pdf
  python planta_tipo.py entrada.pdf [salida] -> anade la planta al final de entrada.pdf
"""
import sys
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.patches import Rectangle, Arc, FancyArrow

ESC = 150
W, H = 26.0, 14.0          # huella del edificio (m)
YC0, YC1 = 6.0, 8.0         # pasillo comun
EXT, INT = 3.2, 1.3         # grosor de muro (pt)

fig = plt.figure(figsize=(11.69, 8.27))
xl, yl = (-2.5, 28.5), (-3.2, 16.2)
wi = (xl[1] - xl[0]) * 1000 / ESC / 25.4
hi = (yl[1] - yl[0]) * 1000 / ESC / 25.4
ax = fig.add_axes([(11.69 - wi) / 2 / 11.69, 0.20, wi / 11.69, hi / 8.27])
ax.set_xlim(*xl); ax.set_ylim(*yl); ax.set_aspect("equal"); ax.axis("off")


def wall(x0, y0, x1, y1, lw=INT):
    ax.plot([x0, x1], [y0, y1], color="k", lw=lw, solid_capstyle="projecting")


def door(x, y, vertical, w=0.8, swing=1):
    """Hueco con hoja y arco. (x, y) = centro del hueco."""
    if vertical:
        ax.add_patch(Rectangle((x - 0.12, y - w / 2), 0.24, w, color="w", zorder=3))
        ax.plot([x, x + swing * w], [y - w / 2, y - w / 2], "k", lw=0.6, zorder=4)
        ax.add_patch(Arc((x, y - w / 2), 2 * w, 2 * w, theta1=0 if swing > 0 else 90,
                         theta2=90 if swing > 0 else 180, lw=0.4, zorder=4))
    else:
        ax.add_patch(Rectangle((x - w / 2, y - 0.12), w, 0.24, color="w", zorder=3))
        ax.plot([x - w / 2, x - w / 2], [y, y + swing * w], "k", lw=0.6, zorder=4)
        ax.add_patch(Arc((x - w / 2, y), 2 * w, 2 * w, theta1=0 if swing > 0 else 270,
                         theta2=90 if swing > 0 else 360, lw=0.4, zorder=4))


def opening(x, y, vertical, w):
    if vertical:
        ax.add_patch(Rectangle((x - 0.12, y - w / 2), 0.24, w, color="w", zorder=3))
    else:
        ax.add_patch(Rectangle((x - w / 2, y - 0.12), w, 0.24, color="w", zorder=3))


def window(x, y, w, vertical=False):
    if vertical:
        ax.add_patch(Rectangle((x - 0.15, y - w / 2), 0.3, w, fc="w", ec="k", lw=0.5, zorder=3))
        ax.plot([x, x], [y - w / 2, y + w / 2], "k", lw=0.4, zorder=4)
    else:
        ax.add_patch(Rectangle((x - w / 2, y - 0.15), w, 0.3, fc="w", ec="k", lw=0.5, zorder=3))
        ax.plot([x - w / 2, x + w / 2], [y, y], "k", lw=0.4, zorder=4)


def label(x, y, name, area, size=6.5):
    ax.text(x, y + 0.45, name, ha="center", va="center", fontsize=size, weight="bold")
    ax.text(x, y - 0.05, f"{area:.1f} m²", ha="center", va="center", fontsize=size - 1)


def apartment(tag, x_out, x_in, yc, yf, facade, service):
    """facade/service: listas (nombre, ancho) medidas desde el extremo exterior."""
    s = 1 if yf > yc else -1
    ym = yc + s * 2.2
    d = 1 if x_in > x_out else -1
    X = lambda u: x_out + d * u
    wall(X(0), ym, x_in, ym)
    # banda de fachada
    u = 0; rooms_f = []
    for i, (n, w) in enumerate(facade):
        if i: wall(X(u), ym, X(u), yf)
        rooms_f.append((n, u, u + w)); u += w
    # banda de servicio
    u = 0; rooms_s = []
    for i, (n, w) in enumerate(service):
        if i: wall(X(u), yc, X(u), ym)
        rooms_s.append((n, u, u + w)); u += w
    depth_f, depth_s = abs(yf - ym), abs(ym - yc)
    for n, a, b in rooms_f:
        cx = X((a + b) / 2)
        label(cx, (ym + yf) / 2, n, (b - a) * depth_f)
        window(cx, yf, 2.4 if "Sal" in n else 1.5)
    for n, a, b in rooms_s:
        label(X((a + b) / 2), (yc + ym) / 2, n, (b - a) * depth_s, 6)
    hall = next(r for r in rooms_s if r[0] == "Hall")
    # puerta de entrada
    door(X((hall[1] + hall[2]) / 2), yc, False, 0.9, s)
    # puertas / huecos hacia banda de fachada
    for n, a, b in rooms_f:
        lo, hi = max(a, hall[1]) + 0.1, min(b, hall[2]) - 0.1
        if "Sal" in n:
            opening(X((lo + hi) / 2), ym, False, min(1.4, hi - lo))
            k = rooms_s[0]  # cocina abierta al salon
            opening(X((k[1] + k[2]) / 2), ym, False, 1.2)
        elif hi - lo > 0.8:
            door(X((lo + hi) / 2), ym, False, 0.8, s)
    # bano: puerta desde el hall
    bano = next(r for r in rooms_s if r[0].startswith("Ba"))
    door(X(bano[1]), (yc + ym) / 2, True, 0.7, d)
    # etiqueta de vivienda
    tot = sum(w for _, w in facade) * depth_f + sum(w for _, w in service) * depth_s
    ax.text((X(0) + x_in) / 2, yf + s * 0.75, f"VIVIENDA {tag}  ·  3D/1B  ·  {tot:.1f} m² útiles",
            ha="center", va="center", fontsize=7, weight="bold", color="#8a1c1c")


# --- contorno y pasillo
ax.add_patch(Rectangle((0, YC0), W, YC1 - YC0, color="#eeeeee", zorder=0))
for (a, b, c, e) in [(0, 0, W, 0), (W, 0, W, H), (W, H, 0, H), (0, H, 0, 0)]:
    wall(a, b, c, e, EXT)
wall(0, YC0, W, YC0, 2.0); wall(0, YC1, W, YC1, 2.0)
window(0, 7.0, 1.4, True); window(W, 7.0, 1.4, True)
ax.text(W / 2, 7.0, "PASILLO COMÚN", ha="center", va="center", fontsize=7, color="#555")

# --- nucleo de comunicaciones (norte, centro)
cx0, cx1 = 10.5, 15.5
wall(cx0, YC1, cx0, H, 2.0); wall(cx1, YC1, cx1, H, 2.0)
ax.add_patch(Rectangle((cx0, YC1), cx1 - cx0, H - YC1, color="#f6f6f6", zorder=0))
# escalera
sx0, sx1 = cx0, 13.0
wall(sx1, 9.2, sx1, H, 1.6)
for i in range(13):
    y = 9.6 + i * 0.3
    ax.plot([sx0, sx0 + 1.15], [y, y], "k", lw=0.4)
    ax.plot([sx0 + 1.35, sx1], [y, y], "k", lw=0.4)
ax.plot([sx0 + 1.25] * 2, [9.6, 13.2], "k", lw=0.8)
ax.add_patch(FancyArrow(sx0 + 0.6, 9.7, 0, 3.2, width=0.02, head_width=0.25, head_length=0.3, color="k"))
ax.text((sx0 + sx1) / 2, 9.0, "ESCALERA", ha="center", fontsize=6)
# ascensores
for x in (13.1, 14.3):
    ax.add_patch(Rectangle((x, 11.8), 1.1, 1.9, fill=False, lw=0.8))
    ax.plot([x, x + 1.1], [11.8, 13.7], "k", lw=0.4); ax.plot([x, x + 1.1], [13.7, 11.8], "k", lw=0.4)
wall(sx1, 11.7, cx1, 11.7, 1.6)
opening(13.65, 11.7, False, 0.8); opening(14.85, 11.7, False, 0.8)
ax.text(14.25, 10.3, "VESTÍBULO\nASCENSORES", ha="center", va="center", fontsize=6)
opening(11.75, YC1, False, 2.0); opening(14.25, YC1, False, 2.0)

# --- viviendas
apartment("A", 0, cx0, YC1, H, [("Salón-comedor", 4.5), ("Dorm. 2", 3.0), ("Dorm. 3", 3.0)],
          [("Cocina", 2.8), ("Hall", 5.6), ("Baño", 2.1)])
apartment("B", W, cx1, YC1, H, [("Salón-comedor", 4.5), ("Dorm. 2", 3.0), ("Dorm. 3", 3.0)],
          [("Cocina", 2.8), ("Hall", 5.6), ("Baño", 2.1)])
apartment("C", 0, 13, YC0, 0, [("Salón-comedor", 4.5), ("Dorm. 2", 3.5), ("Dorm. principal", 5.0)],
          [("Cocina", 3.0), ("Hall", 7.5), ("Baño", 2.5)])
apartment("D", W, 13, YC0, 0, [("Salón-comedor", 4.5), ("Dorm. 2", 3.5), ("Dorm. principal", 5.0)],
          [("Cocina", 3.0), ("Hall", 7.5), ("Baño", 2.5)])
wall(13, 0, 13, YC0, 2.0)

# --- cotas
def dim(x0, y0, x1, y1, txt, off):
    ax.annotate("", (x0, y0), (x1, y1), arrowprops=dict(arrowstyle="<->", lw=0.5))
    ax.text((x0 + x1) / 2 + (off if x0 == x1 else 0), (y0 + y1) / 2 + (0 if x0 == x1 else off),
            txt, ha="center", va="center", fontsize=6.5, rotation=90 if x0 == x1 else 0)
dim(0, -2.4, W, -2.4, "26,00", 0.35)
dim(0, -1.5, 13, -1.5, "13,00", 0.3); dim(13, -1.5, W, -1.5, "13,00", 0.3)
dim(-1.2, 0, -1.2, H, "14,00", -0.35)
dim(-0.6, 0, -0.6, YC0, "6,00", -0.3); dim(-0.6, YC0, -0.6, YC1, "2,00", -0.3); dim(-0.6, YC1, -0.6, H, "6,00", -0.3)

# --- norte y escala grafica
ax.add_patch(FancyArrow(27.3, 13.0, 0, 1.6, width=0.12, head_width=0.6, head_length=0.6, color="k"))
ax.text(27.3, 12.5, "N", ha="center", fontsize=9, weight="bold")
for i in range(5):
    ax.add_patch(Rectangle((i, -3.7), 1, 0.25, fc="k" if i % 2 == 0 else "w", ec="k", lw=0.5, clip_on=False))
    ax.text(i, -3.2, str(i), ha="center", fontsize=5.5)
ax.text(5, -3.2, "5 m", ha="left", fontsize=5.5)

# --- cajetin
fig.text(0.5, 0.94, "PLANTA TIPO", ha="center", fontsize=18, weight="bold")
fig.text(0.5, 0.905, "Edificio residencial · 4 viviendas por planta · Escala 1:150 (A4)", ha="center", fontsize=9)
fig.text(0.5, 0.06, "Superficie construida por planta: 364,0 m²  ·  Núcleo: escalera + 2 ascensores  ·  "
         "Viviendas A-B: 3D/1B (63,0 m²)  ·  Viviendas C-D: 3D/1B (78,0 m²)", ha="center", fontsize=8)

out_plan = "planta_tipo.pdf"
fig.savefig(out_plan)
fig.savefig("planta_tipo.png", dpi=110)
print("ok ->", out_plan)

if len(sys.argv) > 1:
    from pypdf import PdfReader, PdfWriter
    src = sys.argv[1]
    dst = sys.argv[2] if len(sys.argv) > 2 else src.replace(".pdf", "_con_planta.pdf")
    wtr = PdfWriter()
    for p in PdfReader(src).pages:
        wtr.add_page(p)
    wtr.add_page(PdfReader(out_plan).pages[0])
    with open(dst, "wb") as f:
        wtr.write(f)
    print("ok ->", dst)

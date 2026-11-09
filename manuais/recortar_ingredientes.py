import sys
from collections import deque
from PIL import Image
U = "/root/.claude/uploads/8b2faf80-205e-5959-9f5a-11bbc03e8075/"
F = {5: "a9071552", 6: "0c25ffa3", 7: "d822bba2", 11: "092907ac", 14: "80281d6d", 16: "2e15b54e"}
CROPS = {
    "massa": (5, (130, 985, 985, 1365)),
    "molho": (7, (1160, 195, 1940, 425)),
    "queijo": (11, (95, 805, 755, 1150)),
    "frango": (11, (100, 305, 585, 672)),
    "presunto_ralado": (11, (725, 300, 1370, 640)),
    "carne": (11, (1400, 285, 1895, 660)),
    "bacon": (11, (1305, 870, 1930, 1165)),
    "calabresa": (6, (1625, 420, 1915, 630)),
    "tomate": (6, (120, 680, 375, 795)),
    "cebola": (6, (805, 470, 1140, 630)),
    "cebola_meia_lua": (6, (1190, 725, 1495, 990)),
    "presunto_fatia": (6, (1215, 445, 1505, 650)),
    "champignon": (6, (548, 860, 692, 995)),
    "ovo": (6, (555, 1140, 865, 1320)),
    "camarao": (6, (930, 1145, 1170, 1315)),
    "azeitona": (6, (700, 195, 815, 360)),
    "milho": (14, (110, 170, 435, 365)),
    "pimentao_verde": (14, (940, 225, 1315, 430)),
    "pimentao": (14, (1485, 200, 1865, 452)),
    "manjericao": (14, (255, 465, 760, 675)),
    "ervilha": (14, (120, 755, 260, 950)),
    "oregano": (14, (825, 955, 1280, 1365)),
    "catupiry": (7, (65, 640, 670, 985)),
    "cream_cheese": (7, (668, 700, 1180, 1065)),
    "cheddar": (7, (1285, 565, 1915, 950)),
}
def sem_fundo(im, tol=18):
    im = im.convert("RGBA"); w, h = im.size; px = im.load()
    seen = bytearray(w * h); q = deque()
    for x in range(w): q.extend([(x, 0), (x, h - 1)])
    for y in range(h): q.extend([(0, y), (w - 1, y)])
    while q:
        x, y = q.popleft()
        if not (0 <= x < w and 0 <= y < h) or seen[y * w + x]: continue
        seen[y * w + x] = 1
        r, g, b, a = px[x, y]
        if min(r, g, b) >= 255 - tol:
            px[x, y] = (255, 255, 255, 0)
            q.extend([(x + 1, y), (x - 1, y), (x, y + 1), (x, y - 1)])
    bb = im.getbbox()
    return im.crop(bb) if bb else im
GLOBAL = {"oregano", "pimentao", "pimentao_verde", "cebola"}
def tudo_branco(im, tol=22):
    px = im.load()
    for y in range(im.size[1]):
        for x in range(im.size[0]):
            r, g, b, a = px[x, y]
            if min(r, g, b) >= 255 - tol:
                px[x, y] = (255, 255, 255, 0)
    return im
LIMPA = {"cream_cheese", "ervilha", "pimentao", "catupiry", "cheddar"}
def tira_sujeira(im, minimo=900):
    w, h = im.size; px = im.load(); seen = bytearray(w * h)
    for sy in range(h):
        for sx in range(w):
            if seen[sy * w + sx] or px[sx, sy][3] == 0: continue
            comp, q = [], deque([(sx, sy)]); seen[sy * w + sx] = 1
            while q:
                x, y = q.popleft(); comp.append((x, y))
                for nx, ny in ((x+1,y),(x-1,y),(x,y+1),(x,y-1)):
                    if 0 <= nx < w and 0 <= ny < h and not seen[ny*w+nx] and px[nx, ny][3]:
                        seen[ny*w+nx] = 1; q.append((nx, ny))
            if len(comp) < minimo:
                for x, y in comp: px[x, y] = (255, 255, 255, 0)
    bb = im.getbbox()
    return im.crop(bb) if bb else im
out = sys.argv[1]
for nome, (i, box) in CROPS.items():
    src = Image.open(U + F[i] + "-image.png").convert("RGB").crop(box)
    if nome == "cheddar":
        from PIL import ImageDraw
        ImageDraw.Draw(src).rectangle((368, 0, 640, 34), fill="white")
    im = sem_fundo(src)
    if nome in GLOBAL:
        im = tudo_branco(im)
    if nome in LIMPA:
        im = tira_sujeira(im)
    im.save(f"{out}/{nome}.png", optimize=True)
    print(nome, im.size)

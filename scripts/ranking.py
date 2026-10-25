#!/usr/bin/env python3
"""Actualiza los rankings absolutos (Masculino y Femenino) de ligapadelmadrid.com.

Regla: se guarda una foto nueva COMPLETA de un ranking solo si han cambiado los puntos
de algún jugador del club de referencia respecto a la última foto guardada.
Cada fila: [pos, nombre, equipo, p_ini, p_act, idCategoria, idJugador,
            ganados, perdidos, perd_2sets, perd_3sets, perd_wo, division, suma_ok]

Uso: python3 scripts/ranking.py [M|F ...]
"""
import datetime, json, os, re, sys, threading, time
from concurrent.futures import ThreadPoolExecutor
from zoneinfo import ZoneInfo

import requests
from bs4 import BeautifulSoup

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from config import CLUB, EXCLUIDOS, RANKING, UA

SEXOS = {"M": "Masculino", "F": "Femenino"}
URL = "https://www.ligapadelmadrid.com/if_licencia_ranking.aspx?s={}"
DET = "https://www.ligapadelmadrid.com/ligas_verEquiposDetV4.aspx?idCategoria={}&idJugador={}"
TARGET = "ctl00$ContentPlaceHolder1$lbMasDatos"
INDEX = os.path.join(RANKING, "index.json")


def log(*a):
    print(*a, flush=True)


# ---------- Ranking (lista completa pulsando "VER MÁS") ----------
def form_fields(soup):
    form = soup.find("form")
    data = {}
    for inp in form.find_all("input"):
        name = inp.get("name")
        if not name:
            continue
        t = (inp.get("type") or "text").lower()
        if t in ("submit", "button", "image", "file"):
            continue
        if t in ("checkbox", "radio") and not inp.has_attr("checked"):
            continue
        data[name] = inp.get("value", "")
    for sel in form.find_all("select"):
        opt = sel.find("option", selected=True) or sel.find("option")
        if sel.get("name") and opt:
            data[sel["name"]] = opt.get("value", opt.text)
    return data


def filas(soup):
    out = []
    for tr in soup.select("table tr"):
        tds = [re.sub(r"\s+", " ", td.get_text(" ", strip=True)).strip() for td in tr.find_all("td")]
        if len(tds) >= 6 and tds[1].isdigit():
            a = tr.find("a", href=True)
            m = re.search(r"idCategoria=(\d+).*?idJugador=(\d+)", a["href"]) if a else None
            out.append([int(tds[1]), tds[2], tds[3], int(tds[4] or 0), int(tds[5] or 0),
                        int(m.group(1)) if m else None, int(m.group(2)) if m else None])
    return out


def scrape_ranking(sexo):
    url = URL.format(sexo)
    s = requests.Session()
    s.headers["User-Agent"] = UA
    soup = BeautifulSoup(s.get(url, timeout=60).text, "html.parser")
    txt = soup.get_text("\n")
    m = re.search(r"Fecha de Ranking\s*(\d{2}/\d{2}/\d{4})", txt)
    fecha = m.group(1) if m else None
    t = re.search(r"(Ranking Absoluto[^\n]*)", txt)
    titulo = t.group(1).strip() if t else "Ranking Absoluto " + sexo
    prev = len(filas(soup))
    for _ in range(400):
        if not soup.find(id="ContentPlaceHolder1_lbMasDatos"):
            break
        data = form_fields(soup)
        data["__EVENTTARGET"] = TARGET
        data["__EVENTARGUMENT"] = ""
        soup = BeautifulSoup(s.post(url, data=data, timeout=120).text, "html.parser")
        n = len(filas(soup))
        if n <= prev:
            break
        prev = n
    jug = [r for r in filas(soup) if r[6] not in EXCLUIDOS]
    if not fecha or len(jug) < 100:
        raise RuntimeError(f"datos incompletos (fecha={fecha}, jugadores={len(jug)})")
    d, mth, y = fecha.split("/")
    return {"fecha": fecha, "fecha_iso": f"{y}-{mth}-{d}", "titulo": titulo}, jug


# ---------- Partidos ganados / perdidos de cada jugador ----------
_tl = threading.local()


def sess():
    if not hasattr(_tl, "s"):
        _tl.s = requests.Session()
        _tl.s.headers["User-Agent"] = UA
    return _tl.s


def fetch(cat, jug):
    for intento in range(3):
        try:
            r = sess().get(DET.format(cat, jug), timeout=(10, 30))
            if r.status_code == 200:
                return r.text
        except requests.RequestException:
            pass
        time.sleep(2 + intento * 3)
    return None


def analiza(html):
    # Victoria = puntos >= 100; derrota en 2 sets = 10, en 3 sets = 15, W.O. = 0
    soup = BeautifulSoup(html, "html.parser")
    for t in soup(["script", "style"]):
        t.decompose()
    txt = re.sub(r"[ \t\r\f\v]+", " ", soup.get_text("\n"))
    g = p2 = p3 = wo = total = 0
    divisiones = []
    for b in re.split(r"\bJornada:\s*", txt)[1:]:
        m = re.search(r"Puntos Ganados\s*:\s*(\d+)", b)
        if not m:
            continue
        pts = int(m.group(1))
        total += pts
        gm = re.search(r"Grupo:\s*\n?\s*([^\n]+)", b)
        if gm:
            divisiones.append(gm.group(1).strip().replace("DIVISIÓN", "DIVISION"))
        if pts >= 100: g += 1
        elif pts == 15: p3 += 1
        elif pts == 10: p2 += 1
        else: wo += 1
    div = max(set(divisiones), key=divisiones.count) if divisiones else ""
    return [g, p2 + p3 + wo, p2, p3, wo, div, total]


def completa_partidos(jug, prev_rows):
    # Reutiliza los datos de la foto anterior de quien tiene los mismos puntos
    previos = {r[6]: r for r in prev_rows if len(r) >= 14 and r[7] is not None and r[13]}
    cache, faltan = {}, []
    for r in jug:
        p = previos.get(r[6])
        if p and p[4] == r[4]:
            cache[r[6]] = [p[7], p[8], p[9], p[10], p[11], p[12], r[4]]
        else:
            faltan.append(r)
    log(f"  reutilizados {len(cache)}, por descargar {len(faltan)}")
    hechos = [0]
    lock = threading.Lock()

    def trabajo(r):
        html = fetch(r[5], r[6]) if r[6] else None
        a = analiza(html) if html else None
        with lock:
            hechos[0] += 1
            if hechos[0] % 200 == 0:
                log(f"  progreso {hechos[0]}/{len(faltan)}")
        return r[6], a

    with ThreadPoolExecutor(max_workers=8) as ex:
        for i, a in ex.map(trabajo, faltan):
            if a is not None:
                cache[i] = a
    malos = descuadres = 0
    for r in jug:
        a = cache.get(r[6])
        del r[7:]
        if a is None:
            malos += 1
            r.extend([None, None, None, None, None, "", False])
            continue
        g, p, p2, p3, wo, div, total = a
        ok = total == r[4]
        descuadres += not ok
        r.extend([g, p, p2, p3, wo, div, ok])
    log(f"  sin datos {malos}, suma distinta {descuadres}")


# ---------- Almacenamiento ----------
def carga_index():
    if os.path.exists(INDEX):
        return json.load(open(INDEX, encoding="utf8"))
    return {"estado": {}, "M": [], "F": []}


def guarda_json(path, obj):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf8") as f:
        json.dump(obj, f, ensure_ascii=False, separators=(",", ":"))
    os.replace(tmp, path)


def es_club(r):
    return CLUB in str(r[2]).upper().replace("Ó", "O")


def actualiza(g, idx, ahora):
    sexo = SEXOS[g]
    log(f"Ranking {sexo}")
    meta, jug = scrape_ranking(sexo)
    log(f"  web: {meta['fecha']} · {len(jug)} jugadores")
    metas = sorted(idx.get(g, []), key=lambda m: m["fecha_iso"], reverse=True)
    prev_rows = []
    if metas:
        prev_rows = json.load(open(os.path.join(RANKING, g, metas[0]["fecha_iso"] + ".json"), encoding="utf8"))["jugadores"]
        N = {r[6]: r[4] for r in jug if es_club(r)}
        P = {r[6]: r[4] for r in prev_rows if es_club(r)}
        if not N or not P:
            return "error", f"No se pudo verificar el ranking {sexo} (sin jugadores de referencia)", metas[0]["fecha_iso"]
        cambios = [i for i in set(N) | set(P) if N.get(i) != P.get(i)]
        if not cambios:
            return "sin_cambios", f"Sin cambios en los puntos (última foto {metas[0]['fecha']})", metas[0]["fecha_iso"]
        log(f"  {len(cambios)} jugadores del club cambian de puntos")
    # Id de la foto: fecha de la web si aún no existe; si existe, la fecha de hoy en Madrid
    ids = {m["fecha_iso"] for m in metas}
    fid = meta["fecha_iso"]
    if fid in ids:
        fid = ahora.astimezone(ZoneInfo("Europe/Madrid")).date().isoformat()
        if fid != meta["fecha_iso"]:
            meta["fecha_web"] = meta["fecha"]
            y, mo, d = fid.split("-")
            meta["fecha"] = f"{d}/{mo}/{y}"
        meta["fecha_iso"] = fid
    completa_partidos(jug, prev_rows)
    meta.update(total=len(jug), capturado_en=ahora.isoformat(timespec="seconds"))
    guarda_json(os.path.join(RANKING, g, fid + ".json"), {"jugadores": jug})
    idx[g] = sorted([m for m in metas if m["fecha_iso"] != fid] + [meta], key=lambda m: m["fecha_iso"], reverse=True)
    return "nuevo", f"Puntos actualizados: foto del {meta['fecha']} guardada ({len(jug)} jugadores)", fid


def main():
    gs = [a for a in sys.argv[1:] if a in SEXOS] or ["M", "F"]
    idx = carga_index()
    ahora = datetime.datetime.now(datetime.timezone.utc).replace(microsecond=0)
    fallos = 0
    for g in gs:
        try:
            res, msg, fid = actualiza(g, idx, ahora)
        except Exception as e:
            fallos += 1
            res, msg, fid = "error", f"Error al consultar la web: {e}", None
        log(f"  {res}: {msg}")
        if g == "M":
            est = {"ultima_comprobacion": ahora.isoformat(timespec="seconds"), "resultado": res, "mensaje": msg}
            if fid:
                est["ultima_fecha_iso"] = fid
            idx["estado"] = est
    guarda_json(INDEX, idx)
    sys.exit(1 if fallos == len(gs) else 0)


if __name__ == "__main__":
    main()

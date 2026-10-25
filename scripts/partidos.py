#!/usr/bin/env python3
"""Actualiza data/partidos.json: resultados de los encuentros entre equipos (Liga y Copa).

La web corta conexiones con peticiones en paralelo: las categorías se recorren una a una.
Solo reescribe el archivo si cambian los equipos o los encuentros.
Uso: python3 scripts/partidos.py
"""
import datetime, html, http.cookiejar, json, os, re, sys, time, urllib.parse, urllib.request

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from config import DATA, UA

BASE = "https://www.ligapadelmadrid.com/"
CATS = {152: "Liga · Zona Norte y Sur", 153: "Liga · Zona Norte", 154: "Liga · Zona Sur",
        162: "Copa · Zona Norte", 163: "Copa · Zona Sur", 165: "Copa · Zona Norte y Sur"}
SALIDA = os.path.join(DATA, "partidos.json")


def opener():
    cj = http.cookiejar.CookieJar()
    op = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(cj))
    op.addheaders = [("User-Agent", UA)]
    return op


def get(op, url, data=None):
    err = None
    for i in range(5):
        try:
            r = op.open(url, urllib.parse.urlencode(data).encode() if data else None, timeout=40)
            return r.read().decode("utf8", "replace")
        except Exception as e:
            err = e
            time.sleep(5 + i * 15)
    raise err


def hidden(s):
    return {m.group(1): html.unescape(m.group(2)) for m in
            re.finditer(r'<input type="hidden" name="([^"]+)" id="[^"]*" value="([^"]*)"', s)}


def _select(s, name):
    return re.search(r'name="ctl00\$ContentPlaceHolder1\$' + name + r'"[^>]*>(.*?)</select>', s, re.S)


def opts(s, name):
    m = _select(s, name)
    return re.findall(r'<option(?: selected="selected")? value="([^"]*)">([^<]*)</option>', m.group(1)) if m else []


def sel(s, name):
    m = _select(s, name)
    x = re.search(r'<option selected="selected" value="([^"]*)"', m.group(1)) if m else None
    return x.group(1) if x else None


def strip(x):
    return html.unescape(re.sub(r"<[^>]+>", "", x)).strip()


def rows(s):
    out = []
    t = re.search(r"<table class='table'>.*?</table>", s, re.S)
    if not t:
        return out
    for tr in re.findall(r"<tr>(.*?)</tr>", t.group(0), re.S):
        tds = re.findall(r"<td[^>]*>(.*?)</td>", tr, re.S)
        if len(tds) < 5:
            continue
        ids = re.findall(r"idEquipo=(\d+)", tr)
        det = re.search(r"idResultado=(\d+)", tr)
        out.append({"a": strip(tds[0]), "ga": strip(tds[1]), "gb": strip(tds[2]), "b": strip(tds[3]),
                    "ida": ids[0] if len(ids) > 0 else None, "idb": ids[1] if len(ids) > 1 else None,
                    "res": det.group(1) if det else None, "fecha": strip(tds[4]) if not det else ""})
    return out


def post(op, url, s, grupo, jor, target):
    d = hidden(s)
    d["__EVENTTARGET"] = "ctl00$ContentPlaceHolder1$" + target
    d["__EVENTARGUMENT"] = ""
    d["ctl00$ContentPlaceHolder1$ddGrupo"] = grupo
    d["ctl00$ContentPlaceHolder1$ddJornada"] = jor
    return get(op, url, d)


def scrape(cat):
    op = opener()
    url = BASE + f"ligas_calendario.aspx?idCategoria={cat}"
    s = get(op, url)
    res = []
    for gv, gn in opts(s, "ddGrupo"):
        s = post(op, url, s, gv, "1", "ddGrupo")
        for jv, jn in opts(s, "ddJornada"):
            s = post(op, url, s, gv, jv, "ddJornada")
            if sel(s, "ddGrupo") != gv or sel(s, "ddJornada") != jv:
                print("  aviso: respuesta desajustada", gv, jv, flush=True)
            for r in rows(s):
                r.update(cat=cat, grupo=gn.strip(), jornada=int(jn))
                res.append(r)
            time.sleep(0.8)
        print(f"  {cat} {gn.strip()}: {len(res)} filas", flush=True)
    return res


def main():
    todo = {}
    for c in CATS:
        for intento in range(3):
            try:
                todo[c] = scrape(c)
                break
            except Exception as e:
                print(f"  categoría {c}: fallo ({e}), intento {intento + 1}", flush=True)
                time.sleep(30)
        if c not in todo:
            sys.exit(f"No se pudo leer la categoría {c}; no se actualiza nada")
    eq, P, seen = {}, [], set()
    n = lambda x: re.sub(r"\s+", " ", x).strip()
    num = lambda x: int(x) if x.strip().isdigit() else None
    for c in CATS:
        for r in todo[c]:
            if r["res"] and r["res"] in seen:
                continue
            if r["res"]:
                seen.add(r["res"])
            if r["ida"]: eq[r["ida"]] = n(r["a"])
            if r["idb"]: eq[r["idb"]] = n(r["b"])
            P.append([c, html.unescape(r["grupo"]).replace("DIVISIÓN", "DIVISION"), r["jornada"],
                      int(r["ida"]) if r["ida"] else None, int(r["idb"]) if r["idb"] else None,
                      num(r["ga"]), num(r["gb"]), int(r["res"]) if r["res"] else None, r["fecha"]])
    if os.path.exists(SALIDA):
        old = json.load(open(SALIDA, encoding="utf8"))
        if old.get("equipos") == eq and old.get("p") == P:
            print(f"Sin cambios ({len(eq)} equipos, {len(P)} encuentros)")
            return
    out = {"generado": datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds"),
           "cats": {str(k): v for k, v in CATS.items()}, "equipos": eq, "p": P}
    with open(SALIDA, "w", encoding="utf8") as f:
        json.dump(out, f, ensure_ascii=False, separators=(",", ":"))
    print(f"Actualizado: {len(eq)} equipos, {len(P)} encuentros, {sum(1 for p in P if p[5] is not None)} con resultado")


if __name__ == "__main__":
    main()

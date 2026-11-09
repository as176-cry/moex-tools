"""Скачивает ставки риска НКЦ по акциям и сохраняет data/rates.json для дашборда.

Источники по порядку: ISS MOEX (rms, затем rms-test). Для диагностики
сохраняет начало сырых ответов в data/diag.json.
"""
import json, time, urllib.request, datetime, pathlib

OUT = pathlib.Path(__file__).resolve().parent.parent / "data"
OUT.mkdir(exist_ok=True)
UA = {"User-Agent": "moex-tools-rates/1.0"}
diag = {"run": datetime.datetime.utcnow().isoformat() + "Z", "attempts": []}


def get(url):
    req = urllib.request.Request(url, headers=UA)
    with urllib.request.urlopen(req, timeout=60) as r:
        return r.status, r.headers.get("Content-Type", ""), r.read().decode("utf-8", "replace")


def rows(block):
    return [dict(zip(block["columns"], r)) for r in block["data"]]


def from_iss(base):
    out, cols, start, first_prev = [], None, 0, None
    while start < 30000:
        url = f"{base}.json?iss.meta=off&start={start}"
        status, ctype, body = get(url)
        if start == 0:
            diag["attempts"].append({"url": url, "status": status, "type": ctype, "head": body[:1500]})
        j = json.loads(body)
        key = next((k for k, v in j.items() if isinstance(v, dict) and "SECID" in v.get("columns", [])), None)
        if not key:
            break
        b = j[key]
        cols = b["columns"]
        if not b["data"]:
            break
        first = b["data"][0][cols.index("SECID")]
        if first == first_prev:
            break
        first_prev = first
        out += rows(b)
        start += len(b["data"])
        cur = next((k for k in j if "cursor" in k.lower()), None)
        if cur and j[cur]["data"]:
            c = rows(j[cur])[0]
            if c.get("TOTAL") is not None and start >= c["TOTAL"]:
                break
        elif len(b["data"]) < 100:
            break
        time.sleep(0.3)
    return out, cols


result = None
for base in ("https://iss.moex.com/iss/rms/engines/stock/objects/irr",
             "https://iss.moex.com/iss/rms-test/engines/stock/objects/irr"):
    try:
        data, cols = from_iss(base)
        diag["attempts"].append({"source": base, "rows": len(data), "columns": cols})
        if data:
            result = {"source": base, "columns": cols, "rows": data}
            break
    except Exception as e:  # noqa: BLE001
        diag["attempts"].append({"source": base, "error": repr(e)[:500]})

if result:
    by = {}
    for r in result["rows"]:
        by.setdefault(str(r.get("SECID", "")).upper(), []).append(r)
    payload = {
        "updated": diag["run"],
        "source": result["source"],
        "columns": result["columns"],
        "securities": by,
    }
    (OUT / "rates.json").write_text(json.dumps(payload, ensure_ascii=False, separators=(",", ":")))
    diag["ok"] = True
else:
    diag["ok"] = False

(OUT / "diag.json").write_text(json.dumps(diag, ensure_ascii=False, indent=1))
print(json.dumps({k: v for k, v in diag.items() if k != "attempts"}), len(diag["attempts"]), "attempts")

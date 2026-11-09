"""Скачивает ставки риска НКЦ по акциям и сохраняет data/rates.json для дашборда.

Источники по порядку: ISS MOEX (rms, затем rms-test). Для диагностики
сохраняет начало сырых ответов в data/diag.json.
"""
import json, re, time, urllib.request, datetime, pathlib

OUT = pathlib.Path(__file__).resolve().parent.parent / "data"
OUT.mkdir(exist_ok=True)
UA = {"User-Agent": "moex-tools-rates/1.0"}
diag = {"run": datetime.datetime.utcnow().isoformat() + "Z", "attempts": []}


def get(url):
    req = urllib.request.Request(url, headers=UA)
    with urllib.request.urlopen(req, timeout=60) as r:
        return r.status, r.headers.get("Content-Type", ""), r.read().decode("utf-8", "replace")


def text_of(html):
    html = re.sub(r"(?is)<(script|style)[^>]*>.*?</\1>", " ", html)
    html = re.sub(r"data:[^\"')\s]+", " ", html)
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", html)).strip()


def probe(url):
    """Сохраняет текст и ссылки страницы для разведки источника."""
    try:
        status, ctype, body = get(url)
        raw = OUT / "raw"; raw.mkdir(exist_ok=True)
        (raw / (re.sub(r"[^A-Za-z0-9]+", "_", url.split("//")[1])[:80] + ".html")).write_text(body)
        links = sorted(set(re.findall(r"""href=["']([^"']+)["']""", body)))
        links = [l for l in links if re.search(r"(?i)rate|risk|stock|secur|xls|csv|json|connector|fond|equit", l)]
        tables = re.findall(r"(?is)<table.*?</table>", body)
        scripts = re.findall(r"""(?is)<script[^>]*src=["']([^"']+)""", body)
        inline = " ".join(re.findall(r"(?is)<script(?![^>]*src)[^>]*>(.*?)</script>", body))
        endpoints = sorted(set(re.findall(r"""["'](/[^"'\s]*(?:rates|risk|csv|xls|json|ajax|api|export|download)[^"'\s]*)["']""", body + inline)))
        diag["attempts"].append({"probe": url, "status": status, "type": ctype, "size": len(body),
                                 "links": links[:150], "scripts": scripts[:40], "endpoints": endpoints[:80],
                                 "tables": [text_of(t)[:2500] for t in tables[:4]],
                                 "inline_js": re.sub(r"\s+", " ", inline)[:4000],
                                 "forms": re.findall(r"(?is)<form.*?</form>", body)[:3] and
                                          [re.sub(r"\s+", " ", f)[:1500] for f in re.findall(r"(?is)<form.*?</form>", body)[:3]]})
    except Exception as e:  # noqa: BLE001
        diag["attempts"].append({"probe": url, "error": repr(e)[:300]})


def rows(block):
    return [dict(zip(block["columns"], r)) for r in block["data"]]


def from_iss(base):
    out, cols, start, first_prev = [], None, 0, None
    while start < 30000:
        url = f"{base}.json?iss.meta=off&iss.only=marketrates,marketrates.cursor&start={start}"
        status, ctype, body = get(url)
        if start == 0:
            diag["attempts"].append({"url": url, "status": status, "type": ctype, "text": text_of(body)[:1500]})
        j = json.loads(body)
        key = next((k for k, v in j.items() if isinstance(v, dict) and any(c.upper() in ("SECID", "ASSETID1") for c in v.get("columns", []))), None)
        if not key:
            break
        b = j[key]
        cols = b["columns"]
        if not b["data"]:
            break
        idc = next(i for i, c in enumerate(cols) if c.upper() in ("SECID", "ASSETID1"))
        first = (b["data"][0][idc], b["data"][-1][idc], len(b["data"]))
        if first == first_prev:
            break
        first_prev = first
        out += rows(b)
        start += len(b["data"])
        cur = next((k for k in j if "cursor" in k.lower()), None)
        if cur and j[cur]["data"]:
            c = rows(j[cur])[0]
            tot = c.get("TOTAL", c.get("total"))
            if tot is not None and start >= tot:
                break
        elif len(b["data"]) < 100:
            break
        time.sleep(0.3)
    return out, cols


result = None
for base in ("https://iss.moex.com/iss/rms/engines/stock/objects/marketrates",):
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
        sid = str(r.get("SECID") or r.get("assetid1") or r.get("ASSETID1") or "").upper()
        by.setdefault(sid, []).append(r)
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

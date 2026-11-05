#!/usr/bin/env python3
"""
Decouverte ISAPI — etape 2 (lecture seule, GET uniquement).

Pour chaque NVR de config/.env, interroge une liste d'endpoints candidats et enregistre :
  - le code HTTP, la balise racine, le nombre d'elements utiles ;
  - la reponse brute dans data/discovery/<NVR>/<endpoint>.xml|json, apres effacement
    des champs sensibles (password, userName, etc.).
Imprime un tableau de synthese. N'affiche et ne journalise jamais les identifiants.

Usage :  python src/discovery.py            (5 NVR)
         python src/discovery.py SITE-C   (un seul NVR)
"""
import json
import re
import sys
import time
from pathlib import Path

import requests
from requests.auth import HTTPDigestAuth
from dotenv import dotenv_values

ROOT = Path(__file__).resolve().parent.parent
ENV_FILE = ROOT / "config" / ".env"
OUT_DIR = ROOT / "data" / "discovery"

# (cle courte, chemin, ce qu'on espere y trouver)
ENDPOINTS = [
    ("deviceInfo",        "/ISAPI/System/deviceInfo",                          "modele, firmware, serie, MAC du NVR"),
    ("device_info_old",   "/ISAPI/System/device/info",                         "ancien chemin (403 observe le 09/10)"),
    ("capabilities",      "/ISAPI/System/capabilities",                        "capacites du NVR"),
    ("network",           "/ISAPI/System/Network/interfaces",                  "IP/MAC du NVR"),
    ("streaming",         "/ISAPI/Streaming/channels",                         "flux video (comptage cameras)"),
    ("proxy_channels",    "/ISAPI/ContentMgmt/InputProxy/channels",            "nom + IP + modele de chaque camera IP"),
    ("proxy_status",      "/ISAPI/ContentMgmt/InputProxy/channels/status",     "online/offline par canal"),
    ("video_inputs",      "/ISAPI/System/Video/inputs/channels",               "noms des entrees video"),
    ("workingstatus",     "/ISAPI/System/workingstatus?format=json",           "etat global + enregistrement par canal"),
    ("record_tracks",     "/ISAPI/ContentMgmt/record/tracks",                  "plan d'enregistrement par canal"),
    ("storage",           "/ISAPI/ContentMgmt/Storage",                        "etat des disques"),
    ("time",              "/ISAPI/System/time",                                "heure du NVR"),
]

SENSITIVE_TAGS = ("password", "passwd", "userName", "user", "secretKey", "key", "encryptKey")

TIMEOUT = 10
PAUSE_BETWEEN = 0.3   # menager la charge des NVR (spec §12)


def load_config():
    if not ENV_FILE.exists():
        sys.exit(f"ERREUR: {ENV_FILE} absent. Copier config/.env.example en config/.env et remplir NVR_USER / NVR_PASS.")
    env = dotenv_values(ENV_FILE)
    user, pwd = env.get("NVR_USER") or "", env.get("NVR_PASS") or ""
    if not user or not pwd or "A-REMPLIR" in user or "A-REMPLIR" in pwd:
        sys.exit("ERREUR: NVR_USER / NVR_PASS non remplis dans config/.env.")
    for label, val in (("NVR_USER", user), ("NVR_PASS", pwd)):
        if val.startswith("<") and val.endswith(">"):
            sys.exit(f"ERREUR: {label} est encore entoure de < > dans config/.env. "
                     f"Retirer les chevrons : NVR_USER=admin et non NVR_USER=<admin>.")
    nvrs = []
    for i in range(1, 17):
        raw = env.get(f"NVR{i}")
        if not raw:
            continue
        name, ip, port, location = (raw.split("|") + ["", "", "80", ""])[:4]
        nvrs.append({"name": name.strip(), "ip": ip.strip(), "port": int(port or 80), "location": location.strip()})
    return user, pwd, nvrs


def redact(text: str) -> str:
    """Efface les valeurs des champs sensibles (XML et JSON) avant ecriture sur disque."""
    for tag in SENSITIVE_TAGS:
        text = re.sub(rf"(<{tag}[^>]*>)(.*?)(</{tag}>)", r"\1***\3", text, flags=re.S | re.I)
        text = re.sub(rf'("{tag}"\s*:\s*)"[^"]*"', r'\1"***"', text, flags=re.I)
    return text


def strip_ns(xml: str) -> str:
    return re.sub(r'\sxmlns(:\w+)?="[^"]+"', "", xml)


def summarize(body: str, ctype: str) -> str:
    """Resume court : balise racine + comptage des enfants directs."""
    if "json" in ctype or body.lstrip().startswith("{"):
        try:
            data = json.loads(body)
            return "JSON cles=" + ",".join(list(data.keys())[:6])
        except ValueError:
            return "JSON illisible"
    m = re.search(r"<([A-Za-z_][\w.-]*)[\s>]", strip_ns(body).split("?>", 1)[-1])
    if not m:
        return "(vide)"
    root = m.group(1)
    children = re.findall(r"<(\w+)[\s>]", strip_ns(body))
    # enfant repete le plus frequent = type d'element liste
    counts = {}
    for c in children:
        counts[c] = counts.get(c, 0) + 1
    rep = [f"{k}x{v}" for k, v in sorted(counts.items(), key=lambda kv: -kv[1]) if v > 1 and k != root][:2]
    return root + (" [" + ", ".join(rep) + "]" if rep else "")


def probe(nvr, user, pwd):
    session = requests.Session()
    session.auth = HTTPDigestAuth(user, pwd)
    session.headers["User-Agent"] = "hikvision-monitor-discovery/1.0"
    base = f"http://{nvr['ip']}:{nvr['port']}"
    out = OUT_DIR / nvr["name"]
    out.mkdir(parents=True, exist_ok=True)
    rows = []
    for key, path, hope in ENDPOINTS:
        t0 = time.time()
        try:
            r = session.get(base + path, timeout=TIMEOUT)   # GET uniquement : lecture seule
            ms = int((time.time() - t0) * 1000)
            ctype = r.headers.get("Content-Type", "")
            ext = "json" if ("json" in ctype or r.text.lstrip().startswith("{")) else "xml"
            (out / f"{key}.{ext}").write_text(redact(r.text), encoding="utf-8")
            info = summarize(r.text, ctype) if r.status_code == 200 else re.sub(r"\s+", " ", strip_ns(r.text))[:80]
            rows.append((key, r.status_code, ms, info))
        except requests.RequestException as e:
            rows.append((key, "ERR", int((time.time() - t0) * 1000), type(e).__name__))
        time.sleep(PAUSE_BETWEEN)
    return rows


def main():
    user, pwd, nvrs = load_config()
    only = {a.upper() for a in sys.argv[1:]}
    if only:
        nvrs = [n for n in nvrs if n["name"].upper() in only]
    report = {}
    for nvr in nvrs:
        print(f"\n=== {nvr['name']} ({nvr['ip']}:{nvr['port']}) ===")
        rows = probe(nvr, user, pwd)
        report[nvr["name"]] = rows
        for key, code, ms, info in rows:
            print(f"  {key:<16} {str(code):<4} {ms:>5} ms  {info}")
    (OUT_DIR / "summary.json").write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"\nReponses brutes (champs sensibles effaces) : {OUT_DIR}")


if __name__ == "__main__":
    main()

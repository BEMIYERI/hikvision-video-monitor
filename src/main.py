#!/usr/bin/env python3
"""HIKVISION VIDEO MONITOR — point d'entree UNIQUE.

    python src/main.py            -> boucle de supervision + dashboard http://127.0.0.1:8765
    python src/main.py --once     -> un seul cycle de collecte, affiche le resume, quitte

Lecture seule sur les NVR. Aucun secret n'est journalise.
"""
import argparse
import csv
import io
import json
import logging
import re
import secrets
import socket
from logging.handlers import RotatingFileHandler
import sys
import threading
import time
from datetime import datetime, timedelta, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

sys.path.insert(0, str(Path(__file__).resolve().parent))

from config import RESOURCES, ROOT, load_settings   # noqa: E402
from collector import collect_all               # noqa: E402
from store import Store                         # noqa: E402

# PWA assets (inline for reliability in sandboxed environment)
MANIFEST = '''{"name":"Hikvision CCTV Monitor","short_name":"CCTV Monitor","description":"Surveillance vidéo Hikvision - monitoring des NVR et caméras","start_url":"/","display":"standalone","background_color":"#0f1720","theme_color":"#4493f8","orientation":"portrait","icons":[{"src":"/icon-192.svg","sizes":"192x192","type":"image/svg+xml"},{"src":"/icon-512.svg","sizes":"512x512","type":"image/svg+xml"}]}'''
SW = '''const C="hikvision-monitor-v4",S=["/","/manifest.json","/icon-192.svg"];
self.addEventListener("install",e=>e.waitUntil(caches.open(C).then(c=>c.addAll(S)).then(()=>self.skipWaiting())));
self.addEventListener("activate",e=>e.waitUntil(caches.keys().then(k=>Promise.all(k.filter(x=>x!==C).map(x=>caches.delete(x)))).then(()=>self.clients.claim())));
// Jamais de cache pour l'API, les captures, les rapports ni l'APK : donnees volatiles et
// sensibles (le jeton figure dans l'URL de certaines requetes).
self.addEventListener("fetch",e=>{const r=e.request;if(r.method!=="GET")return;
  const u=new URL(r.url);
  if(u.origin!==self.location.origin)return;
  if(u.pathname.startsWith("/api/")||u.pathname.startsWith("/reports/")||u.pathname.startsWith("/snapshots/")||u.pathname==="/app.apk")return;
  e.respondWith(fetch(r).then(res=>{if(res.ok){const cp=res.clone();caches.open(C).then(c=>c.put(r,cp));}return res;}).catch(()=>caches.match(r)));});'''
ICON = '''<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 100 100"><circle cx="50" cy="50" r="45" fill="#4493f8"/><rect x="30" y="25" width="40" height="50" rx="5" fill="#fff"/><circle cx="50" cy="45" r="12" fill="#2ea043"/><circle cx="50" cy="65" r="8" fill="#e5534b"/></svg>'''

log = logging.getLogger("main")
STATIC = RESOURCES / "src" / "static"

def setup_logging(log_dir: Path):
    log_dir.mkdir(parents=True, exist_ok=True)
    fmt = logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s")
    root = logging.getLogger()
    root.setLevel(logging.INFO)
    fh = RotatingFileHandler(log_dir / "monitor.log", maxBytes=2_000_000, backupCount=5, encoding="utf-8")
    fh.setFormatter(fmt)
    sh = logging.StreamHandler(sys.stdout)
    sh.setFormatter(fmt)
    root.handlers[:] = [fh, sh]
    logging.getLogger("urllib3").setLevel(logging.WARNING)


class Monitor:
    def __init__(self, settings, store):
        self.settings, self.store = settings, store
        self.wake = threading.Event()
        self.running = threading.Event()
        self.cycle_lock = threading.Lock()
        self.last_error = None
        self._alerted = {}          # cles (nvr:canal:type) deja notifiees

    def run_cycle(self):
        with self.cycle_lock:
            t0 = time.time()
            snaps = collect_all(self.settings)
            ev = 0
            for s in snaps:
                res = self.store.apply_snapshot(s)
                ev += res["events"]
                for ch, _nom in res.get("went_offline", []):
                    self.capture_offline(s, ch)
                if s.errors:
                    log.warning("[%s %s] %s", s.nvr_id, s.ip, "; ".join(s.errors))
            ms = int((time.time() - t0) * 1000)
            self.store.record_cycle(snaps, ms)
            self.store.prune(self.settings.retention_days)   # purge des evenements anciens
            n = prune_snapshots(self.settings.reports_dir, self.settings.retention_days)
            if n:
                log.info("captures purgees (retention %d j) : %d dossier(s)", self.settings.retention_days, n)
            g = self.store.summary()["global"]
            log.info("cycle %d ms : NVR %d/%d joignables, cameras %d (en ligne %d, hors ligne %d, inconnu %d), %d evenement(s)",
                     ms, g["nvr_reachable"], g["nvr_total"], g["total"], g["online"], g["offline"], g["unknown"], ev)
            self.check_alerts()
            return g

    def check_alerts(self):
        """Alerte (journal + webhook optionnel) pour chaque camera hors ligne ou non-enregistree
        au-dela du seuil. Une meme anomalie n'est notifiee qu'une fois tant qu'elle persiste."""
        s = self.settings
        now_ts = datetime.now(timezone.utc).timestamp()
        actives = {}
        for c in self.store.cameras():
            if not c.get("present"):
                continue
            for kind, value, expected, since_col, threshold in (
                ("hors ligne", c.get("status"), "ONLINE", "last_status_change", s.offline_alert_threshold),
                ("sans enregistrement", c.get("recording"), "RECORDING", "last_recording_change", s.no_recording_threshold),
            ):
                if threshold <= 0 or value in (None, "UNKNOWN", expected):
                    continue
                since = c.get(since_col)
                if not since:
                    continue
                try:
                    dt = datetime.fromisoformat(since)
                except ValueError:
                    continue
                if dt.tzinfo is None:
                    dt = dt.replace(tzinfo=timezone.utc)
                elapsed = now_ts - dt.timestamp()
                if elapsed < threshold:
                    continue
                key = f"{c['nvr_id']}:{c['channel']}:{kind}"
                actives[key] = True
                if key not in self._alerted:
                    msg = (f"ALERTE {kind} : {c.get('nvr_name')} CH{c['channel']} "
                           f"{c.get('name') or '?'} depuis {int(elapsed)}s")
                    log.warning(msg)
                    self._notify(msg)
        self._alerted = actives

    def capture_offline(self, snap, channel):
        """Enregistre la derniere image d'une camera qui vient de passer hors ligne."""
        import isapi
        try:
            cli = isapi.IsapiClient(snap.ip, snap.port, self.settings.user, self.settings.password, timeout=12)
            try:
                data = cli.snapshot(channel)
            finally:
                cli.close()
        except Exception as e:
            log.warning("capture hors ligne impossible (%s CH%s) : %s", snap.nvr_id, channel, e)
            return
        try:
            path = save_snapshot(self.settings.reports_dir, snap.nvr_id, channel, data, "hors-ligne")
            log.info("derniere image avant coupure enregistree : %s", path)
        except OSError as e:
            log.warning("ecriture de la capture impossible : %s", e)

    def _notify(self, msg):
        """Envoi optionnel vers un webhook generique (ALERT_WEBHOOK dans config/.env). Jamais bloquant."""
        url = self.settings.alert_webhook
        if not url:
            return
        try:
            import requests
            requests.post(url, json={"text": msg}, timeout=5)
        except Exception as e:
            log.warning("webhook d'alerte injoignable: %s", type(e).__name__)

    def loop(self):
        self.running.set()
        while self.running.is_set():
            try:
                self.run_cycle()
                self.last_error = None
            except Exception as e:     # ne jamais arreter la supervision sur une erreur de cycle
                self.last_error = f"{type(e).__name__}: {e}"
                log.exception("erreur de cycle")
            self.wake.wait(self.settings.poll_interval)
            self.wake.clear()


def make_handler(monitor: Monitor):
    store = monitor.store

    class Handler(BaseHTTPRequestHandler):
        _role = None
        server_version = "hikvision-monitor/1.0"

        def log_message(self, *args):   # pas de bruit dans la console
            pass

        def _send(self, code, body, ctype="application/json; charset=utf-8", extra=None):
            data = body if isinstance(body, bytes) else body.encode("utf-8")
            extra = extra or {}
            self.send_response(code)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(data)))
            if "Cache-Control" not in extra:
                self.send_header("Cache-Control", "no-store")
            for k, v in extra.items():
                self.send_header(k, v)
            self.end_headers()
            self.wfile.write(data)

        def _json(self, obj, code=200):
            self._send(code, json.dumps(obj, ensure_ascii=False, default=str))

        def _authorized(self):
            """Verifie le jeton d'acces.

            Accepte deux familles de jetons :
              - le jeton maitre de config/.env (toujours valide, pour ne pas se verrouiller dehors) ;
              - les jetons individuels crees depuis le dashboard, un par personne ou par appareil,
                revocables separement.
            """
            got = self.headers.get("X-Auth-Token") or parse_qs(urlparse(self.path).query).get("token", [""])[0]
            want = monitor.settings.dashboard_token
            # le jeton maitre de config/.env est le SEUL a porter le role administrateur :
            # lui seul peut creer ou revoquer des jetons.
            if want and got and secrets.compare_digest(got, want):
                self._role = "admin"
                return True
            try:
                if got and store.verify_token(got) is not None:
                    self._role = "user"
                    return True
                # mode historique : ni jeton maitre ni jeton en base => acces libre (poste local)
                if not want and not store.list_tokens():
                    self._role = "admin"      # poste local sans protection : l'operateur est admin
                    return True
            except Exception:
                log.exception("verification du jeton impossible")
            return False

        def _est_admin(self):
            return getattr(self, "_role", None) == "admin"

        def do_GET(self):
            path = urlparse(self.path).path
            if (path.startswith("/api/") or path.startswith("/reports/")) and not self._authorized():
                return self._json({"error": "jeton d'acces requis"}, 401)
            try:
                if path in ("/", "/index.html"):
                    html = (STATIC / "index.html").read_bytes() if (STATIC / "index.html").exists() else b'<html><body><h1>Hikvision CCTV Monitor</h1><p>Dashboard starting...</p></body></html>'
                    return self._send(200, html, "text/html; charset=utf-8")
                if path == "/manifest.json":
                    return self._send(200, MANIFEST.encode("utf-8"),
                                      "application/manifest+json; charset=utf-8",
                                      {"Cache-Control": "public, max-age=3600"})
                if path == "/sw.js":
                    return self._send(200, SW.encode(), "application/javascript; charset=utf-8",
                                      {"Cache-Control": "no-store"})
                if path in ("/icon-192.png", "/icon-512.png", "/icon-192.svg", "/icon-512.svg"):
                    return self._send(200, ICON.encode("utf-8"), "image/svg+xml",
                                      {"Cache-Control": "public, max-age=3600"})
                if path.startswith("/reports/"):
                    name = path[len("/reports/"):]
                    if not re.fullmatch(r"rapport_cctv_[\w.-]+\.xlsx", name):
                        return self._json({"error": "nom de fichier invalide"}, 400)
                    fp = monitor.settings.reports_dir / name
                    if not fp.is_file():
                        return self._json({"error": "rapport introuvable"}, 404)
                    return self._send(200, fp.read_bytes(),
                                      "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                                      {"Content-Disposition": f'attachment; filename="{name}"'})
                if path in ("/landing", "/landing.html"):
                    for candidat in (ROOT / "landing.html", RESOURCES / "landing.html"):
                        if candidat.is_file():
                            return self._send(200, candidat.read_bytes(), "text/html; charset=utf-8")
                    return self._json({"error": "landing page absente de cette installation"}, 404)
                if path == "/HikvisionMonitor.exe":
                    for candidat in (ROOT / "HikvisionMonitor.exe", RESOURCES / "HikvisionMonitor.exe"):
                        if candidat.is_file():
                            return self._send(200, candidat.read_bytes(),
                                              "application/vnd.microsoft.portable-executable",
                                              {"Content-Disposition":
                                               'attachment; filename="HikvisionMonitor.exe"'})
                    return self._json({"error": "executable absent de cette installation"}, 404)
                if path == "/app.apk":
                    # fichier pose a cote de l'executable (modifiable) sinon embarque
                    for candidat in (ROOT / "HikvisionMonitor.apk",
                                     RESOURCES / "HikvisionMonitor.apk"):
                        if candidat.is_file():
                            return self._send(200, candidat.read_bytes(),
                                              "application/vnd.android.package-archive",
                                              {"Content-Disposition":
                                               'attachment; filename="HikvisionMonitor.apk"'})
                    return self._json({"error": "application Android absente du serveur"}, 404)
                if path == "/api/snapshot":
                    q = parse_qs(urlparse(self.path).query)
                    nvr_id = (q.get("nvr_id") or [""])[0]
                    try:
                        channel = int((q.get("channel") or ["0"])[0])
                    except ValueError:
                        return self._json({"error": "canal invalide"}, 400)
                    if channel <= 0:
                        return self._json({"error": "canal invalide"}, 400)
                    nvr = next((n for n in store.nvrs() if n["nvr_id"] == nvr_id), None)
                    if nvr is None:
                        return self._json({"error": "NVR inconnu"}, 404)
                    import isapi
                    try:
                        data, source = capture_image(monitor.settings, nvr, channel)
                    except isapi.IsapiError as e:
                        log.warning("capture %s CH%s : %s", nvr_id, channel, e)
                        return self._json({"error": str(e)}, 502)
                    log.info("capture %s CH%s depuis %s (%d o)", nvr_id, channel, source, len(data))
                    if (q.get("save") or ["0"])[0] in ("1", "true"):
                        try:
                            fp = save_snapshot(monitor.settings.reports_dir, nvr_id, channel, data)
                        except OSError as e:
                            return self._json({"error": f"ecriture impossible: {e}"}, 500)
                        log.info("capture manuelle : %s", fp.name)
                        return self._json({"ok": True, "file": str(fp), "name": fp.name,
                                           "url": "/snapshots/" + fp.relative_to(Path(monitor.settings.reports_dir) / "snapshots").as_posix()})
                    return self._send(200, data, "image/jpeg", {"Cache-Control": "no-store"})
                if path.startswith("/snapshots/"):
                    rel = path[len("/snapshots/"):]
                    if not re.fullmatch(r"[0-9]{4}-[0-9]{2}-[0-9]{2}/[\w.-]+\.jpg", rel):
                        return self._json({"error": "nom de fichier invalide"}, 400)
                    fp = Path(monitor.settings.reports_dir) / "snapshots" / rel
                    if not fp.is_file():
                        return self._json({"error": "introuvable"}, 404)
                    return self._send(200, fp.read_bytes(), "image/jpeg", {"Cache-Control": "no-store"})
                if path == "/api/summary":
                    s = store.summary()
                    s["last_cycle"] = store.last_cycle()
                    s["poll_interval"] = monitor.settings.poll_interval
                    s["monitor_error"] = monitor.last_error
                    return self._json(s)
                if path == "/api/me":
                    return self._json({"role": getattr(self, "_role", None) or "user",
                                       "admin": self._est_admin()})
                if path == "/api/tokens":
                    if not self._est_admin():
                        return self._json({"error": "reserve au super administrateur"}, 403)
                    return self._json({"tokens": store.list_tokens()})
                if path == "/api/cameras":
                    return self._json(store.cameras())
                if path == "/api/events":
                    q = parse_qs(urlparse(self.path).query)
                    jours = max(1, min(3650, _entier(q.get("days"), 30)))
                    limite = max(1, min(20000, _entier(q.get("limit"), 1000)))
                    return self._json({"events": store.events(limite, jours),
                                       "total": store.events_count(jours),
                                       "days": jours})
                if path == "/api/events.csv":
                    q = parse_qs(urlparse(self.path).query)
                    jours = max(1, min(3650, _entier(q.get("days"), 30)))
                    lignes = store.events(1000000, jours)
                    nom = f"historique_{jours}j_{time.strftime('%Y-%m-%d_%H%M')}.csv"
                    return self._send(200, events_csv(lignes), "text/csv; charset=utf-8",
                                      {"Content-Disposition": f'attachment; filename="{nom}"'})
                if path == "/api/cameras.csv":
                    return self._send(200, cameras_csv(store.cameras()), "text/csv; charset=utf-8",
                                      {"Content-Disposition": f'attachment; filename="cameras_{time.strftime("%Y-%m-%d_%H%M")}.csv"'})
                if path == "/api/health":
                    return self._json({"ok": True})
                self._json({"error": "introuvable"}, 404)
            except Exception as e:
                log.exception("erreur HTTP %s", path)
                self._json({"error": type(e).__name__}, 500)

        def _corps_json(self):
            """Corps JSON de la requete (taille bornee : une requete de renommage est minuscule)."""
            try:
                n = int(self.headers.get("Content-Length") or 0)
            except ValueError:
                return None
            if n <= 0 or n > 8192:
                return None
            try:
                return json.loads(self.rfile.read(n).decode("utf-8"))
            except (ValueError, UnicodeDecodeError):
                return None

        def _rename(self):
            """Renomme une camera cote NVR, verifie sur le materiel, puis met la base a jour."""
            s = monitor.settings
            if not s.allow_write:
                return self._json({"error": "ecriture desactivee (ALLOW_NVR_WRITE=false dans config/.env)"}, 403)
            data = self._corps_json()
            if not isinstance(data, dict):
                return self._json({"error": "corps JSON invalide"}, 400)
            nvr_id = str(data.get("nvr_id") or "").strip()
            try:
                channel = int(data.get("channel"))
            except (TypeError, ValueError):
                return self._json({"error": "canal invalide"}, 400)
            nom = " ".join(str(data.get("name") or "").split())      # espaces multiples compresses
            if not nom:
                return self._json({"error": "le nom ne peut pas etre vide"}, 400)
            if len(nom) > 32:
                return self._json({"error": f"32 caracteres maximum (recu {len(nom)})"}, 400)
            if any(ord(ch) < 32 or ord(ch) == 127 for ch in nom):
                return self._json({"error": "caractere de controle refuse"}, 400)
            nvr = next((n for n in store.nvrs() if n["nvr_id"] == nvr_id), None)
            if nvr is None:
                return self._json({"error": "NVR inconnu"}, 404)
            import isapi
            cli = isapi.IsapiClient(nvr["ip"], nvr["port"] or 80, s.user, s.password, timeout=20)
            try:
                desc = cli.channel_descriptor(channel)
            except isapi.IsapiError as e:
                cli.close()
                return self._json({"error": f"canal illisible sur le NVR : {e}"}, 502)

            # 1) La camera elle-meme : sur les modeles recents, son nom ecrase celui du NVR.
            cam_ok, cam_err = False, None
            if desc["ip"] and desc["protocol"].upper() in ("", "HIKVISION"):
                cam = isapi.IsapiClient(desc["ip"], desc["port"], desc["user"] or s.user,
                                        s.password, timeout=15)
                try:
                    cam_res = cam.rename_video_input(desc["src_input"], nom)
                    cam_ok = cam_res["ok"]
                    if not cam_ok:
                        cam_err = f"la camera a rendu {cam_res['new']!r}"
                except isapi.IsapiError as e:
                    cam_err = str(e)
                finally:
                    cam.close()

            # 2) Le NVR : nom du canal IP (suffit pour les modeles qui l'acceptent).
            nvr_err = None
            try:
                cli.rename_channel(channel, nom)
            except isapi.IsapiError as e:
                nvr_err = str(e)

            # 3) Verification finale sur le NVR : c'est lui que le dashboard affiche.
            actuel, _ = "", None
            for _ in range(6):
                try:
                    actuel = cli.channel_name(channel)
                except isapi.IsapiError as e:
                    nvr_err = nvr_err or str(e)
                    actuel = ""
                if actuel == nom:
                    break
                time.sleep(0.5)
            cli.close()

            if actuel != nom:
                details = []
                if cam_err:
                    details.append(f"camera {desc['ip']} : {cam_err}")
                if nvr_err:
                    details.append(f"NVR : {nvr_err}")
                log.error("renommage %s CH%s : non applique (%r), %s", nvr_id, channel, actuel, " ; ".join(details))
                return self._json({"error": "renommage non applique"
                                            + (" (" + " ; ".join(details) + ")" if details else ""),
                                   "camera_ok": cam_ok, "nvr": actuel}, 502)

            store.set_camera_name(nvr_id, channel, nom)
            store.add_event(nvr_id, channel, "CAMERA_RENAMED", desc["name"], nom,
                            f"depuis le dashboard (camera={cam_ok})")
            log.info("renommage %s CH%s : %r -> %r (camera=%s, client %s)",
                     nvr_id, channel, desc["name"], nom, cam_ok, self.client_address[0])
            return self._json({"ok": True, "old": desc["name"], "name": nom, "camera": cam_ok})

        def _lens(self):
            """Enregistre la focale d'une camera (donnee locale, aucun ecriture sur le NVR)."""
            data = self._corps_json()
            if not isinstance(data, dict):
                return self._json({"error": "corps JSON invalide"}, 400)
            nvr_id = str(data.get("nvr_id") or "").strip()
            try:
                channel = int(data.get("channel"))
            except (TypeError, ValueError):
                return self._json({"error": "canal invalide"}, 400)
            focale = normaliser_focale(data.get("lens"))
            if focale is None:
                return self._json({"error": "focale invalide : attendu 4, 4mm, 2.8mm ou 2.8-12mm"}, 400)
            nvr = next((n for n in store.nvrs() if n["nvr_id"] == nvr_id), None)
            if nvr is None:
                return self._json({"error": "NVR inconnu"}, 404)
            store.set_camera_lens(nvr_id, channel, focale)
            log.info("focale %s CH%s = %r (client %s)", nvr_id, channel, focale or "effacee",
                     self.client_address[0])
            return self._json({"ok": True, "lens": focale})

        def do_POST(self):
            path = urlparse(self.path).path
            if not self._authorized():
                return self._json({"error": "jeton d'acces requis"}, 401)
            if path == "/api/camera/lens":
                return self._lens()
            if path == "/api/camera/rename":
                return self._rename()
            if path == "/api/refresh":
                monitor.wake.set()   # declenche un cycle immediat (actualisation manuelle, spec §5)
                return self._json({"ok": True, "message": "cycle declenche"})
            if path == "/api/export":
                return self._export()
            if path == "/api/tokens":
                if not self._est_admin():
                    return self._json({"error": "reserve au super administrateur"}, 403)
                return self._api_tokens_create()
            self._json({"error": "introuvable"}, 404)

        def do_DELETE(self):
            path = urlparse(self.path).path
            if not self._authorized():
                return self._json({"error": "jeton d'acces requis"}, 401)
            m = re.fullmatch(r"/api/tokens/(\d+)", path)
            if m:
                if not self._est_admin():
                    return self._json({"error": "reserve au super administrateur"}, 403)
                return self._api_tokens_revoke({"id": int(m.group(1))})
            self._json({"error": "introuvable"}, 404)

        def _export(self):
            """Genere le rapport Excel depuis la base et renvoie son nom (bouton du dashboard)."""
            import export_excel
            s = monitor.settings
            out = s.reports_dir / f"rapport_cctv_{datetime.now():%Y%m%d_%H%M}.xlsx"
            try:
                export_excel.export_excel(s.excel_template, out, store.summary(),
                                          store.cameras(), store.events(limit=500))
            except Exception as e:
                log.exception("generation du rapport echouee")
                return self._json({"error": f"{type(e).__name__}: {e}"}, 500)
            log.info("rapport genere : %s", out.name)
            return self._json({"ok": True, "file": out.name, "url": "/reports/" + out.name})

        def _api_tokens_list(self):
            tokens = store.list_tokens()
            return self._json({"tokens": tokens})

        def _api_tokens_create(self):
            data = self._corps_json() or {}
            label = (data.get("label") or "").strip() or "sans label"
            token = store.create_token(label)
            log.info("jeton cree : label=%s", label)
            return self._json({"ok": True, "token": token, "label": label,
                                "message": "Copiez ce token maintenant : il ne sera plus affiche."})

        def _api_tokens_revoke(self, data):
            tid = int(data.get("id", 0))
            if not tid:
                return self._json({"error": "id requis"}, 400)
            n = store.revoke_token(tid)
            if n:
                log.info("jeton %s revoque", tid)
                return self._json({"ok": True})
            return self._json({"error": "jeton introuvable ou deja revoque"}, 404)

    return Handler


EVENT_COLS = [
    ("ts", "Date et heure (locale)"),
    ("nvr_name", "NVR"),
    ("channel", "Canal"),
    ("camera_name", "Caméra"),
    ("type", "Événement"),
    ("old_value", "Ancien"),
    ("new_value", "Nouveau"),
    ("detail", "Détail"),
]


def _entier(valeur, defaut):
    """Convertit le premier element d'une liste de parametres en entier (defaut si invalide)."""
    try:
        return int((valeur or [defaut])[0])
    except (TypeError, ValueError):
        return defaut


def events_csv(rows):
    """Historique au format CSV (separateur ';' + BOM : ouverture directe dans Excel)."""
    buf = io.StringIO()
    w = csv.writer(buf, delimiter=";")
    w.writerow([h for _, h in EVENT_COLS])
    for r in rows:
        vals = []
        for k, _ in EVENT_COLS:
            v = r.get(k)
            if k == "ts" and v:
                try:                       # horodatage UTC stocke -> heure locale lisible
                    v = datetime.fromisoformat(str(v)).astimezone().strftime("%Y-%m-%d %H:%M:%S")
                except ValueError:
                    pass
            vals.append("" if v is None else str(v))
        w.writerow(vals)
    return "\ufeff" + buf.getvalue()


def capture_image(settings, nvr_row, channel, timeout=15):
    """Capture JPEG d'un canal : priorite a la camera (pleine resolution), repli sur le NVR.

    Mesure sur ce parc : le NVR renvoie un JPEG 704x576 (sous-flux) quel que soit le canal
    demande, alors que la camera renvoie 1920x1080. Pour un usage d'identification, il faut
    donc interroger la camera elle-meme.
    """
    import isapi
    cli = isapi.IsapiClient(nvr_row["ip"], nvr_row["port"] or 80,
                            settings.user, settings.password, timeout=timeout)
    try:
        try:
            desc = cli.channel_descriptor(channel)
        except isapi.IsapiError:
            desc = None
        if desc and desc["ip"] and desc["protocol"].upper() in ("", "HIKVISION"):
            cam = isapi.IsapiClient(desc["ip"], desc["port"], desc["user"] or settings.user,
                                    settings.password, timeout=timeout)
            try:
                return cam.snapshot(desc["src_input"], main_stream=True), "camera"
            except isapi.IsapiError as e:
                log.info("capture directe impossible sur %s : %s (repli sur le NVR)", desc["ip"], e)
            finally:
                cam.close()
        return cli.snapshot(channel), "nvr"
    finally:
        cli.close()


def save_snapshot(reports_dir, nvr_id: str, channel: int, data: bytes, reason: str = "") -> Path:
    """Enregistre une capture dans reports/snapshots/<AAAA-MM-JJ>/. Retourne le chemin ecrit."""
    day = datetime.now().strftime("%Y-%m-%d")
    folder = Path(reports_dir) / "snapshots" / day
    folder.mkdir(parents=True, exist_ok=True)
    tag = re.sub(r"[^\w.-]+", "_", str(nvr_id))[:30]
    suffix = f"_{reason}" if reason else ""
    path = folder / f"{datetime.now():%H%M%S}_{tag}_CH{channel:03d}{suffix}.jpg"
    path.write_bytes(data)
    return path


def prune_snapshots(reports_dir, retention_days: int) -> int:
    """Supprime les dossiers de captures plus vieux que la retention (0 = conservation)."""
    if retention_days <= 0:
        return 0
    root = Path(reports_dir) / "snapshots"
    if not root.is_dir():
        return 0
    limite = (datetime.now() - timedelta(days=retention_days)).date()
    n = 0
    for dossier in root.iterdir():
        if not dossier.is_dir():
            continue
        try:
            jour = datetime.strptime(dossier.name, "%Y-%m-%d").date()
        except ValueError:
            continue
        if jour < limite:
            for f in dossier.iterdir():
                if f.is_file():
                    f.unlink(missing_ok=True)
            try:
                dossier.rmdir()
                n += 1
            except OSError:
                pass
    return n


CLASSES_MP = (1, 2, 3, 4, 5, 6, 8, 12, 16, 24, 32)


def normaliser_focale(valeur):
    """'4', '4mm', '2,8 mm', '2.8-12mm' -> '4mm', '2.8mm', '2.8-12mm'.

    Retourne "" pour effacer la valeur, None si la saisie n'est pas une focale.
    """
    t = str(valeur or "").strip().lower().replace(",", ".").replace(" ", "")
    if not t:
        return ""
    if t.endswith("mm"):
        t = t[:-2]
    m = re.fullmatch(r"(\d{1,2}(?:\.\d)?)(?:-(\d{1,2}(?:\.\d)?))?", t)
    if not m:
        return None
    return f"{m.group(1)}-{m.group(2)}mm" if m.group(2) else f"{m.group(1)}mm"


def definition_mp(width, height) -> str:
    """Classe commerciale la plus proche (2, 4, 8 MP...) depuis la resolution reelle du flux."""
    try:
        pixels = int(width) * int(height)
    except (TypeError, ValueError):
        return ""
    if pixels <= 0:
        return ""
    mp = pixels / 1_000_000
    return f"{min(CLASSES_MP, key=lambda c: abs(c - mp))} MP"


CSV_COLS = [("nvr_name", "NVR"), ("nvr_ip", "NVR IP"), ("channel", "Canal"), ("name", "Camera"), ("ip", "IP camera"),
            ("mac", "MAC"), ("model", "Modele"), ("width", "Largeur (px)"), ("height", "Hauteur (px)"),
            ("definition", "Definition"), ("lens", "Focale"), ("serial", "N serie"), ("status", "Statut"), ("recording", "Enregistrement"),
            ("detect", "Detail"), ("last_seen", "Derniere vue (UTC)"), ("last_status_change", "Dernier changement (UTC)"),
            ("present", "Present dans le NVR")]


def cameras_csv(rows):
    buf = io.StringIO()
    w = csv.writer(buf, delimiter=";")
    w.writerow([h for _, h in CSV_COLS])
    for r in rows:
        valeurs = []
        for k, _ in CSV_COLS:
            if k == "definition":
                valeurs.append(definition_mp(r.get("width"), r.get("height")) or "UNKNOWN")
            else:
                valeurs.append("UNKNOWN" if r.get(k) is None else r.get(k))
        w.writerow(valeurs)
    return "\ufeff" + buf.getvalue()   # BOM : ouverture correcte dans Excel


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--once", action="store_true", help="un seul cycle puis quitter")
    args = ap.parse_args()

    settings = load_settings()
    setup_logging(settings.log_dir)
    settings.db_path.parent.mkdir(parents=True, exist_ok=True)
    store = Store(settings.db_path)
    monitor = Monitor(settings, store)
    log.info("demarrage : %d NVR configures, polling %ds, base %s", len(settings.nvrs), settings.poll_interval, settings.db_path)

    if args.once:
        g = monitor.run_cycle()
        print(json.dumps(store.summary(), ensure_ascii=False, indent=2, default=str))
        return 0 if g["nvr_reachable"] else 1

    # Windows autorise deux processus a se lier au meme port : les reponses deviennent
    # incoherentes (une instance ancienne repond a la place de la nouvelle). On refuse
    # de demarrer si un service repond deja sur ce port.
    _hote = "127.0.0.1" if settings.dashboard_host in ("0.0.0.0", "", "::") else settings.dashboard_host
    try:
        with socket.create_connection((_hote, settings.dashboard_port), timeout=1.0):
            log.error("port %d deja occupe : une autre instance repond deja sur %s. Arret.",
                      settings.dashboard_port, _hote)
            return 3
    except OSError:
        pass

    try:
        httpd = ThreadingHTTPServer((settings.dashboard_host, settings.dashboard_port), make_handler(monitor))
    except OSError as e:
        log.error("port %d indisponible (%s) : une instance tourne deja ?", settings.dashboard_port, e)
        return 2
    threading.Thread(target=monitor.loop, name="monitor", daemon=True).start()
    # 0.0.0.0 n'est pas une adresse ouvrable : afficher une adresse utile.
    if settings.dashboard_host == "0.0.0.0":
        url_hote, expose = "127.0.0.1 (ou l'IP de ce PC)", True
    else:
        url_hote = settings.dashboard_host
        expose = settings.dashboard_host not in ("127.0.0.1", "localhost", "::1")
    log.info("dashboard : http://%s:%d", url_hote, settings.dashboard_port)
    if expose and not settings.dashboard_token:
        log.warning("dashboard EXPOSE sur le reseau SANS jeton : renseigner DASHBOARD_TOKEN dans config/.env")
    elif expose:
        log.info("acces protege par jeton : ouvrir http://%s:%d/?token=...", url_hote, settings.dashboard_port)
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        log.info("arret demande")
    finally:
        monitor.running.clear()
        monitor.wake.set()
        httpd.server_close()
    return 0


if __name__ == "__main__":
    sys.exit(main())

"""Base SQLite : source de verite (spec §6). Inventaire, etat courant, historique des changements, cycles.

Regles :
- une camera n'est JAMAIS supprimee (OFFLINE, NVR en panne ou retiree du NVR => conservee, marquee) ;
- NVR injoignable => statut des cameras UNKNOWN, derniere vue et autres donnees conservees ;
- une valeur absente ne remplace jamais une valeur connue (nom, IP, modele...).
"""
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
import json
import sqlite3
import threading

SCHEMA = """
CREATE TABLE IF NOT EXISTS nvrs (
    nvr_id TEXT PRIMARY KEY, ip TEXT NOT NULL, port INTEGER,
    device_name TEXT, model TEXT, serial TEXT, firmware TEXT, mac TEXT,
    reachable INTEGER DEFAULT 0, last_ok TEXT, last_error TEXT, hdd_json TEXT,
    first_detected TEXT, updated_at TEXT
);
CREATE TABLE IF NOT EXISTS cameras (
    nvr_id TEXT NOT NULL, channel INTEGER NOT NULL,
    name TEXT, ip TEXT, mac TEXT, model TEXT, serial TEXT, firmware TEXT,
    status TEXT DEFAULT 'UNKNOWN', recording TEXT DEFAULT 'UNKNOWN', detect TEXT, bitrate INTEGER,
    width INTEGER, height INTEGER,
    lens TEXT,                       -- focale, saisie par l'utilisateur (non exposee par l'ISAPI)
    present INTEGER DEFAULT 1,
    first_detected TEXT, last_detected TEXT, last_seen TEXT,
    last_status_change TEXT, last_recording_change TEXT,
    PRIMARY KEY (nvr_id, channel)
);
CREATE TABLE IF NOT EXISTS events (
    id INTEGER PRIMARY KEY AUTOINCREMENT, ts TEXT NOT NULL,
    nvr_id TEXT, channel INTEGER, type TEXT NOT NULL,
    old_value TEXT, new_value TEXT, detail TEXT
);
CREATE INDEX IF NOT EXISTS idx_events_ts ON events(ts);
CREATE TABLE IF NOT EXISTS cycles (
    id INTEGER PRIMARY KEY AUTOINCREMENT, ts TEXT NOT NULL, duration_ms INTEGER,
    nvr_ok INTEGER, nvr_fail INTEGER, cameras INTEGER, online INTEGER, offline INTEGER,
    unknown INTEGER, errors_json TEXT
);
CREATE TABLE IF NOT EXISTS tokens (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    token_hash TEXT UNIQUE NOT NULL,
    label TEXT DEFAULT '',
    created_at TEXT NOT NULL DEFAULT (datetime('now','localtime')),
    last_used_at TEXT,
    revoked_at TEXT
);
CREATE INDEX IF NOT EXISTS idx_tokens_hash ON tokens(token_hash);
"""


def now():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class Store:
    def __init__(self, path):
        self.path = str(path)
        self._lock = threading.Lock()
        with self.conn() as c:
            c.executescript(SCHEMA)
            # migration des bases existantes (la resolution a ete ajoutee apres coup)
            colonnes = {r[1] for r in c.execute("PRAGMA table_info(cameras)")}
            for nom, typ in (("width", "INTEGER"), ("height", "INTEGER"), ("lens", "TEXT")):
                if nom not in colonnes:
                    c.execute(f"ALTER TABLE cameras ADD COLUMN {nom} {typ}")

    @contextmanager
    def conn(self):
        c = sqlite3.connect(self.path, timeout=30)
        c.row_factory = sqlite3.Row
        try:
            yield c
            c.commit()
        finally:
            c.close()

    # ------------------------------------------------------------------ ecriture
    def apply_snapshot(self, snap) -> dict:
        """Integre un instantane NVR. Retourne des compteurs d'evenements generes."""
        ts = snap.ts
        counts = {"events": 0, "went_offline": []}
        with self._lock, self.conn() as c:
            def event(type_, ch=None, old=None, new=None, detail=None):
                c.execute("INSERT INTO events(ts,nvr_id,channel,type,old_value,new_value,detail) VALUES(?,?,?,?,?,?,?)",
                          (ts, snap.nvr_id, ch, type_, old, new, detail))
                counts["events"] += 1

            # --- NVR
            prev = c.execute("SELECT * FROM nvrs WHERE nvr_id=?", (snap.nvr_id,)).fetchone()
            d = snap.device
            err = "; ".join(snap.errors) or None
            if prev is None:
                c.execute("""INSERT INTO nvrs(nvr_id,ip,port,device_name,model,serial,firmware,mac,reachable,last_ok,
                             last_error,hdd_json,first_detected,updated_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                          (snap.nvr_id, snap.ip, snap.port, d.get("device_name"), d.get("model"), d.get("serial"),
                           d.get("firmware"), d.get("mac"), int(snap.reachable), ts if snap.reachable else None,
                           err, json.dumps(snap.hdd) if snap.hdd else None, ts, ts))
            else:
                if bool(prev["reachable"]) != snap.reachable:
                    event("NVR_ONLINE" if snap.reachable else "NVR_UNREACHABLE", detail=err)
                c.execute("""UPDATE nvrs SET ip=?, port=?,
                             device_name=COALESCE(?,device_name), model=COALESCE(?,model), serial=COALESCE(?,serial),
                             firmware=COALESCE(?,firmware), mac=COALESCE(?,mac), reachable=?,
                             last_ok=CASE WHEN ? THEN ? ELSE last_ok END, last_error=?,
                             hdd_json=COALESCE(?,hdd_json), updated_at=? WHERE nvr_id=?""",
                          (snap.ip, snap.port, d.get("device_name"), d.get("model"), d.get("serial"), d.get("firmware"),
                           d.get("mac"), int(snap.reachable), int(snap.reachable), ts, err,
                           json.dumps(snap.hdd) if snap.hdd else None, ts, snap.nvr_id))

            # --- cameras
            known = {r["channel"]: r for r in c.execute("SELECT * FROM cameras WHERE nvr_id=?", (snap.nvr_id,))}

            if not snap.inventory_ok:
                # Inventaire indisponible : on ne conclut rien sur l'existence ; etat => UNKNOWN, reste conserve.
                for ch, r in known.items():
                    if r["present"] and r["status"] != "UNKNOWN":
                        c.execute("UPDATE cameras SET status='UNKNOWN', recording='UNKNOWN', last_status_change=? "
                                  "WHERE nvr_id=? AND channel=?", (ts, snap.nvr_id, ch))
                        event("STATUS", ch, r["status"], "UNKNOWN", "NVR injoignable")
                return counts

            seen = set()
            for cam in snap.cameras:
                seen.add(cam.channel)
                r = known.get(cam.channel)
                last_seen = ts if cam.status == "ONLINE" else None
                if r is None:
                    c.execute("""INSERT INTO cameras(nvr_id,channel,name,ip,model,serial,firmware,status,recording,detect,
                                 bitrate,width,height,present,first_detected,last_detected,last_seen,last_status_change,last_recording_change)
                                 VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,1,?,?,?,?,?)""",
                              (snap.nvr_id, cam.channel, cam.name, cam.ip, cam.model, cam.serial, cam.firmware,
                               cam.status, cam.recording, cam.detect, cam.bitrate, cam.width, cam.height,
                               ts, ts, last_seen, ts, ts))
                    if prev is not None:   # pas d'evenement au tout premier inventaire
                        event("CAMERA_ADDED", cam.channel, None, cam.status, f"{cam.name} @ {cam.ip}")
                    continue
                if r["status"] != cam.status:
                    event("STATUS", cam.channel, r["status"], cam.status, cam.detect)
                    if cam.status == "OFFLINE" and r["status"] == "ONLINE":
                        # transition ONLINE -> OFFLINE : on veut la derniere image connue
                        counts["went_offline"].append((cam.channel, r["name"]))
                if r["recording"] != cam.recording:
                    event("RECORDING", cam.channel, r["recording"], cam.recording)
                if cam.ip and r["ip"] and cam.ip != r["ip"]:
                    event("IP_CHANGED", cam.channel, r["ip"], cam.ip, "Human Gate : changement d'IP inattendu")
                if not r["present"]:
                    event("CAMERA_RETURNED", cam.channel, None, cam.status)
                c.execute("""UPDATE cameras SET name=COALESCE(?,name), ip=COALESCE(?,ip), model=COALESCE(?,model),
                             serial=COALESCE(?,serial), firmware=COALESCE(?,firmware), status=?, recording=?, detect=?,
                             bitrate=?, width=COALESCE(?,width), height=COALESCE(?,height),
                             present=1, last_detected=?, last_seen=COALESCE(?,last_seen),
                             last_status_change=CASE WHEN status<>? THEN ? ELSE last_status_change END,
                             last_recording_change=CASE WHEN recording<>? THEN ? ELSE last_recording_change END
                             WHERE nvr_id=? AND channel=?""",
                          (cam.name, cam.ip, cam.model, cam.serial, cam.firmware, cam.status, cam.recording, cam.detect,
                           cam.bitrate, cam.width, cam.height, ts, last_seen, cam.status, ts,
                           cam.recording, ts, snap.nvr_id, cam.channel))

            # cameras qui ne figurent plus dans l'inventaire du NVR : conservees, marquees absentes
            for ch, r in known.items():
                if ch not in seen and r["present"]:
                    c.execute("UPDATE cameras SET present=0, status='UNKNOWN', recording='UNKNOWN', last_status_change=? "
                              "WHERE nvr_id=? AND channel=?", (ts, snap.nvr_id, ch))
                    event("CAMERA_REMOVED_FROM_NVR", ch, r["status"], "UNKNOWN", f"{r['name']} @ {r['ip']}")
        return counts

    def record_cycle(self, snaps, duration_ms):
        s = self.summary()["global"]
        errors = {x.nvr_id: x.errors for x in snaps if x.errors}
        with self._lock, self.conn() as c:
            c.execute("INSERT INTO cycles(ts,duration_ms,nvr_ok,nvr_fail,cameras,online,offline,unknown,errors_json) "
                      "VALUES(?,?,?,?,?,?,?,?,?)",
                      (now(), duration_ms, sum(x.reachable for x in snaps), sum(not x.reachable for x in snaps),
                       s["total"], s["online"], s["offline"], s["unknown"], json.dumps(errors, ensure_ascii=False)))

    def prune(self, retention_days: int = 90) -> int:
        """Supprime les evenements et cycles plus vieux que la retention (en jours).

        Les cameras et les NVR ne sont jamais supprimes : seule la memoire historique est bornee.
        """
        if retention_days <= 0:
            return 0
        cutoff = (datetime.now(timezone.utc) - timedelta(days=retention_days)).isoformat(timespec="seconds")
        with self._lock, self.conn() as c:
            n = c.execute("DELETE FROM events WHERE ts < ?", (cutoff,)).rowcount
            m = c.execute("DELETE FROM cycles WHERE ts < ?", (cutoff,)).rowcount
        return n + m

    # ------------------------------------------------------------------ lecture
    def add_event(self, nvr_id, channel, type_, old=None, new=None, detail=None):
        """Trace une operation faite depuis le dashboard (ex. renommage)."""
        ts = datetime.now(timezone.utc).isoformat(timespec="seconds")
        with self._lock, self.conn() as c:
            c.execute("INSERT INTO events(ts,nvr_id,channel,type,old_value,new_value,detail) "
                      "VALUES(?,?,?,?,?,?,?)", (ts, nvr_id, channel, type_, old, new, detail))

    def set_camera_lens(self, nvr_id, channel, lens):
        """Enregistre la focale saisie (donnee locale : le materiel ne l'expose pas)."""
        with self._lock, self.conn() as c:
            c.execute("UPDATE cameras SET lens=? WHERE nvr_id=? AND channel=?",
                      (lens or None, nvr_id, channel))

    def set_camera_name(self, nvr_id, channel, name):
        """Reflete tout de suite un nom deja applique au NVR (sans attendre le cycle suivant)."""
        with self._lock, self.conn() as c:
            c.execute("UPDATE cameras SET name=? WHERE nvr_id=? AND channel=?", (name, nvr_id, channel))

    def nvrs(self):
        with self.conn() as c:
            return [dict(r) for r in c.execute("SELECT * FROM nvrs ORDER BY ip")]

    def cameras(self):
        with self.conn() as c:
            return [dict(r) for r in c.execute("""
                SELECT c.*, COALESCE(n.device_name, n.nvr_id) AS nvr_name, n.ip AS nvr_ip
                FROM cameras c JOIN nvrs n ON n.nvr_id=c.nvr_id ORDER BY n.ip, c.channel""")]

    def events(self, limit=200, days=None):
        """Evenements les plus recents, bornes a N jours en arriere si demande."""
        where, params = "", []
        if days and days > 0:
            where = "WHERE e.ts >= ?"
            params.append((datetime.now(timezone.utc) - timedelta(days=days)).isoformat(timespec="seconds"))
        params.append(limit)
        with self.conn() as c:
            return [dict(r) for r in c.execute(f"""
                SELECT e.*, COALESCE(n.device_name, e.nvr_id) AS nvr_name, cam.name AS camera_name, cam.ip AS camera_ip
                FROM events e LEFT JOIN nvrs n ON n.nvr_id=e.nvr_id
                LEFT JOIN cameras cam ON cam.nvr_id=e.nvr_id AND cam.channel=e.channel
                {where}
                ORDER BY e.id DESC LIMIT ?""", params)]

    def events_count(self, days=None) -> int:
        """Nombre total d'evenements sur la periode (independant de la limite d'affichage)."""
        where, params = "", []
        if days and days > 0:
            where = "WHERE ts >= ?"
            params.append((datetime.now(timezone.utc) - timedelta(days=days)).isoformat(timespec="seconds"))
        with self.conn() as c:
            return c.execute(f"SELECT COUNT(*) FROM events {where}", params).fetchone()[0]

    def last_cycle(self):
        with self.conn() as c:
            r = c.execute("SELECT * FROM cycles ORDER BY id DESC LIMIT 1").fetchone()
            return dict(r) if r else None

    def summary(self):
        with self.conn() as c:
            per = [dict(r) for r in c.execute("""
                SELECT n.nvr_id, COALESCE(n.device_name, n.nvr_id) AS nvr_name, n.ip, n.model, n.firmware, n.reachable,
                       n.last_ok, n.last_error, n.hdd_json,
                       COUNT(c.channel) AS total,
                       SUM(c.status='ONLINE') AS online, SUM(c.status='OFFLINE') AS offline,
                       SUM(c.status='UNKNOWN') AS unknown,
                       SUM(c.recording='RECORDING') AS recording, SUM(c.recording='NOT_RECORDING') AS not_recording
                FROM nvrs n LEFT JOIN cameras c ON c.nvr_id=n.nvr_id AND c.present=1
                GROUP BY n.nvr_id ORDER BY n.ip""")]
            for p in per:
                for k in ("total", "online", "offline", "unknown", "recording", "not_recording"):
                    p[k] = p[k] or 0
                try:
                    p["hdd"] = json.loads(p.pop("hdd_json") or "[]")
                except ValueError:
                    p["hdd"] = []
            g = {k: sum(p[k] for p in per) for k in ("total", "online", "offline", "unknown", "recording", "not_recording")}
            g["nvr_total"] = len(per)
            g["nvr_reachable"] = sum(1 for p in per if p["reachable"])
            # anomalies : meme IP de camera sur plusieurs NVR
            dup = [dict(r) for r in c.execute("""
                SELECT c.ip, GROUP_CONCAT(COALESCE(n.device_name,n.nvr_id) || ' CH' || c.channel, ' / ') AS where_
                FROM cameras c JOIN nvrs n ON n.nvr_id=c.nvr_id
                WHERE c.present=1 AND c.ip IS NOT NULL
                GROUP BY c.ip HAVING COUNT(DISTINCT c.nvr_id) > 1""")]
            return {"nvrs": per, "global": g, "duplicate_ips": dup}

    # ------------------------------------------------------------------ jetons d'acces
    def list_tokens(self):
        with self.conn() as c:
            return [dict(r) for r in c.execute(
                "SELECT id, label, created_at, last_used_at, revoked_at FROM tokens ORDER BY id DESC")]
    
    def create_token(self, label):
        import secrets, hashlib
        token = secrets.token_urlsafe(32)
        token_hash = hashlib.sha256(token.encode()).hexdigest()
        with self.conn() as c:
            c.execute("INSERT INTO tokens (token_hash, label) VALUES (?, ?)", (token_hash, label))
        return token
    
    def revoke_token(self, token_id):
        with self.conn() as c:
            c.execute("UPDATE tokens SET revoked_at = datetime('now','localtime') WHERE id = ? AND revoked_at IS NULL",
                      (token_id,))
            return c.total_changes
    
    def verify_token(self, token):
        import hashlib
        token_hash = hashlib.sha256(token.encode()).hexdigest()
        with self.conn() as c:
            row = c.execute("SELECT id FROM tokens WHERE token_hash = ? AND revoked_at IS NULL", (token_hash,)).fetchone()
            if row:
                c.execute("UPDATE tokens SET last_used_at = datetime('now','localtime') WHERE id = ?", (row[0],))
                return row[0]
            return None

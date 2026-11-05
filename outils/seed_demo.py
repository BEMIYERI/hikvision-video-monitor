"""Fabrique un jeu de demonstration anonyme pour les captures de la landing page.

5 NVR de 64 canaux = 320 cameras, noms neutres (Site 1..5 / Camera 01..64),
aucune adresse reelle, historique de ~21 000 evenements sur 30 jours.

    python outils/seed_demo.py <dossier>        # cree <dossier>/data/demo.db

Le dossier doit ensuite contenir l'executable + config/.env (PORT libre, DB_PATH=data/demo.db).
"""
import json, random, shutil, sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))
import store as store_mod

NVR_N, CH_PAR_NVR, EVENEMENTS = 16, 64, 32400


def seed(dossier):
    dossier = Path(dossier).resolve()
    if (dossier / "data" / "demo.db").exists():
        (dossier / "data" / "demo.db").unlink()
    (dossier / "data").mkdir(parents=True, exist_ok=True)
    s = store_mod.Store(dossier / "data" / "demo.db")
    random.seed(7)

    pool = []
    for m, w, h, f, n in [("DS-2CD1023G2-LIU", 1920, 1080, "4mm", 737),
                          ("DS-2CD1043G2-LIU", 2560, 1440, "8mm", 174),
                          ("DS-2CD1047G2H-LIU", 2560, 1440, "8mm", 82),
                          ("DS-2CD1053G2-LIU", 2880, 1620, "4mm", 31)]:
        pool += [(m, w, h, f)] * n
    random.shuffle(pool)

    ts = datetime.now(timezone.utc).isoformat(timespec="seconds")
    with s.conn() as c:
        k = 0
        for i in range(1, NVR_N + 1):
            nid = f"SITE{i}"
            c.execute("""INSERT INTO nvrs(nvr_id,ip,port,device_name,model,serial,firmware,mac,reachable,
                         last_ok,last_error,hdd_json,first_detected,updated_at)
                         VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                      (nid, f"10.0.{i}.10", 80, f"Site {i}", "DS-7764NI-M4", f"SN{i:04d}0001",
                       "V5.04.020", f"00:11:22:33:44:0{i}", 1, ts, None,
                       json.dumps([{"id": 1, "status": 0, "volume": 11264000, "free": 6180000},
                                   {"id": 2, "status": 0, "volume": 11264000, "free": 4930000}]), ts, ts))
            for ch in range(1, CH_PAR_NVR + 1):
                modele, w, h, focale = pool[k % len(pool)]
                k += 1
                hors = (i % 4 == 0 and ch in (7, 19, 33)) or (i % 3 == 0 and ch == 51)
                c.execute("""INSERT INTO cameras(nvr_id,channel,name,ip,model,serial,firmware,status,recording,
                             detect,bitrate,width,height,lens,present,first_detected,last_detected,last_seen,
                             last_status_change,last_recording_change)
                             VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,1,?,?,?,?,?)""",
                          (nid, ch, f"Camera {ch:02d}", f"10.{i}.{ch // 250 + 1}.{ch % 250 + 1}", modele,
                           f"CN{k:05d}", "V5.8.10" if "1047" in modele else "V5.8.4",
                           "OFFLINE" if hors else "ONLINE", "NOT_RECORDING" if hors else "RECORDING",
                           "MOTION", random.choice([1024, 2048, 4096]), w, h, focale, ts, ts, ts, ts, ts))

        types = [("STATUS", "ONLINE", "OFFLINE"), ("STATUS", "OFFLINE", "ONLINE"),
                 ("RECORDING", "RECORDING", "NOT_RECORDING"), ("RECORDING", "NOT_RECORDING", "RECORDING")]
        lignes = [((datetime.now(timezone.utc) - timedelta(minutes=random.randint(0, 30 * 24 * 60)))
                   .isoformat(timespec="seconds"), f"SITE{random.randint(1, NVR_N)}",
                   random.randint(1, CH_PAR_NVR), *random.choice(types), None) for _ in range(EVENEMENTS)]
        lignes.sort()
        c.executemany("INSERT INTO events(ts,nvr_id,channel,type,old_value,new_value,detail) "
                      "VALUES(?,?,?,?,?,?,?)", lignes)
        c.execute("""INSERT INTO cycles(ts,duration_ms,nvr_ok,nvr_fail,cameras,online,offline,unknown,errors_json)
                     VALUES(?,?,?,?,?,?,?,?,?)""", (ts, 412, NVR_N, 0, NVR_N * CH_PAR_NVR,
                                                    NVR_N * CH_PAR_NVR - 44, 44, 0, "{}"))
    print(f"base de demonstration : {dossier / 'data' / 'demo.db'}")


if __name__ == "__main__":
    seed(sys.argv[1] if len(sys.argv) > 1 else ".")

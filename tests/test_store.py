"""Tests des regles critiques de la spec (base SQLite, aucun acces reseau).

Deux facons de lancer :
    python tests/test_store.py     -> sans dependance
    pytest -q                      -> si pytest est installe
"""
import os
import sys
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from collector import CameraObs, NvrSnapshot   # noqa: E402
from store import Store                        # noqa: E402


def _snap(ts, reachable=True, inventory_ok=True, cams=()):
    device = {"device_name": "SITE-A", "model": "DS"} if reachable else {}
    return NvrSnapshot("N1", "10.0.0.1", 80, reachable, ts, device=device,
                       cameras=list(cams), inventory_ok=inventory_ok)


def _cam(ch, status="ONLINE", rec="RECORDING", ip=None, name=None):
    return CameraObs(ch, name or f"Camera {ch:02d}", ip or f"10.0.1.{ch}", "M", "S", "F", status, rec, "connect", 100)


def _store():
    return Store(os.path.join(tempfile.mkdtemp(), "t.db"))


def test_premier_inventaire_sans_evenement_parasite():
    s = _store()
    s.apply_snapshot(_snap("t1", cams=[_cam(1), _cam(2), _cam(3)]))
    g = s.summary()["global"]
    assert (g["total"], g["online"]) == (3, 3), g
    assert s.events() == [], s.events()


def test_camera_hors_ligne_conserve_derniere_vue():
    s = _store()
    s.apply_snapshot(_snap("t1", cams=[_cam(1), _cam(2), _cam(3)]))
    before = {c["channel"]: c for c in s.cameras()}[2]["last_seen"]
    s.apply_snapshot(_snap("t2", cams=[_cam(1), _cam(2, "OFFLINE", "NOT_RECORDING"), _cam(3)]))
    c2 = {c["channel"]: c for c in s.cameras()}[2]
    assert c2["status"] == "OFFLINE" and c2["last_seen"] == before, c2
    types = [e["type"] for e in s.events()]
    assert "STATUS" in types and "RECORDING" in types, types


def test_nvr_injoignable_conserve_inventaire():
    s = _store()
    s.apply_snapshot(_snap("t1", cams=[_cam(1), _cam(2), _cam(3)]))
    s.apply_snapshot(_snap("t3", reachable=False, inventory_ok=False))
    cams = s.cameras()
    assert len(cams) == 3 and all(c["status"] == "UNKNOWN" for c in cams), cams
    assert all(c["ip"] and c["name"] for c in cams)
    assert s.summary()["nvrs"][0]["nvr_name"] == "SITE-A"
    assert any(e["type"] == "NVR_UNREACHABLE" for e in s.events())


def test_camera_retiree_du_nvr_conservee():
    s = _store()
    s.apply_snapshot(_snap("t1", cams=[_cam(1), _cam(2), _cam(3)]))
    s.apply_snapshot(_snap("t4", cams=[_cam(1), _cam(2)]))
    c3 = {c["channel"]: c for c in s.cameras()}[3]
    assert c3["present"] == 0 and s.summary()["global"]["total"] == 2, c3
    assert any(e["type"] == "CAMERA_REMOVED_FROM_NVR" for e in s.events())


def test_valeur_absente_ne_remplace_pas_le_connu_et_ip_signalee():
    s = _store()
    s.apply_snapshot(_snap("t1", cams=[_cam(1), _cam(2)]))
    s.apply_snapshot(_snap("t5", cams=[CameraObs(1, None, None, None, None, None, "ONLINE", "RECORDING"),
                                      _cam(2, ip="10.0.9.9")]))
    by = {c["channel"]: c for c in s.cameras()}
    assert by[1]["name"] == "Camera 01" and by[1]["ip"] == "10.0.1.1", by[1]
    assert any(e["type"] == "IP_CHANGED" for e in s.events())


def test_prune_supprime_les_evenements_anciens():
    s = _store()
    s.apply_snapshot(_snap("2000-01-01T00:00:00+00:00", cams=[_cam(1)]))
    s.apply_snapshot(_snap("2000-01-01T01:00:00+00:00", cams=[_cam(1, "OFFLINE")]))
    assert s.events(), "des evenements doivent exister avant la purge"
    assert s.prune(90) > 0
    assert s.events() == []


def test_passage_hors_ligne_signale_pour_capture():
    """Une transition ONLINE -> OFFLINE est remontee, pour capturer la derniere image."""
    s = _store()
    s.apply_snapshot(_snap("t1", cams=[_cam(1), _cam(2)]))
    res = s.apply_snapshot(_snap("t2", cams=[_cam(1), _cam(2, "OFFLINE", "NOT_RECORDING")]))
    assert res.get("went_offline") == [(2, "Camera 02")], res.get("went_offline")
    # une camera deja hors ligne ne doit pas etre remontee une seconde fois
    res2 = s.apply_snapshot(_snap("t3", cams=[_cam(1), _cam(2, "OFFLINE", "NOT_RECORDING")]))
    assert res2.get("went_offline") == [], res2.get("went_offline")


def test_fenetre_historique_et_total():
    """events(days) borne la periode ; events_count renvoie le total de la periode (1 mois inclus)."""
    s = _store()
    maintenant = datetime.now(timezone.utc)
    with s.conn() as c:
        # ordre d'insertion = ordre chronologique, comme en production
        for jours, etiquette in ((60, "VIEUX"), (10, "DIX_JOURS"), (1, "RECENT")):
            ts = (maintenant - timedelta(days=jours)).isoformat(timespec="seconds")
            c.execute("""INSERT INTO events(ts, nvr_id, channel, type, old_value, new_value, detail)
                         VALUES (?,?,?,?,?,?,?)""", (ts, "N1", 1, etiquette, "OFFLINE", "ONLINE", None))
    assert s.events_count(30) == 2, s.events_count(30)        # 1 j + 10 j, pas le vieux de 60 j
    assert s.events_count(7) == 1
    assert s.events_count(90) == 3                             # une periode large le recupere
    assert s.events_count(0) == 3, "0 doit signifier 'sans borne'"
    recents = s.events(1000, 30)
    assert [e["type"] for e in recents] == ["RECENT", "DIX_JOURS"], [e["type"] for e in recents]
    assert recents[0]["ts"] >= recents[1]["ts"], "du plus recent au plus ancien"
    assert len(s.events(1, 30)) == 1, "la limite d'affichage ne doit pas changer le total"


def test_renommage_reflete_en_base_et_trace():
    """set_camera_name met a jour la camera ; add_event trace l'operation dans l'historique."""
    s = _store()
    s.apply_snapshot(_snap("t1", cams=[_cam(1)]))
    s.set_camera_name("N1", 1, "Entree principale")
    cam = next(c for c in s.cameras() if c["channel"] == 1)
    assert cam["name"] == "Entree principale", cam["name"]
    avant = s.events_count(0)
    s.add_event("N1", 1, "CAMERA_RENAMED", "Camera 01", "Entree principale", "test")
    assert s.events_count(0) == avant + 1
    dernier = s.events(1, 0)[0]
    assert dernier["type"] == "CAMERA_RENAMED", dernier["type"]
    assert (dernier["old_value"], dernier["new_value"]) == ("Camera 01", "Entree principale")


if __name__ == "__main__":
    tests = [fn for name, fn in sorted(globals().items()) if name.startswith("test_") and callable(fn)]
    failed = []
    for fn in tests:
        try:
            fn()
            print(f"OK    {fn.__name__}")
        except AssertionError as exc:
            failed.append(fn.__name__)
            print(f"ECHEC {fn.__name__}: {exc}")
    print(f"\n{len(tests) - len(failed)}/{len(tests)} tests OK")
    sys.exit(1 if failed else 0)

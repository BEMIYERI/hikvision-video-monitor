"""Contrat de l'export Excel : le rapport doit rester conforme au modele (aucun acces reseau).

Lancer : python tests/test_export.py   (ou pytest -q si pytest est installe)
"""
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from openpyxl import load_workbook        # noqa: E402
from export_excel import export_excel     # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
TEMPLATE = ROOT / "docs" / "CCTV_TEMPLATE.xlsx"
NVR_NAME = "SITE-A"


def _summary():
    return {"nvrs": [{"nvr_name": NVR_NAME, "online": 3, "offline": 1, "total": 4}], "global": {}}


def _cameras():
    return [
        {"nvr_id": "N1", "nvr_name": NVR_NAME, "channel": 1, "name": "Camera 01",
         "status": "ONLINE", "recording": "RECORDING"},
        {"nvr_id": "N1", "nvr_name": NVR_NAME, "channel": 2, "name": "Camera 02",
         "status": "OFFLINE", "recording": "NOT_RECORDING"},
    ]


def _events():
    return [
        {"ts": "2026-10-16T09:00:00+00:00", "type": "STATUS", "nvr_name": NVR_NAME, "channel": 1,
         "camera_name": "Camera 01", "old_value": "OFFLINE", "new_value": "ONLINE"},
        {"ts": "2026-10-16T08:30:00+00:00", "type": "RECORDING", "nvr_name": NVR_NAME, "channel": 2,
         "camera_name": "Camera 02", "old_value": "RECORDING", "new_value": "NOT_RECORDING"},
    ]


def _build():
    out = Path(tempfile.mkdtemp()) / "rapport_test.xlsx"
    export_excel(TEMPLATE, out, _summary(), _cameras(), _events())
    return load_workbook(out)


def test_feuilles_du_modele_conservees():
    """L'export ne doit ni ajouter ni renommer de feuille."""
    assert _build().sheetnames == ["Summary", "Daily Monitoring Log", "Maintenance Report",
                                   "Incident Report", "Camera Performance"]


def test_summary_libelle_et_formules_du_modele():
    ws = _build()["Summary"]
    assert ws.cell(3, 2).value == "64 Channel NVR (" + NVR_NAME + ")"
    assert (ws.cell(3, 3).value, ws.cell(3, 4).value) == (3, 1)
    assert str(ws.cell(3, 5).value).startswith("="), "la formule Total du modele doit etre conservee"
    assert str(ws.cell(8, 3).value).startswith("=SUM"), "les formules de totaux doivent etre conservees"


def test_camera_performance_regles_de_statut():
    ws = _build()["Camera Performance"]
    assert [ws.cell(8, j).value for j in range(1, 8)] == [
        1, "NVR-" + NVR_NAME, NVR_NAME + " CH1 - Camera 01", "GOOD", "ADEQUATE", "WORKING", "NO"]
    assert [ws.cell(9, j).value for j in (4, 5, 6, 7)] == ["UNKNOWN", "UNKNOWN", "NOT WORKING", "YES"]


def test_daily_log_activite_hors_ligne_et_en_ligne():
    ws = _build()["Daily Monitoring Log"]
    assert ws.cell(6, 4).value == "RECORDING"        # OFFLINE -> ONLINE
    assert ws.cell(7, 4).value == "NOT_RECORDING"    # RECORDING -> NOT_RECORDING


def test_daily_log_date_sans_fuseau_horaire():
    """Excel refuse les datetimes avec fuseau : l'erreur levait au save et corrompait le fichier."""
    ws = _build()["Daily Monitoring Log"]
    assert ws.cell(6, 1).value.tzinfo is None


def test_definition_mp_classe_commerciale():
    """La definition affichee est la classe la plus proche de la resolution reelle."""
    from main import definition_mp
    assert definition_mp(2560, 1440) == "4 MP"      # 3.7 MP
    assert definition_mp(1920, 1080) == "2 MP"      # 2.1 MP
    assert definition_mp(3840, 2160) == "8 MP"      # 8.3 MP
    assert definition_mp(3072, 2048) == "6 MP"      # 6.3 MP
    assert definition_mp(2560, 1920) == "5 MP"      # 4.9 MP
    assert definition_mp(None, 1080) == "", "resolution incomplete -> vide"
    assert definition_mp(0, 0) == "", "resolution nulle -> vide"


def test_normaliser_focale():
    """La focale saisie est normalisee ; une saisie non numerique est refusee."""
    from main import normaliser_focale
    assert normaliser_focale("4") == "4mm"
    assert normaliser_focale("4mm") == "4mm"
    assert normaliser_focale(" 2,8 mm ") == "2.8mm"
    assert normaliser_focale("2.8-12mm") == "2.8-12mm"
    assert normaliser_focale("") == "", "vide doit effacer la valeur"
    assert normaliser_focale(None) == ""
    assert normaliser_focale("abc") is None, "texte refuse"
    assert normaliser_focale("4m") is None, "unite incomplete refusee"
    assert normaliser_focale("123mm") is None, "une focale de 123 mm n'existe pas"


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

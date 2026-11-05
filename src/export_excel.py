#!/usr/bin/env python3
"""Export Excel : copie le MODELE CCTV_TEMPLATE.xlsx et injecte les donnees de surveillance.

On ne cree JAMAIS de colonne ni de feuille : on remplace uniquement le contenu des cellules
de donnees du modele. Titres, logos, styles, cellules fusionnees et formules (=C+D, =SUM(...))
sont conserves tels quels, et la liste des NVR vient de la base (aucun nom code en dur).

Feuilles alimentees :
  - Summary              : lignes 3-7 (S/N, libelle NVR, en ligne, hors ligne)
  - Daily Monitoring Log : a partir de la ligne 6 (Date, Heure, Camera, Activite, Type, ...)
  - Camera Performance   : a partir de la ligne 8 (S/N, Division, Camera, qualite, ...)
Les feuilles Maintenance Report et Incident Report restent telles quelles (saisie manuelle).
"""
import datetime
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from openpyxl import load_workbook
from openpyxl.cell.cell import MergedCell

SUM_FIRST_ROW, SUM_ROWS = 3, 5       # Summary : 5 emplacements NVR (lignes 3 a 7)
LOG_FIRST_ROW, LOG_ROWS = 6, 390     # Daily Monitoring Log : lignes 6 a 395
PERF_FIRST_ROW, PERF_ROWS = 8, 330   # Camera Performance : lignes 8 a 337


def _set(ws, row, col, value):
    """Ecrit une cellule. Une cellule fusionnee du modele est laissee intacte (retourne None)."""
    cell = ws.cell(row=row, column=col)
    if isinstance(cell, MergedCell):
        return None
    cell.value = value
    return cell


def nvr_label(nvr_name: str) -> str:
    """Libelle au format du modele : '64 Channel NVR (NOM)'."""
    return f"64 Channel NVR ({nvr_name})"


def activity_of(event: dict) -> str:
    """Etat de la camera au moment de l'evenement : RECORDING ou NOT_RECORDING."""
    kind = (event.get("type") or "").upper()
    new = (event.get("new_value") or "").upper()
    if kind == "RECORDING":
        return "RECORDING" if new == "RECORDING" else "NOT_RECORDING"
    if kind in ("STATUS", "CAMERA_REMOVED_FROM_NVR", "NVR_UNREACHABLE", "CAMERA_ADDED", "CAMERA_RETURNED"):
        return "RECORDING" if new == "ONLINE" else "NOT_RECORDING"
    return "UNKNOWN"


def fill_summary(ws, nvrs):
    """Une ligne par NVR. La colonne E (Total) garde la formule du modele : on n'y touche pas."""
    for offset in range(SUM_ROWS):
        row = SUM_FIRST_ROW + offset
        nvr = nvrs[offset] if offset < len(nvrs) else None
        if nvr is None:                       # moins de NVR que d'emplacements : on vide la ligne
            for col in (1, 2, 3, 4, 6, 7, 8):
                _set(ws, row, col, None)
            continue
        _set(ws, row, 1, offset + 1)                       # S/N
        _set(ws, row, 2, nvr_label(nvr["nvr_name"]))       # libelle (remplace celui du modele)
        _set(ws, row, 3, nvr.get("online") or 0)           # en ligne
        _set(ws, row, 4, nvr.get("offline") or 0)          # hors ligne
        for col in (6, 7, 8):                              # pas de source automatique -> vide
            _set(ws, row, col, None)


def fill_daily_log(ws, events):
    for row in range(LOG_FIRST_ROW, LOG_FIRST_ROW + LOG_ROWS):
        for col in range(1, 8):
            _set(ws, row, col, None)
    for offset, event in enumerate(events[:LOG_ROWS]):
        row = LOG_FIRST_ROW + offset
        try:
            dt = datetime.datetime.fromisoformat((event.get("ts") or "").replace("Z", "+00:00"))
        except ValueError:
            dt = datetime.datetime.now(datetime.timezone.utc)
        if dt.tzinfo is not None:
            dt = dt.astimezone().replace(tzinfo=None)   # Excel refuse les datetimes avec fuseau
        where = event.get("camera_name") or f"CH{event.get('channel', '')}"
        if event.get("nvr_name"):
            where = f"{where} ({event['nvr_name']})"
        cell = _set(ws, row, 1, dt)
        if cell is not None:
            cell.number_format = "DD/MM/YYYY"
        _set(ws, row, 2, dt.strftime("%H:%M"))
        _set(ws, row, 3, where)
        _set(ws, row, 4, activity_of(event))
        _set(ws, row, 5, event.get("type") or None)
        _set(ws, row, 6, "Check" if (event.get("type") or "") in ("STATUS", "RECORDING") else None)
        old, new = event.get("old_value") or "", event.get("new_value") or ""
        _set(ws, row, 7, f"{old} -> {new}" if (old or new) else None)


def fill_camera_performance(ws, cameras):
    """Une ligne par camera.

    Regles : qualite d'image et couverture suivent la mise en ligne ; la fonctionnalite exige
    'en ligne ET en enregistrement' ; le support de maintenance suit la mise en ligne.
    """
    for row in range(PERF_FIRST_ROW, PERF_FIRST_ROW + PERF_ROWS):
        for col in range(1, 9):
            _set(ws, row, col, None)
    for offset, cam in enumerate(cameras[:PERF_ROWS]):
        row = PERF_FIRST_ROW + offset
        online = cam.get("status") == "ONLINE"
        recording = cam.get("recording") == "RECORDING"
        nvr = cam.get("nvr_name") or "?"
        _set(ws, row, 1, offset + 1)                                          # S/N
        _set(ws, row, 2, f"NVR-{nvr}")                                        # DIVISION
        _set(ws, row, 3, f"{nvr} CH{cam.get('channel')} - {cam.get('name') or '?'}")
        _set(ws, row, 4, "GOOD" if online else "UNKNOWN")                     # IMAGE QUALITY
        _set(ws, row, 5, "ADEQUATE" if online else "UNKNOWN")                 # COVERAGE AREA
        _set(ws, row, 6, "WORKING" if (online and recording) else "NOT WORKING")
        _set(ws, row, 7, "NO" if online else "YES")                           # MAINTENANCE SUPPORT
        _set(ws, row, 8, None)                                                # REMARKS


def export_excel(template_path, output_path, summary_data, cameras, events):
    wb = load_workbook(template_path)
    fill_summary(wb["Summary"], summary_data.get("nvrs") or [])
    fill_daily_log(wb["Daily Monitoring Log"], events)
    fill_camera_performance(wb["Camera Performance"], cameras)
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    wb.save(output_path)
    return output_path


def main():
    from config import load_settings
    from store import Store

    settings = load_settings()
    if not settings.excel_template.exists():
        print(f"ERREUR: modele introuvable : {settings.excel_template}", file=sys.stderr)
        return 1
    store = Store(settings.db_path)
    out = settings.reports_dir / f"rapport_cctv_{datetime.datetime.now():%Y%m%d_%H%M}.xlsx"
    export_excel(settings.excel_template, out, store.summary(), store.cameras(), store.events(limit=500))
    print(f"Export OK: {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

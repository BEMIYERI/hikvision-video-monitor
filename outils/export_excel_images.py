"""Exporte les feuilles du rapport Excel en PNG, sans les logos du modele.

1. copie le classeur en retirant les images embarquees (logos) ;
2. ouvre la copie dans Excel et capture chaque feuille utile en bitmap haute definition.
"""
import shutil
import time
import sys
from pathlib import Path

import openpyxl
import win32com.client as win32

BASE = Path(r"C:\Users\nanga\projets\hikvision-monitor")
SRC = BASE / "demo" / "rapport_demo.xlsx"
CLEAN = BASE / "demo" / "rapport_public.xlsx"
OUT = BASE / "marketing" / "excel"
OUT.mkdir(parents=True, exist_ok=True)

# --- 1) retirer les images (logos du client) ---
shutil.copy(SRC, CLEAN)
wb = openpyxl.load_workbook(CLEAN)
retirees = 0
for ws in wb.worksheets:
    if getattr(ws, "_images", None):
        retirees += len(ws._images)
        ws._images = []
# retirer les references internes du client (n° de document, date d'edition)
MOTIFS = ("Doc No", "Issue Date", "Document No", "Ref.")
effacees = 0
for ws in wb.worksheets:
    for ligne in ws.iter_rows():
        for cellule in ligne:
            if isinstance(cellule.value, str) and any(m.lower() in cellule.value.lower() for m in MOTIFS):
                cellule.value = None
                effacees += 1
wb.save(CLEAN)
print(f"logos retires : {retirees} | cellules anonymisees : {effacees}")

# --- 2) capture par Excel ---
CIBLES = [
    ("Summary", "excel-01-summary", 8, 8),
    ("Camera Performance", "excel-02-camera-performance", 30, 8),
    ("Daily Monitoring Log", "excel-03-daily-log", 14, 7),
]

xl = win32.DispatchEx("Excel.Application")
xl.Visible = False
xl.DisplayAlerts = False
classeur = xl.Workbooks.Open(str(CLEAN))


def capturer(feuille, nom, lignes, colonnes, essais=3):
    for essai in range(1, essais + 1):
        try:
            ws = classeur.Worksheets(feuille)
            ws.Activate()
            xl.ActiveWindow.Zoom = 200
            zone = ws.Range(ws.Cells(1, 1), ws.Cells(lignes, colonnes))
            zone.Select()
            zone.CopyPicture(1, 2)          # xlScreen, xlBitmap
            graphique = ws.ChartObjects().Add(0, 0, zone.Width * 2, zone.Height * 2)
            graphique.Chart.Paste()
            cible = OUT / f"{nom}.png"
            if cible.exists():
                cible.unlink()
            graphique.Chart.Export(str(cible), "PNG")
            graphique.Delete()
            xl.CutCopyMode = False
            print(f"  {feuille:24s} -> {nom}.png  ({essai} essai)")
            return True
        except Exception as e:
            print(f"  tentative {essai} sur {feuille} : {str(e)[:120]}")
            time.sleep(1.0)
    return False


try:
    for feuille, nom, lignes, colonnes in CIBLES:
        capturer(feuille, nom, lignes, colonnes)
finally:
    classeur.Close(False)
    xl.Quit()

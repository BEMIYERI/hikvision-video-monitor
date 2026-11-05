import sys
from pathlib import Path
base = Path(r"C:\Users\nanga\projets\hikvision-monitor")
lab = base / "demo"
sys.path.insert(0, str(base / "outils"))
sys.path.insert(0, str(base / "src"))
import seed_demo, store as store_mod, export_excel

if not (lab / "data" / "demo.db").exists():
    seed_demo.seed(lab)

s = store_mod.Store(lab / "data" / "demo.db")
sortie = lab / "rapport_demo.xlsx"
export_excel.export_excel(base / "docs" / "CCTV_TEMPLATE.xlsx", sortie, s.summary(), s.cameras(), s.events(limit=500))
print("rapport :", sortie.name, sortie.stat().st_size // 1024, "Ko")

import openpyxl
wb = openpyxl.load_workbook(sortie)
for ws in wb.worksheets:
    print(f"  feuille '{ws.title}' : {ws.max_row} lignes x {ws.max_column} colonnes")
ws = wb["Summary"]
print("Summary B3:B7 :", [ws.cell(row=r, column=2).value for r in range(3, 8)])
print("Summary en-tetes L2 :", [ws.cell(row=2, column=c).value for c in range(1, 9)])

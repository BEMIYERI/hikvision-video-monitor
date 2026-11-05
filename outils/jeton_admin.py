"""Genere le jeton SUPER ADMIN (jeton maitre) et le place dans config/.env.

Ce jeton est le seul a pouvoir creer ou revoquer les jetons individuels.
A lancer une fois a l'installation, et a chaque fois qu'on veut le renouveler.
"""
from pathlib import Path
import re
import secrets
import sys

base = Path(__file__).resolve().parent
env = base / "config" / ".env"
if len(sys.argv) > 1:
    env = Path(sys.argv[1])

if not env.is_file():
    sys.exit(f"ERREUR : {env} introuvable. Lancer ce script depuis le dossier du service.")

jeton = secrets.token_urlsafe(32)
texte = env.read_text(encoding="utf-8")
if re.search(r"^DASHBOARD_TOKEN=.*$", texte, re.M):
    texte = re.sub(r"^DASHBOARD_TOKEN=.*$", f"DASHBOARD_TOKEN={jeton}", texte, count=1, flags=re.M)
else:
    texte = texte.rstrip("\n") + f"\nDASHBOARD_TOKEN={jeton}\n"
env.write_text(texte, encoding="utf-8", newline="\n")

port = "8765"
m = re.search(r"^DASHBOARD_PORT=(\d+)", texte, re.M)
if m:
    port = m.group(1)

print()
print("  Jeton super admin genere et enregistre dans config/.env")
print("  " + "-" * 62)
print(f"  {jeton}")
print("  " + "-" * 62)
print("  Il permet : acces au dashboard + creation/revocation des jetons.")
print("  A conserver pour vous : ne le donnez a personne d'autre.")
print()
print(f"  Redemarrez le service, puis ouvrez :")
print(f"    http://127.0.0.1:{port}/?token={jeton}")
print()

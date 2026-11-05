"""Configuration : lecture de config/.env. Les secrets restent dans cet objet et ne sont jamais journalises."""
from dataclasses import dataclass, field
from pathlib import Path
import sys

from dotenv import dotenv_values

# Emplacement des donnees modifiables (config/, data/, logs/, reports/).
# - en Python : la racine du projet ;
# - en executable PyInstaller : le dossier de l'exe, pour que config/.env, la base et les
#   journaux restent accessibles et modifiables apres installation.
if getattr(sys, "frozen", False):
    ROOT = Path(sys.executable).resolve().parent
    RESOURCES = Path(getattr(sys, "_MEIPASS", ROOT))     # fichiers embarques (static/, docs/)
else:
    ROOT = Path(__file__).resolve().parent.parent
    RESOURCES = ROOT

# Modele Excel : une copie locale (modifiable) prime sur celle embarquee dans l'exe.
_TEMPLATE = ROOT / "docs" / "CCTV_TEMPLATE.xlsx"
if not _TEMPLATE.exists() and (RESOURCES / "docs" / "CCTV_TEMPLATE.xlsx").exists():
    _TEMPLATE = RESOURCES / "docs" / "CCTV_TEMPLATE.xlsx"


@dataclass(frozen=True)
class NvrConfig:
    nvr_id: str          # identifiant de secours (.env) ; le nom affiche vient du NVR (deviceName)
    ip: str
    port: int = 80
    location: str = ""


@dataclass(frozen=True)
class Settings:
    user: str = field(repr=False)
    password: str = field(repr=False)
    nvrs: tuple
    poll_interval: int = 60
    dashboard_host: str = "127.0.0.1"
    dashboard_port: int = 8765
    dashboard_token: str = field(default="", repr=False)   # jeton d'acces si le dashboard sort de 127.0.0.1
    db_path: Path = ROOT / "data" / "cctv_monitoring.db"
    log_dir: Path = ROOT / "logs"
    reports_dir: Path = ROOT / "reports"
    excel_template: Path = _TEMPLATE
    offline_alert_threshold: int = 300
    no_recording_threshold: int = 300
    alert_webhook: str = ""
    retention_days: int = 90
    allow_write: bool = True      # autorise le renommage des cameras cote NVR


def _clean(v):
    return (v or "").strip()


def load_settings(env_file: Path = ROOT / "config" / ".env") -> Settings:
    if not env_file.exists():
        sys.exit(f"ERREUR: {env_file} absent (copier config/.env.example puis remplir NVR_USER / NVR_PASS).")
    env = dotenv_values(env_file)
    user, pwd = _clean(env.get("NVR_USER")), _clean(env.get("NVR_PASS"))
    if not user or not pwd or "A-REMPLIR" in (user + pwd):
        sys.exit("ERREUR: NVR_USER / NVR_PASS non remplis dans config/.env.")
    for label, val in (("NVR_USER", user), ("NVR_PASS", pwd)):
        if val.startswith("<") and val.endswith(">"):
            sys.exit(f"ERREUR: {label} est entoure de < > dans config/.env : retirer les chevrons.")
    nvrs = []
    for i in range(1, 17):
        raw = env.get(f"NVR{i}")
        if not raw:
            continue
        parts = [p.strip() for p in raw.split("|")] + ["", "", "80", ""]
        nvr_id, ip, port, loc = parts[:4]
        if not ip:
            continue
        nvrs.append(NvrConfig(nvr_id or f"NVR{i}", ip, int(port or 80), "" if loc.startswith("<") else loc))
    if not nvrs:
        sys.exit("ERREUR: aucun NVR (NVR1=..., NVR2=...) dans config/.env.")

    def num(key, default):
        try:
            return int(_clean(env.get(key)) or default)
        except ValueError:
            return default

    def path(key, default):
        raw = _clean(env.get(key)) or default
        p = Path(raw)
        return p if p.is_absolute() else ROOT / p

    template = path("EXCEL_TEMPLATE", "docs/CCTV_TEMPLATE.xlsx")
    if not template.exists() and (RESOURCES / "docs" / "CCTV_TEMPLATE.xlsx").exists():
        template = RESOURCES / "docs" / "CCTV_TEMPLATE.xlsx"

    return Settings(
        user=user, password=pwd, nvrs=tuple(nvrs),
        poll_interval=max(15, num("POLL_INTERVAL", 60)),
        dashboard_host=_clean(env.get("DASHBOARD_HOST")) or "127.0.0.1",
        dashboard_port=num("DASHBOARD_PORT", 8765),
        dashboard_token=_clean(env.get("DASHBOARD_TOKEN")),
        db_path=path("DB_PATH", "data/cctv_monitoring.db"),
        reports_dir=path("REPORTS_DIR", "reports"),
        excel_template=template,

        offline_alert_threshold=num("OFFLINE_ALERT_THRESHOLD", 300),
        no_recording_threshold=num("NO_RECORDING_THRESHOLD", 300),
        alert_webhook=_clean(env.get("ALERT_WEBHOOK")),
        retention_days=max(0, num("RETENTION_DAYS", 90)),
        allow_write=_clean(env.get("ALLOW_NVR_WRITE") or "true").lower() in ("1", "true", "oui", "yes", "on"),
    )

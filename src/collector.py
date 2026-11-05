"""Collecte : un instantane par NVR. Contrat de donnees fixe (dataclasses), teste dans tests/.

Regles (spec §12, §17, §20) :
- jamais de camera inventee : l'inventaire vient uniquement de InputProxy/channels ;
- donnee absente -> None (affichee UNKNOWN) ;
- un NVR en echec ne bloque pas les autres (thread par NVR, exception capturee).
"""
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from datetime import datetime, timezone
import logging
import time

from isapi import IsapiClient, IsapiError

log = logging.getLogger("collector")

ONLINE, OFFLINE, UNKNOWN = "ONLINE", "OFFLINE", "UNKNOWN"
RECORDING, NOT_RECORDING = "RECORDING", "NOT_RECORDING"


@dataclass
class CameraObs:
    channel: int
    name: str | None
    ip: str | None
    model: str | None
    serial: str | None
    firmware: str | None
    status: str = UNKNOWN            # ONLINE / OFFLINE / UNKNOWN
    recording: str = UNKNOWN         # RECORDING / NOT_RECORDING / UNKNOWN
    detect: str | None = None        # chanDetectResult (connect, netUnreachable, ...)
    bitrate: int | None = None
    width: int | None = None         # resolution du flux principal (pixels)
    height: int | None = None


@dataclass
class NvrSnapshot:
    nvr_id: str
    ip: str
    port: int
    reachable: bool
    ts: str
    duration_ms: int = 0
    device: dict = field(default_factory=dict)
    cameras: list = field(default_factory=list)   # list[CameraObs] ; vide si inventaire indisponible
    inventory_ok: bool = False                    # False => ne PAS conclure qu'une camera a disparu
    hdd: list = field(default_factory=list)
    errors: list = field(default_factory=list)    # messages courts, sans secret


def _status(proxy, work):
    """Statut de connexion : priorite a InputProxy/status, sinon workingstatus."""
    if proxy is not None and proxy[0] is not None:
        return ONLINE if proxy[0] else OFFLINE
    if work and work.get("online") in (0, 1):
        return ONLINE if work["online"] == 1 else OFFLINE
    return UNKNOWN


def _recording(work):
    if work and work.get("record") in (0, 1):
        return RECORDING if work["record"] == 1 else NOT_RECORDING
    return UNKNOWN


def collect_nvr(nvr, user, password) -> NvrSnapshot:
    t0 = time.time()
    snap = NvrSnapshot(nvr.nvr_id, nvr.ip, nvr.port, reachable=False,
                       ts=datetime.now(timezone.utc).isoformat(timespec="seconds"))
    cli = IsapiClient(nvr.ip, nvr.port, user, password)
    try:
        try:
            snap.device = cli.device_info()
            snap.reachable = True
        except IsapiError as e:
            snap.errors.append(f"deviceInfo: {e}")

        try:
            inventory = cli.proxy_channels()
            snap.reachable = True
            snap.inventory_ok = True
        except IsapiError as e:
            snap.errors.append(f"inventaire: {e}")
            inventory = []

        resolutions = {}
        if snap.inventory_ok:
            try:
                resolutions = cli.stream_resolutions()
            except (IsapiError, ValueError) as e:
                snap.errors.append(f"resolutions: {e}")

        status, work = {}, {}
        if snap.inventory_ok:
            try:
                status = cli.proxy_status()
            except IsapiError as e:
                snap.errors.append(f"statut: {e}")
            try:
                ws = cli.working_status()
                work, snap.hdd = ws["channels"], ws["hdd"]
            except (IsapiError, ValueError) as e:
                snap.errors.append(f"workingstatus: {e}")

        for c in inventory:
            w = work.get(c["channel"])
            p = status.get(c["channel"])
            snap.cameras.append(CameraObs(
                channel=c["channel"], name=c["name"], ip=c["ip"], model=c["model"],
                serial=c["serial"], firmware=c["firmware"],
                status=_status(p, w), recording=_recording(w),
                detect=p[1] if p else None,
                bitrate=w.get("bitrate") if w else None,
                width=(resolutions.get(c["channel"]) or (None, None))[0],
                height=(resolutions.get(c["channel"]) or (None, None))[1],
            ))
    except Exception as e:   # filet de securite : un bug sur un NVR ne doit pas tuer le cycle
        log.exception("[%s] erreur inattendue", nvr.nvr_id)
        snap.errors.append(f"erreur interne: {type(e).__name__}")
    finally:
        cli.close()
        snap.duration_ms = int((time.time() - t0) * 1000)
    return snap


def collect_all(settings) -> list:
    """Interroge tous les NVR en parallele. Retourne toujours une liste de NvrSnapshot (meme ordre que la config)."""
    with ThreadPoolExecutor(max_workers=len(settings.nvrs)) as pool:
        futures = [pool.submit(collect_nvr, n, settings.user, settings.password) for n in settings.nvrs]
        return [f.result() for f in futures]

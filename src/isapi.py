"""Client ISAPI Hikvision — authentification Digest.

Lecture (GET) pour tout l'inventaire et les captures. Une seule ecriture existe :
rename_channel(), qui renvoie la configuration du canal telle que le NVR la livre en
remplacant uniquement <name>.

Endpoints valides le 14/10 sur les 5 NVR DS-7764NI-M4 (docs/DISCOVERY_2026-10-14.md).
"""
import json
import re
import xml.etree.ElementTree as ET

import requests
from xml.sax.saxutils import escape, unescape
from requests.auth import HTTPDigestAuth

# Parsing XML durci (CWE-611) : on refuse toute declaration de type de document
# et toute entite externe. defusedxml ne fait qu'appeler expat avec les garde-fous ;
# le repli ci-dessous les reproduit si la dependance n'est pas installee.
try:
    from defusedxml import ElementTree as _safe_et
except ImportError:                     # pragma: no cover
    _safe_et = None

_DOCTYPE = re.compile(r"<\s*(!DOCTYPE|!ENTITY)", re.I)

_NS = re.compile(r'\sxmlns(:\w+)?="[^"]+"')


class IsapiError(Exception):
    """Erreur exploitable : message court, sans secret."""


def parse_xml(text: str) -> ET.Element:
    """Parse une reponse ISAPI en retirant le namespace (sinon findall ne trouve rien).

    Les reponses viennent d'un equipement du reseau, pas d'une source de confiance :
    aucune DTD ni entite externe n'est acceptee (XXE / expansion d'entites).
    """
    propre = _NS.sub("", text)
    if _DOCTYPE.search(propre):
        raise IsapiError("reponse XML refusee : declaration de type de document")
    if _safe_et is not None:
        try:
            return _safe_et.fromstring(propre.encode("utf-8"))
        except Exception as e:                        # DefusedXmlException incluse
            raise IsapiError(f"XML invalide : {type(e).__name__}") from None
    return ET.fromstring(propre.encode("utf-8"))


def t(el, path, default=None):
    """Texte d'un sous-element, nettoye ; default si absent ou vide."""
    if el is None:
        return default
    f = el.find(path)
    if f is None or f.text is None or not f.text.strip():
        return default
    return f.text.strip()


class IsapiClient:
    def __init__(self, ip: str, port: int, user: str, password: str, timeout: float = 10.0):
        self.base = f"http://{ip}:{port}"
        self.timeout = timeout
        self.s = requests.Session()
        self.s.auth = HTTPDigestAuth(user, password)
        self.s.headers["User-Agent"] = "hikvision-monitor/1.0"

    def close(self):
        self.s.close()

    def _get(self, path: str) -> str:
        try:
            r = self.s.get(self.base + path, timeout=self.timeout)   # GET uniquement : lecture seule
        except requests.Timeout:
            raise IsapiError(f"timeout {path}")
        except requests.ConnectionError:
            raise IsapiError(f"connexion impossible {path}")
        if r.status_code == 401:
            raise IsapiError("authentification refusee (401)")
        if r.status_code != 200:
            raise IsapiError(f"HTTP {r.status_code} sur {path}")
        return r.text

    def _get_bytes(self, path: str) -> bytes:
        """Comme _get, mais pour du binaire (images)."""
        try:
            r = self.s.get(self.base + path, timeout=self.timeout)   # GET uniquement : lecture seule
        except requests.Timeout:
            raise IsapiError(f"timeout {path}")
        except requests.ConnectionError:
            raise IsapiError(f"connexion impossible {path}")
        if r.status_code == 401:
            raise IsapiError("authentification refusee (401)")
        if r.status_code != 200:
            raise IsapiError(f"HTTP {r.status_code} sur {path}")
        return r.content

    # ------------------------------------------------------------------ ecriture
    # Une seule operation d'ecriture existe dans ce projet : le renommage d'un canal.
    # Elle renvoie la configuration complete telle que le NVR l'a livree, seul <name>
    # etant remplace : adresse source, identifiants et audio restent identiques.

    def _put(self, path: str, body: str) -> str:
        try:
            r = self.s.put(self.base + path, data=body.encode("utf-8"),
                           headers={"Content-Type": "application/xml; charset=UTF-8"},
                           timeout=self.timeout)
        except requests.Timeout:
            raise IsapiError(f"timeout {path}")
        except requests.ConnectionError:
            raise IsapiError(f"connexion impossible {path}")
        if r.status_code == 401:
            raise IsapiError("authentification refusee (401)")
        if r.status_code == 403:
            raise IsapiError("permission refusee par le NVR (403)")
        if r.status_code not in (200, 201, 204):
            raise IsapiError(f"HTTP {r.status_code} sur {path}")
        return r.text

    def channel_name(self, channel: int) -> str:
        xml = self._get(f"/ISAPI/ContentMgmt/InputProxy/channels/{channel}")
        m = re.search(r"<name>(.*?)</name>", xml, re.S)
        return unescape(m.group(1)) if m else ""

    def stream_resolutions(self) -> dict:
        """{canal: (largeur, hauteur)} du flux principal, en UNE requete pour tout le NVR.

        /ISAPI/Streaming/channels renvoie 101, 102, 103... : seul le 01 est le flux principal,
        les autres sont les sous-flux (704x576) et ne doivent pas servir a qualifier la camera.
        """
        xml = self._get("/ISAPI/Streaming/channels")
        out = {}
        for bloc in re.findall(r"<StreamingChannel>(.*?)</StreamingChannel>", xml, re.S):
            cid = re.search(r"<id>(\d+)</id>", bloc)
            larg = re.search(r"<videoResolutionWidth>(\d+)</videoResolutionWidth>", bloc)
            haut = re.search(r"<videoResolutionHeight>(\d+)</videoResolutionHeight>", bloc)
            if not (cid and larg and haut):
                continue
            identifiant = int(cid.group(1))
            if identifiant % 100 != 1:        # 101, 201... = flux principal
                continue
            out[identifiant // 100] = (int(larg.group(1)), int(haut.group(1)))
        return out

    def channel_descriptor(self, channel: int) -> dict:
        """Caracteristiques du canal IP telles que le NVR les connait.

        Attention : managePortNo est le port du protocole prive (8000), PAS le port HTTP.
        L'ISAPI de la camera est joint sur 80.
        """
        xml = self._get(f"/ISAPI/ContentMgmt/InputProxy/channels/{channel}")

        def val(tag, defaut=""):
            m = re.search(rf"<{tag}>(.*?)</{tag}>", xml, re.S)
            return unescape(m.group(1)).strip() if m else defaut

        def nombre(tag, defaut):
            try:
                return int(val(tag, str(defaut)) or defaut)
            except ValueError:
                return defaut

        return {"name": val("name"), "ip": val("ipAddress"), "port": 80,
                "sdk_port": nombre("managePortNo", 8000),
                "src_input": nombre("srcInputPort", 1),
                "protocol": val("proxyProtocol"), "user": val("userName")}

    def rename_video_input(self, src_channel: int, name: str) -> dict:
        """Renomme un canal video la ou son nom fait foi : sur la camera elle-meme."""
        path = f"/ISAPI/System/Video/inputs/channels/{src_channel}"
        xml = self._get(path)
        m = re.search(r"<name>(.*?)</name>", xml, re.S)
        if not m:
            raise IsapiError("bloc <name> absent de /ISAPI/System/Video/inputs")
        ancien = unescape(m.group(1))
        self._put(path, xml[:m.start()] + f"<name>{escape(name)}</name>" + xml[m.end():])
        relu = re.search(r"<name>(.*?)</name>", self._get(path), re.S)
        relu = unescape(relu.group(1)) if relu else ""
        return {"old": ancien, "new": relu, "ok": relu == name}

    def rename_channel(self, channel: int, name: str) -> dict:
        """Renomme un canal IP cote NVR puis relit pour confirmer."""
        xml = self._get(f"/ISAPI/ContentMgmt/InputProxy/channels/{channel}")
        m = re.search(r"<name>(.*?)</name>", xml, re.S)
        if not m:
            raise IsapiError("bloc <name> absent de la configuration du canal")
        ancien = unescape(m.group(1))
        corps = xml[:m.start()] + f"<name>{escape(name)}</name>" + xml[m.end():]
        self._put(f"/ISAPI/ContentMgmt/InputProxy/channels/{channel}", corps)
        nouveau = self.channel_name(channel)
        return {"old": ancien, "new": nouveau, "ok": nouveau == name}

    def snapshot(self, channel: int, main_stream: bool = True) -> bytes:
        """Capture JPEG d'un canal : 101 = canal 1 flux principal, 102 = sous-flux."""
        suffix = "01" if main_stream else "02"
        return self._get_bytes(f"/ISAPI/Streaming/channels/{channel}{suffix}/picture")

    # --- endpoints -------------------------------------------------------
    def device_info(self) -> dict:
        root = parse_xml(self._get("/ISAPI/System/deviceInfo"))
        return {
            "device_name": t(root, "deviceName"),
            "model": t(root, "model"),
            "serial": t(root, "serialNumber"),
            "firmware": t(root, "firmwareVersion"),
            "mac": t(root, "macAddress"),
        }

    def proxy_channels(self) -> list:
        """Inventaire des cameras IP : une entree par canal configure (en ligne ou non)."""
        root = parse_xml(self._get("/ISAPI/ContentMgmt/InputProxy/channels"))
        out = []
        for c in root.findall("InputProxyChannel"):
            d = c.find("sourceInputPortDescriptor")
            ch = t(c, "id")
            if ch is None or not ch.isdigit():
                continue
            out.append({
                "channel": int(ch),
                "name": t(c, "name"),
                "ip": t(d, "ipAddress"),
                "model": t(d, "model"),
                "serial": t(d, "serialNumber"),
                "firmware": t(d, "firmwareVersion"),
            })
        return out

    def proxy_status(self) -> dict:
        """{canal: (online bool, chanDetectResult)}"""
        root = parse_xml(self._get("/ISAPI/ContentMgmt/InputProxy/channels/status"))
        out = {}
        for s in root.findall("InputProxyChannelStatus"):
            ch = t(s, "id")
            if ch and ch.isdigit():
                online = t(s, "online")
                out[int(ch)] = (None if online is None else online.lower() == "true", t(s, "chanDetectResult"))
        return out

    def working_status(self) -> dict:
        """{canal: {online, record, bitrate}} depuis /ISAPI/System/workingstatus (JSON)."""
        data = json.loads(self._get("/ISAPI/System/workingstatus?format=json"))
        ws = data.get("WorkingStatus", {})
        out = {}
        for c in ws.get("ChanStatus") or []:
            try:
                out[int(c["chanNo"])] = {"online": c.get("online"), "record": c.get("record"), "bitrate": c.get("bitRate")}
            except (KeyError, TypeError, ValueError):
                continue
        hdd = [{"id": h.get("hdNo"), "status": h.get("status"), "volume": h.get("volume"), "free": h.get("freeSpace")}
               for h in ws.get("HDStatus") or []]
        return {"channels": out, "hdd": hdd, "dev_status": ws.get("devStatus")}

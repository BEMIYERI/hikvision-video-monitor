"""Analyse des reponses brutes de la decouverte (data/discovery). Lecture seule, aucun appel reseau."""
import json, re, collections
from pathlib import Path
import xml.etree.ElementTree as ET

D = Path(__file__).resolve().parent.parent / "data" / "discovery"
NVRS = sorted(p.name for p in D.iterdir() if p.is_dir()) if D.exists() else []

def xml(nvr, key):
    t = (D / nvr / f"{key}.xml").read_text(encoding="utf-8")
    return ET.fromstring(re.sub(r'\sxmlns(:\w+)?="[^"]+"', "", t).encode("utf-8"))

def txt(el, path, default="UNKNOWN"):
    f = el.find(path)
    return f.text.strip() if f is not None and f.text and f.text.strip() else default

all_ips = collections.defaultdict(list)
for nvr in NVRS:
    print(f"\n######## {nvr} (nom dans .env) ########")
    di = xml(nvr, "deviceInfo")
    print(f"deviceName={txt(di,'deviceName')}  model={txt(di,'model')}  fw={txt(di,'firmwareVersion')}  mac={txt(di,'macAddress')}")

    # cameras IP (InputProxy)
    ch = xml(nvr, "proxy_channels")
    cams = []
    for c in ch.findall("InputProxyChannel"):
        cams.append({
            "id": txt(c, "id"), "name": txt(c, "name"),
            "ip": txt(c, "sourceInputPortDescriptor/ipAddress"),
            "model": txt(c, "sourceInputPortDescriptor/model"),
            "proto": txt(c, "sourceInputPortDescriptor/proxyProtocol"),
        })
    for c in cams:
        all_ips[c["ip"]].append(f"{nvr}:{c['id']}")
    names = collections.Counter(c["name"] for c in cams)
    generic = sum(1 for c in cams if re.fullmatch(r"(?i)(camera|ipcamera|ipdome|cam)\s*0*\d+", c["name"]))
    print(f"InputProxy: {len(cams)} cameras | noms generiques type 'Camera 01': {generic} | noms en double: {sum(v for v in names.values() if v>1)}")
    print("  exemples:", "; ".join(f"{c['id']}={c['name']}@{c['ip']}" for c in cams[:6]))
    print("  modeles:", dict(collections.Counter(c["model"] for c in cams).most_common(4)))

    # statut (InputProxy status)
    st = xml(nvr, "proxy_status")
    first = st.find("InputProxyChannelStatus")
    if first is not None:
        print("  champs status (1er):", [e.tag for e in first])
    online = collections.Counter(txt(s, "online") for s in st.findall("InputProxyChannelStatus"))
    print(f"  online (proxy_status): {dict(online)}")
    detect = collections.Counter(txt(s, "chanDetectResult") for s in st.findall("InputProxyChannelStatus"))
    print(f"  chanDetectResult: {dict(detect)}")

    # streaming : cameras physiques actives
    sc = xml(nvr, "streaming")
    phys = {txt(s, "Video/dynVideoInputChannelID") for s in sc.findall("StreamingChannel") if txt(s, "Video/enabled") == "true"}
    phys.discard("UNKNOWN")
    print(f"  Streaming: {len(phys)} entrees video actives")

    # workingstatus JSON
    ws = json.loads((D / nvr / "workingstatus.json").read_text(encoding="utf-8"))
    w = ws.get("WorkingStatus", {})
    print("  WorkingStatus cles:", list(w.keys()))
    chans = w.get("ChanStatus") or w.get("chanStatus") or []
    if chans:
        print("  ChanStatus[0]:", json.dumps(chans[0], ensure_ascii=False)[:300])
        print("  online:", dict(collections.Counter(str(c.get("online")) for c in chans)),
              "| record:", dict(collections.Counter(str(c.get("record")) for c in chans)))

dups = {ip: v for ip, v in all_ips.items() if len(v) > 1 and ip != "UNKNOWN"}
print(f"\nIP camera en double (meme IP sur plusieurs canaux): {len(dups)}")
for ip, v in list(dups.items())[:10]:
    print("  ", ip, v)
print("Total cameras InputProxy:", sum(len(v) for v in all_ips.values()))

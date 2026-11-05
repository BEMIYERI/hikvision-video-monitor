"""Construit la video de presentation (8 plans, voix off FR, sous-titres).

Etapes : synthese vocale par plan (edge-tts), mesure des durees, rendu video avec
zoom lent, concatenation, incrustation des sous-titres, mux audio.
"""
from __future__ import annotations

import json
import re
import subprocess
from pathlib import Path

from gtts import gTTS

VID = Path(__file__).resolve().parent
SCENES = VID / "scenes"
AUDIO = VID / "audio"
WORK = VID / "work"
LANGUE = "fr"
FPS = 25

PLANS = [
    ("s1-accroche", "Vos caméras filment. Mais qui vérifie qu'elles fonctionnent encore ? "
                    "Hikvision Video Monitor surveille jusqu'à mille vingt-quatre caméras et seize "
                    "enregistreurs, depuis un seul écran."),
    ("s2-probleme", "Une caméra tombe. Le disque sature. L'enregistrement s'arrête. Personne ne le voit. "
                    "Et le jour où il faut rendre des comptes, il faut tout recompter à la main."),
    ("s3-solution", "Notre agent interroge vos enregistreurs Hikvision existants, en lecture seule, "
                    "toutes les soixante secondes. Aucune caméra à remplacer. Aucun cloud. "
                    "Rien ne sort de votre réseau."),
    ("s4-tableau", "En un écran : chaque caméra, son enregistreur, sa définition, sa focale, son statut "
                   "et l'heure de son dernier contact."),
    ("s5-filtres", "Filtrez par enregistreur, par statut, par définition ou par focale. Deux mégapixels, "
                   "quatre mégapixels, huit millimètres : la question trouve sa réponse en un clic."),
    ("s6-preuve", "Chaque changement est horodaté. Trente-deux mille quatre cents événements sur trente "
                  "jours, exportables en CSV. Une panne devient un fait daté, pas une impression."),
    ("s7-rapport", "Et le rapport que le client attend, calqué sur son modèle, se génère en un clic. "
                   "Formules et mise en forme conservées."),
    ("s7b-synthese", "Et en tête du rapport, la synthèse par enregistreur : combien de caméras en ligne, "
                     "combien hors ligne, et le total calculé automatiquement."),
    ("s8-cta", "Installation en quinze minutes sur un PC ordinaire. Démonstration en ligne et "
               "application Android disponibles dès aujourd'hui."),
]


def run(cmd, **kw):
    r = subprocess.run(cmd, capture_output=True, text=True, **kw)
    if r.returncode != 0:
        raise RuntimeError(f"{' '.join(map(str, cmd))}\n{r.stderr[-1500:]}")
    return r


def duree(chemin: Path) -> float:
    r = run(["ffprobe", "-v", "error", "-show_entries", "format=duration",
             "-of", "default=nw=1:nk=1", str(chemin)])
    return float(r.stdout.strip())


def synthese(nom: str, texte: str) -> Path:
    """Voix francaise via Google TTS (edge-tts refuse le jeton : horloge du poste decalee)."""
    mp3 = AUDIO / f"{nom}.mp3"
    if mp3.exists() and mp3.stat().st_size > 1000:
        return mp3
    gTTS(texte, lang=LANGUE, slow=False).save(str(mp3))
    return mp3


def srt(plans_avec_durees, chemin: Path):
    """Un sous-titre tous les ~9 mots, reparti proportionnellement a la duree du plan."""
    def ts(t):
        h, r = divmod(t, 3600)
        m, s = divmod(r, 60)
        return f"{int(h):02d}:{int(m):02d}:{s:06.3f}".replace(".", ",")

    lignes, index, curseur = [], 1, 0.0
    for nom, texte, d in plans_avec_durees:
        mots = texte.split()
        lots = [" ".join(mots[i:i + 9]) for i in range(0, len(mots), 9)]
        total_mots = sum(len(l.split()) for l in lots) or 1
        debut = curseur
        for lot in lots:
            part = d * len(lot.split()) / total_mots
            lignes += [str(index), f"{ts(debut)} --> {ts(debut + part)}", lot, ""]
            index += 1
            debut += part
        curseur += d
    chemin.write_text("\n".join(lignes), encoding="utf-8")


def main():
    WORK.mkdir(exist_ok=True)
    AUDIO.mkdir(exist_ok=True)

    faits = []
    for nom, texte in PLANS:
        mp3 = synthese(nom, texte)
        wav = AUDIO / f"{nom}.wav"
        if not wav.exists():
            run(["ffmpeg", "-y", "-i", str(mp3), "-ar", "44100", "-ac", "2", str(wav)])
        d = duree(wav) + 1.0                     # respiration entre les plans
        faits.append((nom, texte, d, wav))
        print(f"{nom:14s} voix {duree(wav):5.2f}s  plan {d:5.2f}s")

    # 1) video par plan (zoom lent, fondu entre plans via concat xfade simple : on reste sur fondu noir)
    clips = []
    for i, (nom, texte, d, wav) in enumerate(faits):
        png = SCENES / f"{nom}.png"
        mp4 = WORK / f"{nom}.mp4"
        zoom = f"zoompan=z='min(zoom+0.0002,1.02)':d={int(d * FPS)}:s=1920x1080:fps={FPS}"
        run(["ffmpeg", "-y", "-loop", "1", "-i", str(png),
             "-vf", f"{zoom},fade=t=in:st=0:d=0.6,fade=t=out:st={max(0, d - 0.6):.2f}:d=0.6,format=yuv420p",
             "-t", f"{d:.2f}", "-r", str(FPS), "-c:v", "libx264", "-preset", "medium", "-crf", "19",
             str(mp4)])
        clips.append(mp4)

    # 2) audio continu : chaque piste decalee puis additionnee
    sortie_audio = WORK / "voix.wav"
    entrees, filtres, curseur = [], [], 0.0
    for i, (nom, texte, d, wav) in enumerate(faits):
        entrees += ["-i", str(wav)]
        filtres.append(f"[{i}:a]adelay={int(curseur * 1000)}|{int(curseur * 1000)}[a{i}]")
        curseur += d
    total = curseur
    melange = "".join(f"[a{i}]" for i in range(len(faits)))
    run(["ffmpeg", "-y", *entrees, "-filter_complex",
         ";".join(filtres) + f";{melange}amix=inputs={len(faits)}:normalize=0:dropout_transition=0[aout]",
         "-map", "[aout]", "-ar", "44100", "-ac", "2", "-t", f"{total:.2f}", str(sortie_audio)])

    # 3) concatenation video
    liste = WORK / "liste.txt"
    liste.write_text("\n".join(f"file '{c.name}'" for c in clips), encoding="utf-8")
    silencieux = WORK / "video_muette.mp4"
    run(["ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", str(liste.name),
         "-c", "copy", str(silencieux.name)], cwd=WORK)

    # 4) sous-titres
    fichier_srt = VID / "sous-titres.srt"
    srt([(n, t, d) for n, t, d, _ in faits], fichier_srt)

    # 5) rendu final : sous-titres incrustes + audio
    final = VID / "hikvision-video-monitor-presentation.mp4"
    run(["ffmpeg", "-y", "-i", "work/video_muette.mp4", "-i", "work/voix.wav",
         "-vf", "subtitles=sous-titres.srt:force_style='FontName=Segoe UI,FontSize=14,"
                "PrimaryColour=&H00FFFFFF,OutlineColour=&H00101010,BorderStyle=1,Outline=1.6,"
                "Shadow=0.6,MarginV=38'",
         "-c:v", "libx264", "-preset", "medium", "-crf", "20", "-c:a", "aac", "-b:a", "160k",
         "-shortest", "-movflags", "+faststart", final.name], cwd=VID)

    print(f"\nvideeo : {final}  ({duree(final):.1f}s, {final.stat().st_size / 1024 / 1024:.1f} Mo)")
    (VID / "plans.json").write_text(json.dumps(
        [{"plan": n, "duree": round(d, 2), "texte": t} for n, t, d, _ in faits],
        ensure_ascii=False, indent=2), encoding="utf-8")


if __name__ == "__main__":
    main()

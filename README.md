# Shorts-fabriek 🎬

Plak een videolink (YouTube, Twitch-VOD, …) of sleep een videobestand erin. De app zoekt zelf de sterkste
momenten, maakt er verticale Shorts van (1080×1920, < 60 s, met ondertitels en een hook) en zet ze na jouw
goedkeuring ingepland op YouTube.

**Kwaliteit boven kwantiteit:** Claude beoordeelt elk moment op viraal potentieel (hook, clou, zelfstandig
te begrijpen). Alleen clips met een score vanaf 7/10 komen in je review. Liever 3 knallers dan 10 matige clips.

---

## Installatie (Windows)

1. Download deze map, bijvoorbeeld met **Code → Download ZIP** op GitHub, en pak hem uit.
2. Dubbelklik **`start.bat`**.
   - De eerste keer installeert het script automatisch **uv** (Python), **ffmpeg** (via winget) en alle pakketten.
     Duurt dat bij ffmpeg lang of zie je een fout? Sluit het venster en dubbelklik `start.bat` nog een keer.
   - Daarna gaat je browser open op <http://127.0.0.1:8765>.
3. Open het bestand **`.env`** in deze map (Kladblok is prima) en vul je Claude-sleutel in:
   ```
   ANTHROPIC_API_KEY=sk-ant-...
   ```
   Een sleutel maak je aan op <https://console.anthropic.com> → *API Keys*. Sla het bestand op, sluit het
   zwarte venster en start `start.bat` opnieuw.

> De eerste video duurt langer: de spraakherkenningsmodellen (Whisper, ±2 GB) worden dan eenmalig gedownload.

Stoppen: sluit het zwarte venster. Starten: dubbelklik `start.bat`. Bij elke start wordt yt-dlp bijgewerkt,
zodat downloads blijven werken als YouTube of Twitch iets verandert.

*macOS/Linux:* installeer ffmpeg (`brew install ffmpeg` / `sudo apt install ffmpeg`) en start met `./start.sh`.

---

## Gebruik

### 1. Toevoegen
Plak één of meer links (één per regel) en druk **Ctrl+Enter**, of sleep videobestanden in het venster.
Je kunt meteen de volgende link plakken: alles gaat in een wachtrij.

Zo werkt de app per video:
1. Downloadt eerst **alleen de audio** (snel, ook bij een stream van 5 uur).
2. Maakt een snelle transcriptie en meet geluidspieken en YouTube's "meest opnieuw afgespeeld"-grafiek.
3. Laat **Claude** de beste momenten kiezen, met titel, hook-tekst, beschrijving en hashtags.
4. Downloadt **alleen die fragmenten** in 1080p.
5. Maakt nauwkeurige ondertitels en zoekt gezichten voor het bijsnijden.

### 2. Review
Je ziet elke clip direct als Short, met layout, ondertitels en hook. Er wordt nog niets gerenderd, dus
beoordelen gaat razendsnel.

| Toets | Actie |
|---|---|
| **A** | goedkeuren (de clip wordt op de achtergrond gerenderd) |
| **R** | afkeuren |
| **Spatie** | afspelen / pauzeren |
| **J / K** | vorige / volgende clip |
| **Q / W** | begin 0,5 s eerder / later |
| **O / P** | einde 0,5 s eerder / later |
| **B** | laatste 3 seconden afspelen (loopt het einde lekker?) |

Je kunt ook de rode randjes op de tijdlijn verslepen, de titel en hook aanpassen en typfouten in de ondertitels
verbeteren. Er zijn vier **layouts**:
- **Volgen**: de uitsnede beweegt rustig mee met het gezicht.
- **Vast**: een vaste uitsnede; de positie stel je in met de schuifbalk.
- **Hele beeld**: het volledige 16:9-beeld met een vervaagde achtergrond (goed bij actie zonder gezicht).
- **Facecam+game**: webcam boven, gameplay onder. Deze wordt automatisch gekozen als er een facecam in een hoek zit.

### 3. Publiceren
- **📅 Plan in** verdeelt de goedgekeurde clips over je vaste tijdsloten (standaard 12:00, 17:00 en 20:00).
  Je kunt per clip de tijd aanpassen.
- Daarna, afhankelijk van de uploadmodus:
  - **Studio-modus** (standaard): *Zet alles klaar* kopieert de Shorts naar `data/export` met datum en titel
    in de bestandsnaam. Sleep ze in [YouTube Studio](https://studio.youtube.com) (tot 15 tegelijk) en gebruik
    de knoppen *Kopieer titel/beschrijving*.
  - **API-modus**: *Upload alles* uploadt en plant alles automatisch in. Zie hieronder.

---

## YouTube koppelen (API-modus)

### ⚠️ Eerst dit: "privé (vergrendeld)"
YouTube zet video's die je via een **niet-geaudit** API-project uploadt automatisch op **privé (vergrendeld)**.
Zo'n video kun je daarna ook in Studio niet meer openbaar maken. Wat je daaraan kunt doen:

1. **Vraag de audit meteen aan** via het
   [YouTube API Services Audit & Quota Extension-formulier](https://support.google.com/youtube/contact/yt_api_form).
   Beschrijf het eerlijk: *"Persoonlijke tool om eigen Shorts te uploaden naar mijn eigen kanaal."*
   Je hebt een openbare privacybeleid-pagina nodig; een simpele pagina op Google Sites of GitHub Pages is genoeg.
   Reken op een paar weken wachttijd.
2. Gebruik tot die tijd de **Studio-modus**.
3. Na goedkeuring: zet in **Instellingen** "Mijn API-project is geaudit" aan en kies uploadmodus **YouTube API**.

### Instellen (±10 minuten, eenmalig)
1. Ga naar <https://console.cloud.google.com> en maak een nieuw project aan (bijv. "Shorts-fabriek").
2. **APIs & Services → Library**: zoek *YouTube Data API v3* en klik **Enable**.
3. **APIs & Services → OAuth consent screen** (heet ook *Google Auth Platform*):
   - Kies type **External** en vul de verplichte velden in.
   - Voeg bij *Audience/Test users* je eigen Google-account toe.
   - Klik daarna op **Publish app / In production**. Doe je dat niet, dan vervalt je login elke 7 dagen.
     Bij het inloggen zie je dan "Google heeft deze app niet geverifieerd". Klik op *Geavanceerd → Doorgaan*;
     dat is prima voor eigen gebruik.
4. **APIs & Services → Credentials → Create credentials → OAuth client ID**, kies type **Desktop app**.
   Download het JSON-bestand en zet het in deze map als **`client_secret.json`**.
5. Ga in de app naar **Instellingen → YouTube koppelen** en log in met het account van je kanaal.

`client_secret.json`, `.env` en de map `data/` (met je login-token) staan in `.gitignore` en komen nooit in git.

### Limieten
- **Quota:** volgens recente bronnen heeft uploaden (`videos.insert`) sinds juni 2026 een eigen dagquotum van
  **~100 uploads per dag** per project. Vroeger kostte één upload 1.600 van de 10.000 units, dus maximaal
  ~6 per dag. De app gebruikt per clip precies één upload-aanroep, plus één lichte aanroep om je kanaalnaam te tonen.
- **Inplannen** gaat via `privacyStatus=private` + `publishAt`. YouTube zet de video dan zelf op het
  ingestelde tijdstip openbaar. Dat werkt alleen met een geaudit project (zie hierboven).
- YouTube hanteert daarnaast een eigen daglimiet per kanaal. Door je clips over tijdsloten te verdelen blijf je
  daar ruim onder, en het is ook beter voor het algoritme.

---

## Tips voor Shorts die aanslaan

- Vul in **Instellingen** bij *"Waar gaat je kanaal over?"* je niche en doelgroep in. Claude kiest dan gerichter
  en schrijft titels in jouw stijl. Titels die je goedkeurt, gebruikt hij als voorbeeld voor volgende video's.
- Houd de **minimale score op 7** of hoger. Krijg je te weinig clips? Verlaag hem pas daarna.
- Check met **B** altijd het einde: een Short die direct na de clou stopt, wordt vaker herbekeken.
- Pas de **hook-tekst** gerust aan. Een vraag of spanning werkt beter dan een samenvatting.
- Clips van andermans video's kunnen Content ID-claims of strikes opleveren. Gebruik eigen content of vraag
  toestemming.

---

## Snelheid

- **Renderen:** de app kiest automatisch de snelste encoder: AMD (AMF), Intel (Quick Sync), NVIDIA (NVENC)
  of anders de CPU. Pas "Clips tegelijk renderen" aan in Instellingen (2-3 werkt meestal het best).
- **Transcriptie** draait bij AMD/Intel op de CPU. Voor extra snelheid kun je *pass 1* op `base` zetten; de
  ondertitels blijven nauwkeurig, want pass 2 (`large-v3-turbo`) doet alleen de gekozen clips.
- Heeft een YouTube-video een "meest opnieuw afgespeeld"-grafiek? Dan weegt die zwaar mee: dat zijn letterlijk
  de momenten die kijkers het leukst vonden.

**Kosten Claude:** ongeveer €0,05-0,15 per uur bronvideo.

---

## Problemen oplossen

| Probleem | Oplossing |
|---|---|
| "ffmpeg niet gevonden" | Sluit het venster en start `start.bat` opnieuw, of installeer ffmpeg handmatig: `winget install Gyan.FFmpeg` |
| Download mislukt | Bij elke start wordt yt-dlp bijgewerkt; probeer de job opnieuw. Voor privé-video's werkt downloaden niet. |
| "AI-selectie mislukt" | Controleer `ANTHROPIC_API_KEY` in `.env` en je tegoed op console.anthropic.com. De app kiest dan op geluid. |
| Render mislukt met AMF/QSV | Zet in Instellingen de encoder op *CPU (libx264)* en werk je GPU-driver bij. |
| Preview blijft zwart | Gebruik Chrome of Edge. |
| Poort 8765 bezet | Zet `PORT=8766` in `.env`. |

Alles draait lokaal. Alleen het transcript gaat naar Claude, en de video's gaan naar YouTube.

---

## Voor ontwikkelaars

```
app/
  main.py            FastAPI-routes en pagina's
  worker.py          wachtrij: analyse, parallel renderen, uploaden
  pipeline/          download → transcribe → signals → select (Claude) → framing → captions → render
  upload/            YouTube API, tijdsloten, Studio-export
  templates/, static/  HTML/JS (live preview in review.js)
tests/               `uv run pytest`
```

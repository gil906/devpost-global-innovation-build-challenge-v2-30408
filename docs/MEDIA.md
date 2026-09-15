# CommonTable in action

These assets show the running CommonTable prototype with its original synthetic scenario. They contain fictional location names only.

| Asset | What it shows |
|---|---|
| [Plan overview](media/01-plan-overview.png) | Maximum-coverage allocation, schematic network, baseline comparison, transfer table and unassigned supply |
| [Supply and hubs](media/02-supply-and-hubs.png) | Six editable batches and four receiving hubs, with quantities, categories and time windows |
| [Method and evidence](media/03-method-and-evidence.png) | Algorithm explanation, explicit assumptions and the 24-pair eligibility audit |
| [Mobile plan](media/04-mobile-plan.png) | Responsive 390-pixel-wide interface; this capture uses a 20-serving vehicle capacity |
| [Captioned demo](media/commontable-demo.webm) | Approximately 2:38 of actual browser interactions at 1440 x 1000, with burned-in English captions |

The demo covers the project purpose, fictional-data boundaries, supply editing, the 230-versus-170 result, the 2 km what-if, blocked-connection explanations, snapshot persistence, CSV export and the algorithm. The final scene states the direct-distance and parallel-vehicle assumptions. The video uses English text captions rather than spoken audio.

## Reproduce the media

Install the optional browser development prerequisites described in the README, then run these commands sequentially:

```bash
node scripts/browser-check.mjs
node scripts/record-demo.mjs
python3 scripts/verify_media.py
node scripts/check-video.mjs
```

Each browser command starts and stops its own temporary application server on port 8764 and uses an isolated runtime database. The recording script drives the application, not pre-rendered screenshots. The validation script inspects the actual PNG and WebM formats, requires three desktop screenshots of at least 1280 pixels wide, and checks a 120-300 second video at a minimum of 1280 x 720.

The repository contains the media files, not a hosted video-service URL.

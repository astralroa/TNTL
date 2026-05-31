# NoLaugh — Beta Setup

## Install

```
pip install -r requirements.txt
py setup_db.py
```

## Generate SSL cert (one time)

```
py gen_cert.py 26.24.146.35
```

Replace `26.24.146.35` with your Radmin VPN IP if it changes.

## Run

```
py -m daphne -b 0.0.0.0 -p 8443 --certfile cert.pem --keyfile key.pem nolaugh.asgi:application
```

- Local: `https://localhost:8443`
- Other devices via Radmin: `https://26.24.146.35:8443`

## First visit — accept the cert warning

Self-signed cert will show a browser warning. Click "Advanced" → "Proceed anyway".
You only need to do this once per device.

## Modes

- **Solo** — one player, one face, just you vs the camera
- **Hotseat Rotation** — two players, alternates who's on the hot seat each round
- **First to Laugh Loses** — both faces monitored, first laugh triggers that player's round

## Sound files (optional)

Drop into `game/static/game/sounds/` then re-run `py setup_db.py`:
- `airhorn.mp3`
- `laugh_track.mp3`
- `sad_trombone.mp3`

Free from freesound.org. Without them sound bombs silently do nothing.

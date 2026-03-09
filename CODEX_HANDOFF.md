# Codex Handoff

Updated: 2026.03.09

## Environment

- Local repo path: `/home/codex/projects/malla`
- Remote deploy host: `codex@10.5.0.71`
- Remote deploy path: `/home/codex/apps/malla`
- Local toolchain is prepared:
  - `uv`
  - Python `3.13`
  - `docker`
  - `docker compose`
  - `rsync`
- Remote host also has:
  - `docker`
  - `docker compose`
  - `rsync`

## Deploy workflow

- Local bootstrap:
  - `make bootstrap`
- Local tests:
  - `make test`
- Remote deploy:
  - `DEPLOY_USER=codex DEPLOY_HOST=10.5.0.71 DEPLOY_PATH=/home/codex/apps/malla make deploy-remote`

Files added for this workflow:

- `scripts/bootstrap_dev.sh`
- `scripts/deploy_remote.sh`
- `docker-compose.remote-build.yml`

## Runtime state

- App is deployed on `10.5.0.71`
- Web UI responds on:
  - `http://10.5.0.71:5008`
- MQTT broker in `.env` is configured to:
  - `mqtt.aperturelab.cz`
- `malla-web` and `malla-capture` were both confirmed `Up` after deploy

## Important implemented changes

- Dashboard now auto-refreshes data every 30 seconds in the browser without full page reload.
- Footer link points to:
  - `https://github.com/norman67cz/malla`
- Footer version text is static:
  - `Version 2026.03.09`
- LoRa preset support was added to node detail:
  - captured from `ADMIN_APP`
  - extracted from `AdminMessage -> Config -> lora -> modem_preset`
  - stored in `node_info.lora_modem_preset`
  - timestamp stored in `node_info.lora_modem_preset_updated_at`
  - if no config packet has been seen yet, node detail shows:
    - `Not captured yet`

## Important caveat

- Current production data on `10.5.0.71` does not yet contain any `ADMIN_APP` packets in `packet_history`.
- Because of that, LoRa preset rendering is implemented and deployed, but most nodes currently show `Not captured yet`.
- This is expected and not a bug unless `ADMIN_APP` traffic is known to exist.

## Database notes

- Node channel-like info is stored in:
  - `node_info.primary_channel`
- This is based on `ServiceEnvelope.channel_id`
- It is not the same thing as LoRa modem preset

Docker volume data on the server should be in the existing Docker volume for this compose project, typically:

- `/var/lib/docker/volumes/malla_malla_data/_data/`

Check with:

- `docker volume inspect malla_malla_data --format '{{ .Mountpoint }}'`

## Recent commits

- `d05c457` `Add remote deploy workflow and dashboard auto-refresh`
- `e20af37` `Add LoRa preset to node info page`
- `eb7ee36` `Update footer repository link and version date`

## Suggested next steps

- If needed, capture and inspect `ADMIN_APP` traffic to confirm LoRa preset population in production.
- If the footer/version change should be visible on the remote host, deploy after pulling latest `main`.
- If more takeover notes are needed, extend this file instead of scattering them across docs.

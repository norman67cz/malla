# Original Malla

Malla (_Mesh_, in Spanish) is an ([AI-built](./AI.md)) tool that logs Meshtastic packets from an MQTT broker into a SQL database and exposes a web UI to get some interesting data insights from them.

## My Add
This is a fork of the original project where I'm trying out code editing using AI codex.

## Changes
You can choose SSLite or PostgresQL as the SQL backend. Migration scripts are included.
Made by codex:
  - add auto refresh dashboard
  - add Live View of incoming packet
  - add a translation layer
  - I modified the structure to better withstand the load
  - small check data security

## Install
  clean install ubuntu 24.04 server
  pull repository 
  sudo ./scripts/install_malla_instance.sh sqlite
  sudo ./scripts/install_malla_instance.sh postgres

## Deploy Notes
  if you refresh manually with git pull + docker compose, write the current short commit first:
  printf '%s\n' "$(git rev-parse --short HEAD)" > BUILD_COMMIT
  this file is used by the footer to show the deployed commit hash

## Data Retention
  packet history cleanup already exists in `malla-capture` and runs automatically on startup and then every hour
  configure it in `.env` using either:
  `MALLA_DATA_RETENTION_DAYS=30`
  or
  `MALLA_DATA_RETENTION_HOURS=720`
  if both are set, `MALLA_DATA_RETENTION_HOURS` wins
  `0` means keep everything forever

## Uninstall
  sudo ./scripts/uninstall_malla_instance.sh --force
  PURGE_POSTGRES=1 sudo ./scripts/uninstall_malla_instance.sh --force
  PURGE_POSTGRES=1 PURGE_PACKAGES=1 sudo ./scripts/uninstall_malla_instance.sh --force

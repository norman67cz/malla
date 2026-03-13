# Malla

Malla (_Mesh_, in Spanish) is an ([AI-built](./AI.md)) tool that logs Meshtastic packets from an MQTT broker into a SQLite database and exposes a web UI to get some interesting data insights from them.

## Original


## Changes
Made by codex:
  - auto refresh dashboard
  - 

## Install
  clean install ubuntu 24.04 server
  pull repository 
  sudo ./scripts/install_malla_instance.sh sqlite
  sudo ./scripts/install_malla_instance.sh postgres

## Uninstall
  sudo ./scripts/uninstall_malla_instance.sh --force


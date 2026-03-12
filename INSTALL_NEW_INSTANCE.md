# Install New Instance

This document describes the current recommended way to install a new Malla instance from this repository.

It covers:
- a fresh Docker-based deployment
- first start with SQLite
- optional switch to PostgreSQL after the instance is already running

## 1. Server prerequisites

Install the base packages on the target server:

```bash
sudo apt update
sudo apt install -y git rsync docker.io docker-compose-plugin
sudo systemctl enable --now docker
```

Your user should be able to run Docker commands. Either use `sudo docker ...` or add the user to the `docker` group.

## 2. Clone the repository

Choose a target directory, for example:

```bash
mkdir -p /opt
cd /opt
git clone https://github.com/norman67cz/malla.git
cd malla
```

## 3. Create the environment file

Create `.env` from the example:

```bash
cp env.example .env
```

Edit at least these values:

```bash
MALLA_SECRET_KEY=replace-this-with-a-random-secret
MALLA_MQTT_BROKER_ADDRESS=your.mqtt.server
MALLA_MQTT_PORT=1883
MALLA_MQTT_USERNAME=
MALLA_MQTT_PASSWORD=
MALLA_NAME=My Malla Instance
MALLA_WEB_COMMAND=/app/.venv/bin/malla-web-gunicorn
```

If you use a public broker or multiple channel keys, also review:

```bash
MALLA_MQTT_TOPIC_PREFIX=msh
MALLA_MQTT_TOPIC_SUFFIX=/+/+/+/#
MALLA_DEFAULT_CHANNEL_KEY=
```

## 4. Start the first instance

For a production-style Docker start:

```bash
docker compose \
  -f docker-compose.yml \
  -f docker-compose.prod.yml \
  -f docker-compose.remote-build.yml \
  up -d --build
```

This starts:
- `malla-capture`
- `malla-web`

The initial database backend is SQLite unless `.env` explicitly says otherwise.

## 5. Verify the instance

Check running containers:

```bash
docker compose ps
```

Check logs:

```bash
docker logs --tail 50 malla-malla-capture-1
docker logs --tail 50 malla-malla-web-1
```

Verify HTTP:

```bash
curl -I http://127.0.0.1:5008/
curl http://127.0.0.1:5008/api/stats
```

If the server is remote, expose or reverse-proxy port `5008` as needed.

## 6. Deploy updates later

If the repository already exists on the target server and `.env` is already configured:

```bash
cd /opt/malla
git pull --ff-only
docker compose \
  -f docker-compose.yml \
  -f docker-compose.prod.yml \
  -f docker-compose.remote-build.yml \
  up -d --build
```

If you prefer deploying from another machine over SSH, use:

```bash
DEPLOY_USER=your-user \
DEPLOY_HOST=your-server \
DEPLOY_PATH=/opt/malla \
make deploy-remote
```

`make deploy-remote` preserves the remote `.env`.

## 7. Optional: switch the running instance to PostgreSQL

The simplest recommended path is:

1. Start the instance on SQLite.
2. Confirm capture and UI work.
3. Switch to PostgreSQL with the provided script.

Install PostgreSQL packages:

```bash
sudo apt update
sudo apt install -y postgresql postgresql-contrib postgresql-client libpq-dev
```

Preview the switch first:

```bash
cd /opt/malla
DB_PASSWORD='your-strong-password' ./scripts/switch_to_postgres.sh --dry-run
```

Run the real switch:

```bash
cd /opt/malla
DB_PASSWORD='your-strong-password' ./scripts/switch_to_postgres.sh
```

The script will:
- create the PostgreSQL user and database
- adjust local PostgreSQL auth for socket access
- snapshot the SQLite database
- migrate data to PostgreSQL
- update `.env`
- rebuild and restart the containers
- verify `/`, `/api/stats`, and `/api/analytics`

## 8. Roll back from PostgreSQL to SQLite

Preview rollback:

```bash
cd /opt/malla
./scripts/switch_to_sqlite.sh --dry-run
```

Run rollback:

```bash
cd /opt/malla
./scripts/switch_to_sqlite.sh
```

This switches `.env` back to SQLite and rebuilds the services.

## 9. Data location

By default, Docker stores persistent app data in the `malla_data` volume.

To inspect the actual path on the host:

```bash
docker volume inspect malla_malla_data --format '{{ .Mountpoint }}'
```

Typical location:

```bash
/var/lib/docker/volumes/malla_malla_data/_data/
```

The SQLite database is usually:

```bash
/var/lib/docker/volumes/malla_malla_data/_data/meshtastic_history.db
```

## 10. Minimal install summary

For the shortest path to a new working instance:

```bash
sudo apt update
sudo apt install -y git docker.io docker-compose-plugin
sudo systemctl enable --now docker
cd /opt
git clone https://github.com/norman67cz/malla.git
cd malla
cp env.example .env
$EDITOR .env
docker compose -f docker-compose.yml -f docker-compose.prod.yml -f docker-compose.remote-build.yml up -d --build
```

Then open:

```bash
http://SERVER_IP:5008
```

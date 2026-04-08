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

## Multiple MQTT Servers
  The first version supports ingest from multiple MQTT brokers in one capture process.
  Configure them in `config.yaml` using `mqtt_sources:`.
  Example:

```yaml
mqtt_sources:
  - name: cz-west
    enabled: true
    broker_address: mqtt-west.example.net
    port: 1883
    username: user1
    password: pass1
    topic_prefix: msh
    topic_suffix: /+/+/+/#
    allowed_channels:
      - LongFast
      - MediumFast
      - ShortFast
  - name: cz-east
    enabled: true
    broker_address: mqtt-east.example.net
    port: 1883
    username: user2
    password: pass2
    topic_prefix: msh
    topic_suffix: /+/+/+/#
```

  If `mqtt_sources` is not defined, the existing single-broker config from `.env`
  is used as a backward-compatible fallback.
  Set `enabled: false` to keep a source definition in `config.yaml` without
  connecting to that broker.
  Each source may optionally define `allowed_channels` to accept only selected
  topic channel names before messages are parsed and inserted into the database.
  Raw receptions are kept per broker and stored with `mqtt_source`.
  Grouped views deduplicate packets across sources by `mesh_packet_id` when available.

## Uninstall
  sudo ./scripts/uninstall_malla_instance.sh --force
  PURGE_POSTGRES=1 sudo ./scripts/uninstall_malla_instance.sh --force
  PURGE_POSTGRES=1 PURGE_PACKAGES=1 sudo ./scripts/uninstall_malla_instance.sh --force

**Access the web interface:**
- Local: http://localhost:5008

## Running Both Tools Together

For a complete monitoring setup, run both tools simultaneously:

**Terminal 1 - Data Capture:**
```bash
export MALLA_MQTT_BROKER_ADDRESS="127.0.0.1"  # Replace with your broker
./malla-capture
```

**Terminal 2 - Web UI:**
```bash
./malla-web
```

Both tools use the same SQLite database concurrently using thread-safe connections.

## Docker Configuration

When using Docker, configuration is handled through environment variables defined in your `.env` file:

### Production Deployment with Gunicorn

For production deployments, Malla supports running with Gunicorn, a production-ready WSGI server that provides better performance and stability than Flask's development server.

**Option 1: Using environment variable (recommended)**
```bash
# In your .env file:
MALLA_WEB_COMMAND=/app/.venv/bin/malla-web-gunicorn
```

**Option 2: Using the production override file**
```bash
docker-compose -f docker-compose.yml -f docker-compose.prod.yml up -d
```

**Option 3: Direct script execution**
```bash
# For local development with uv:
uv run malla-web-gunicorn

# Or using the executable script:
./malla-web-gunicorn
```

The Gunicorn configuration automatically:
- Uses multiple worker processes based on CPU cores
- Enables proper logging and monitoring
- Configures appropriate timeouts and connection limits
- Provides better concurrent request handling

**Benefits of Gunicorn over Flask dev server:**
- Production-ready with proper process management
- Better performance under load
- Automatic worker process recycling
- Proper signal handling for graceful shutdowns
- Enhanced logging and monitoring capabilities

### Environment File Setup
1. **Copy the example:**
   ```bash
   cp env.example .env
   ```

2. **Configure your settings:**
   ```bash
   # Required: Set your MQTT broker address
   MALLA_MQTT_BROKER_ADDRESS=your.mqtt.broker.address

   # Optional: Customize other settings
   MALLA_NAME=My Malla Instance
   MALLA_WEB_PORT=5008
   MALLA_SECRET_KEY=your-production-secret-key
   ```

### Key Configuration Options
- `MALLA_MQTT_BROKER_ADDRESS`: Your MQTT broker IP/hostname (**required**)
- `MALLA_MQTT_PORT`: MQTT broker port (default: 1883)
- `MALLA_MQTT_USERNAME`/`MALLA_MQTT_PASSWORD`: MQTT authentication (optional)
- `MALLA_WEB_PORT`: Port to expose the web UI (default: 5008)
- `MALLA_NAME`: Display name in the web interface

### Data Persistence
Data is automatically stored in a Docker volume (`malla_data`) and persists across container restarts. No manual volume setup is required when using `docker-compose`.

## Configuration Options

### YAML configuration file *(recommended)*

Malla will automatically look for a file named `config.yaml` in the **current
working directory** when it starts.  You can point to an alternative file by
setting the `MALLA_CONFIG_FILE` environment variable.

If the file is not found, all built-in defaults are used (see
`config.sample.yaml`).

Copy the sample file and customise it:

```bash
cp config.sample.yaml config.yaml
$EDITOR config.yaml  # tweak values as required
```

The file is **git-ignored** so you will never accidentally commit secrets such
as your `secret_key`.

The following keys are recognised:

| YAML key        | Type   | Default                                  | Description                                   | Env-var override |
| --------------- | ------ | ---------------------------------------- | --------------------------------------------- | ---------------- |
| `name`          | str    | `"Malla"`                                | Display name shown in the navigation bar.     | `MALLA_NAME` |
| `home_markdown` | str    | `""`                                     | Markdown rendered on the dashboard homepage.  | `MALLA_HOME_MARKDOWN` |
| `secret_key`    | str    | `"dev-secret-key-change-in-production"` | Flask session secret key (change in prod!). (currently unused)   | `MALLA_SECRET_KEY` |
| `database_file` | str    | `"meshtastic_history.db"`                | SQLite database file location.                | `MALLA_DATABASE_FILE` |
| `host`          | str    | `"0.0.0.0"`                              | Interface to bind the web server to.          | `MALLA_HOST` |
| `port`          | int    | `5008`                                   | TCP port for the web server.                  | `MALLA_PORT` |
| `debug`         | bool   | `false`                                  | Run Flask in debug mode (unsafe for prod!).   | `MALLA_DEBUG` |
| `mqtt_broker_address` | str | `"127.0.0.1"`                      | MQTT broker hostname or IP address.           | `MALLA_MQTT_BROKER_ADDRESS` |
| `mqtt_port`     | int    | `1883`                                   | MQTT broker port.                              | `MALLA_MQTT_PORT` |
| `mqtt_username` | str    | `""`                                     | MQTT broker username (optional).               | `MALLA_MQTT_USERNAME` |
| `mqtt_password` | str    | `""`                                     | MQTT broker password (optional).               | `MALLA_MQTT_PASSWORD` |
| `mqtt_topic_prefix` | str | `"msh"`                                 | MQTT topic prefix for Meshtastic messages.    | `MALLA_MQTT_TOPIC_PREFIX` |
| `mqtt_topic_suffix` | str | `"/+/+/+/#"`                           | MQTT topic suffix pattern.                     | `MALLA_MQTT_TOPIC_SUFFIX` |
| `mqtt_client_id`    | str | `""`                                     | MQTT client ID. Leave empty for a randomly generated ID (recommended). | `MALLA_MQTT_CLIENT_ID` |
| `default_channel_key` | str | `"1PG7OiApB1nwvP+rz05pAQ=="`         | Default channel key(s) for decryption (base64). Supports comma-separated list of keys - each will be tried in order until successful. | `MALLA_DEFAULT_CHANNEL_KEY` |
| `data_retention_hours` | int | `0`                                     | Number of hours after which to delete old data (0 = never delete). Automatically cleans up packet_history and node_info records older than specified hours. | `MALLA_DATA_RETENTION_HOURS` |
| `gunicorn_workers` | int | `null` | Number of Gunicorn worker processes. `null` means auto-detect based on CPU cores. | `MALLA_GUNICORN_WORKERS` |
| `gunicorn_threads` | int | `1` | Number of threads per Gunicorn worker. Increase this for better concurrency, especially on I/O bound tasks. | `MALLA_GUNICORN_THREADS` |

Environment variables **always override** values coming from YAML file.

### Data Cleanup

Malla includes an automatic data cleanup feature to help manage database size over time. When enabled, it will:

1. Delete packet_history records older than the specified number of hours
2. Delete node_info records for nodes that haven't been seen recently and have no packets in the packet_history table
3. Repeat the cleanup process every hour in the background

To enable data cleanup, set the `data_retention_hours` configuration parameter to a positive value:

```yaml
# Keep data for 7 days (168 hours)
data_retention_hours: 168
```

Or via environment variable:
```bash
export MALLA_DATA_RETENTION_HOURS=168
```

Set to `0` (default) to disable cleanup completely.

## Embedding the Map

The map view can be embedded in other websites or used in a narrower width by collapsing the sidebar by default. This is particularly useful when you want to showcase your mesh network on your website or integrate it into other pages.

### URL Parameter

Add `?sidebar-collapsed=true` or `?sidebar-collapsed=1` to the map URL to collapse the sidebar by default:

```
https://your-malla-instance.com/map?sidebar-collapsed=true
```

The sidebar can still be expanded by users clicking the toggle button, giving them access to filters, statistics, and controls when needed.

### Embedding Example

```html
<iframe 
    src="https://your-malla-instance.com/map?sidebar-collapsed=true" 
    width="100%" 
    height="600" 
    frameborder="0"
    style="border: 0;">
</iframe>
```

This approach maximizes the visible map area while keeping full functionality accessible through the expandable sidebar.

## Contributing

Feel free to submit issues, feature requests, or pull requests to improve Malla!

## License

This project is licensed under the [MIT](LICENSE) license.

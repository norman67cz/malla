#!/usr/bin/env python3
"""
Meshtastic Mesh Health Web UI - Main Application

A Flask web application for browsing and analyzing Meshtastic mesh network data.
This is the main entry point for the web UI component.
"""

import atexit
import html
import json
import logging
import os
import sys
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import urlparse

from flask import Flask, session

# Import application configuration loader
from .config import AppConfig, get_config

# Optional CORS support will be checked inline
# Import configuration and database setup
from .database.connection import init_database
from .routes import register_routes

# Import utility functions for template filters
from .utils.formatting import format_node_id, format_time_ago
from .utils.i18n import normalize_language, translate
from .utils.node_utils import (
    start_cache_cleanup,
    stop_cache_cleanup,
)

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    handlers=[logging.FileHandler("app.log"), logging.StreamHandler(sys.stdout)],
)

logger = logging.getLogger(__name__)


def get_build_commit(package_dir: Path) -> str:
    """Return the deployed build commit from env or a build metadata file."""
    commit = os.getenv("MALLA_GIT_COMMIT", "").strip()
    if commit:
        return commit

    commit_file = package_dir.parent.parent / "BUILD_COMMIT"
    try:
        file_commit = commit_file.read_text(encoding="utf-8").strip()
    except OSError:
        return "unknown"

    return file_commit or "unknown"


def make_json_safe(obj):
    """
    Recursively convert an object to be JSON-serializable by handling bytes objects.

    Args:
        obj: The object to make JSON-safe

    Returns:
        A JSON-serializable version of the object
    """
    if isinstance(obj, bytes):
        # Convert bytes to hex string
        return obj.hex()
    elif isinstance(obj, dict):
        return {key: make_json_safe(value) for key, value in obj.items()}
    elif isinstance(obj, list | tuple):
        return [make_json_safe(item) for item in obj]
    elif hasattr(obj, "__dict__"):
        # Handle objects with attributes by converting to dict
        return make_json_safe(obj.__dict__)
    else:
        # Return as-is for JSON-serializable types (str, int, float, bool, None)
        return obj


class _HtmlAllowlistSanitizer(HTMLParser):
    """Small allowlist sanitizer for Markdown-rendered HTML."""

    allowed_tags = {
        "a",
        "p",
        "br",
        "strong",
        "em",
        "ul",
        "ol",
        "li",
        "code",
        "pre",
        "blockquote",
        "hr",
        "h1",
        "h2",
        "h3",
        "h4",
        "h5",
        "h6",
    }
    allowed_attrs = {
        "a": {"href", "title"},
    }
    void_tags = {"br", "hr"}
    allowed_schemes = {"http", "https", "mailto"}

    def __init__(self) -> None:
        super().__init__(convert_charrefs=False)
        self.parts: list[str] = []

    def _sanitize_href(self, href: str) -> str | None:
        parsed = urlparse(href)
        if not parsed.scheme:
            return href
        if parsed.scheme.lower() in self.allowed_schemes:
            return href
        return None

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag not in self.allowed_tags:
            return

        clean_attrs: list[str] = []
        allowed_attrs = self.allowed_attrs.get(tag, set())
        attr_dict = {name: value for name, value in attrs if name in allowed_attrs}

        if tag == "a":
            href = attr_dict.get("href")
            if href:
                safe_href = self._sanitize_href(href)
                if safe_href:
                    clean_attrs.append(f'href="{html.escape(safe_href, quote=True)}"')
                    clean_attrs.append('rel="noopener noreferrer"')
            title = attr_dict.get("title")
            if title:
                clean_attrs.append(f'title="{html.escape(title, quote=True)}"')
        else:
            for name, value in attr_dict.items():
                if value is not None:
                    clean_attrs.append(f'{name}="{html.escape(value, quote=True)}"')

        attrs_rendered = f" {' '.join(clean_attrs)}" if clean_attrs else ""
        self.parts.append(f"<{tag}{attrs_rendered}>")

    def handle_endtag(self, tag: str) -> None:
        if tag in self.allowed_tags and tag not in self.void_tags:
            self.parts.append(f"</{tag}>")

    def handle_data(self, data: str) -> None:
        self.parts.append(html.escape(data))

    def handle_entityref(self, name: str) -> None:
        self.parts.append(f"&{name};")

    def handle_charref(self, name: str) -> None:
        self.parts.append(f"&#{name};")

    def get_html(self) -> str:
        return "".join(self.parts)


def sanitize_markdown_html(rendered_html: str) -> str:
    """Sanitize HTML produced from dashboard markdown using a strict allowlist."""
    sanitizer = _HtmlAllowlistSanitizer()
    sanitizer.feed(rendered_html)
    sanitizer.close()
    return sanitizer.get_html()


def create_app(cfg: AppConfig | None = None):  # noqa: D401
    """Create and configure the Flask application.

    If *cfg* is ``None`` the configuration is loaded via :func:`get_config`.
    Tests can pass an :class:`~malla.config.AppConfig` instance directly which
    eliminates the need for fiddling with environment variables.
    """

    logger.info("Creating Flask application")

    # Get the package directory for templates and static files
    package_dir = Path(__file__).parent

    app = Flask(
        __name__,
        template_folder=str(package_dir / "templates"),
        static_folder=str(package_dir / "static"),
    )

    # ---------------------------------------------------------------------
    # Load application configuration (YAML + environment overrides)
    # ---------------------------------------------------------------------

    if cfg is None:
        cfg = get_config()
    else:
        # Ensure subsequent calls to get_config() return this instance (tests)
        from .config import _override_config  # local import to avoid circular

        _override_config(cfg)

    # Persist config on Flask instance for later use
    app.config["APP_CONFIG"] = cfg

    # Setup OpenTelemetry if endpoint is configured
    if cfg.otlp_endpoint:
        from .telemetry import setup_telemetry

        setup_telemetry(app, cfg.otlp_endpoint)

    # Mirror a few frequently-used values to top-level keys for backwards
    # compatibility with the existing code base. Over time we should migrate
    # direct usages to the nested ``APP_CONFIG`` object instead.
    app.config["SECRET_KEY"] = cfg.secret_key
    app.config["DATABASE_BACKEND"] = cfg.database_backend
    app.config["DATABASE_FILE"] = cfg.database_file
    app.config["POSTGRES_DSN"] = cfg.postgres_dsn

    # Ensure helper modules relying on env-var fallback pick up the correct DB
    # path in contexts where they cannot access Flask's app.config (e.g.
    # standalone scripts).  This is primarily relevant for the test suite.
    os.environ["MALLA_DATABASE_BACKEND"] = str(cfg.database_backend)
    os.environ["MALLA_DATABASE_FILE"] = str(cfg.database_file)
    if cfg.postgres_dsn:
        os.environ["MALLA_POSTGRES_DSN"] = str(cfg.postgres_dsn)

    # ---------------------------------------------------------------------

    # Add template filters for consistent formatting
    @app.template_filter("format_node_id")
    def format_node_id_filter(node_id):
        """Template filter for consistent node ID formatting."""
        return format_node_id(node_id)

    @app.template_filter("format_node_short_name")
    def format_node_short_name_filter(node_name):
        """Template filter for short node names."""
        if not node_name:
            return "Unknown"
        # If it's a long name with hex ID in parentheses, extract just the name part
        if " (" in node_name and node_name.endswith(")"):
            return node_name.split(" (")[0]
        return node_name

    @app.template_filter("format_time_ago")
    def format_time_ago_filter(dt):
        """Template filter for relative time formatting."""
        return format_time_ago(dt)

    @app.template_filter("safe_json")
    def safe_json_filter(obj, indent=None):
        """
        Template filter for safely serializing objects to JSON, handling bytes objects.

        Args:
            obj: The object to serialize
            indent: Optional indentation for pretty printing

        Returns:
            JSON string with bytes objects converted to hex strings
        """
        try:
            safe_obj = make_json_safe(obj)
            return json.dumps(safe_obj, indent=indent, ensure_ascii=False)
        except Exception as e:
            logger.warning(f"Error in safe_json filter: {e}")
            return json.dumps(
                {"error": f"Serialization failed: {str(e)}"}, indent=indent
            )

    @app.template_filter("format_rssi")
    def format_rssi_filter(rssi):
        """Template filter for consistent RSSI formatting with 1 decimal place."""
        if rssi is None:
            return "N/A"
        try:
            return f"{float(rssi):.1f}"
        except (ValueError, TypeError):
            return str(rssi)

    @app.template_filter("format_snr")
    def format_snr_filter(snr):
        """Template filter for consistent SNR formatting with 2 decimal places."""
        if snr is None:
            return "N/A"
        try:
            return f"{float(snr):.2f}"
        except (ValueError, TypeError):
            return str(snr)

    @app.template_filter("format_signal")
    def format_signal_filter(value, decimals=1):
        """Template filter for consistent signal value formatting with configurable decimal places."""
        if value is None:
            return "N/A"
        try:
            return f"{float(value):.{decimals}f}"
        except (ValueError, TypeError):
            return str(value)

    # ------------------------------------------------------------------
    # Markdown rendering filter & context processor for config variables
    # ------------------------------------------------------------------

    try:
        import markdown as _markdown  # import locally to avoid hard dependency at runtime until used
    except ModuleNotFoundError:  # pragma: no cover – dependency should be present
        _markdown = None  # type: ignore[assignment]

    @app.template_filter("markdown")
    def markdown_filter(text: str | None):  # noqa: ANN001
        """Render *text* (Markdown) to HTML for safe embedding."""

        if text is None:
            return ""
        if _markdown is None:
            logger.warning("markdown package not installed – returning raw text")
            return html.escape(text)
        from markupsafe import Markup

        rendered = _markdown.markdown(text)
        return Markup(sanitize_markdown_html(rendered))

    @app.context_processor
    def inject_config():
        """Inject selected config values into all templates."""
        current_lang = normalize_language(session.get("lang"))

        return {
            "APP_NAME": cfg.name,
            "APP_CONFIG": cfg,
            "DATABASE_FILE": cfg.database_file,
            "BUILD_COMMIT": get_build_commit(package_dir),
            "current_lang": current_lang,
            "t": lambda key: translate(key, current_lang),
        }

    # Initialize database
    logger.info("Initializing database connection")
    init_database()

    # Start periodic cache cleanup for node names
    logger.info("Starting node name cache cleanup background thread")
    start_cache_cleanup()

    # Register cleanup on app shutdown
    atexit.register(stop_cache_cleanup)

    # Register all routes
    logger.info("Registering application routes")
    register_routes(app)

    # Add health check endpoint
    @app.route("/health")
    def health_check():
        """Health check endpoint for monitoring."""
        return {
            "status": "healthy",
            "service": "meshtastic-mesh-health-ui",
            "version": "2.0.0",
        }

    # Add application info
    @app.route("/info")
    def app_info():
        """Application information endpoint."""
        return {
            "name": "Meshtastic Mesh Health Web UI",
            "version": "2.0.0",
            "description": "Web interface for monitoring Meshtastic mesh network health",
            "database_file": app.config["DATABASE_FILE"],
            "components": {
                "database": "Repository pattern with SQLite",
                "models": "Data models and packet parsing",
                "services": "Business logic layer",
                "utils": "Utility functions",
                "routes": "HTTP request handling",
            },
        }

    logger.info("Flask application created successfully")
    return app


def main():
    """Main entry point for the application."""
    logger.info("Starting Meshtastic Mesh Health Web UI")

    try:
        # Create the application
        app = create_app()

        # Use configuration values (environment overrides already applied)
        cfg: AppConfig = app.config.get("APP_CONFIG")  # type: ignore[assignment]

        host = cfg.host
        port = cfg.port
        debug = cfg.debug

        # Print startup information
        print("=" * 60)
        print("🌐 Meshtastic Mesh Health Web UI")
        print("=" * 60)
        print(f"Database: {app.config['DATABASE_FILE']}")
        print(f"Web UI: http://{host}:{port}")
        print(f"Debug mode: {debug}")
        print(f"Log level: {logging.getLogger().level}")
        print("=" * 60)
        print()

        logger.info(f"Starting server on {host}:{port} (debug={debug})")

        # Run the application
        app.run(host=host, port=port, debug=debug, threaded=True)

    except Exception as e:
        logger.error(f"Failed to start application: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()

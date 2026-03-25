"""
Main routes for the Meshtastic Mesh Health Web UI
"""

import hashlib
import hmac
import logging

from flask import Blueprint, flash, redirect, render_template, request, session, url_for

# Import from the new modular architecture
from ..database.repositories import (
    DashboardRepository,
)
from ..services.wiki_service import WikiService
from ..utils.i18n import normalize_language, translate

logger = logging.getLogger(__name__)
main_bp = Blueprint("main", __name__)


def _tr(key: str) -> str:
    return translate(key, normalize_language(session.get("lang")))


def _wiki_auth_digest(edit_key: str | None) -> str:
    if not edit_key:
        return ""
    return hashlib.sha256(edit_key.encode("utf-8")).hexdigest()


def _wiki_edit_available() -> bool:
    from ..config import get_config

    cfg = get_config()
    return bool((cfg.wiki_edit_key or "").strip())


def _wiki_edit_allowed() -> bool:
    from ..config import get_config

    cfg = get_config()
    expected = _wiki_auth_digest((cfg.wiki_edit_key or "").strip())
    current = str(session.get("wiki_edit_auth", ""))
    return bool(expected) and hmac.compare_digest(current, expected)


@main_bp.route("/")
def dashboard():
    """Dashboard route with network statistics."""
    try:
        # Get basic dashboard stats
        stats = DashboardRepository.get_stats()

        # Get gateway statistics from the new cached service
        from ..services.gateway_service import GatewayService

        gateway_stats = GatewayService.get_gateway_statistics(hours=24)
        gateway_count = gateway_stats.get("total_gateways", 0)

        return render_template(
            "dashboard.html",
            stats=stats,
            gateway_count=gateway_count,
        )
    except Exception as e:
        logger.error(f"Error loading dashboard: {e}")
        # Fallback to basic stats without gateway info
        stats = DashboardRepository.get_stats()
        return render_template(
            "dashboard.html",
            stats=stats,
            gateway_count=0,
            error_message="Some dashboard features may be unavailable",
        )


@main_bp.route("/map")
def map_view():
    """Node location map view."""
    try:
        return render_template("map.html")
    except Exception as e:
        logger.error(f"Error in map route: {e}")
        return f"Map error: {e}", 500


@main_bp.route("/longest-links")
def longest_links():
    """Longest links analysis page."""
    logger.info("Longest links route accessed")
    try:
        return render_template("longest_links.html")
    except Exception as e:
        logger.error(f"Error in longest links route: {e}")
        return f"Longest links error: {e}", 500


@main_bp.route("/line-of-sight")
def line_of_sight():
    """Line of sight analysis tool page."""
    logger.info("Line of sight tool route accessed")
    try:
        # Get optional query parameters for pre-loading analysis
        from_node_id = request.args.get("from")
        to_node_id = request.args.get("to")

        return render_template(
            "line_of_sight.html", from_node_id=from_node_id, to_node_id=to_node_id
        )
    except Exception as e:
        logger.error(f"Error in line of sight route: {e}")
        return f"Line of sight error: {e}", 500


@main_bp.route("/help")
def help_page():
    """Simple help page describing the main menu sections."""
    try:
        return render_template("help.html")
    except Exception as e:
        logger.error(f"Error in help route: {e}")
        return f"Help error: {e}", 500


@main_bp.route("/about")
def about_page():
    """Short about page describing the application."""
    try:
        return render_template("about.html")
    except Exception as e:
        logger.error(f"Error in about route: {e}")
        return f"About error: {e}", 500


@main_bp.route("/statistic")
def statistic_page():
    """Per-node packet type statistics page."""
    try:
        return render_template("statistic.html")
    except Exception as e:
        logger.error(f"Error in statistic route: {e}")
        return f"Statistic error: {e}", 500


@main_bp.route("/wiki")
def wiki_page():
    """Filesystem-backed Markdown wiki viewer/editor."""
    try:
        from ..config import get_config

        cfg = get_config()
        page = request.args.get("page")
        edit_mode = request.args.get("edit") == "1"
        pages = WikiService.list_pages(cfg)

        if not page and pages:
            page = pages[0].path

        selected_page, page_content, page_exists = WikiService.read_page(page, cfg)
        rendered_page_content = WikiService.render_internal_links(page_content)

        return render_template(
            "wiki.html",
            pages=pages,
            selected_page=selected_page,
            page_content=page_content,
            rendered_page_content=rendered_page_content,
            page_exists=page_exists,
            edit_mode=edit_mode and _wiki_edit_allowed(),
            wiki_edit_available=_wiki_edit_available(),
            wiki_edit_allowed=_wiki_edit_allowed(),
            wiki_base_dir=str(WikiService.get_base_dir(cfg)),
        )
    except ValueError as e:
        logger.warning(f"Invalid wiki path requested: {e}")
        flash(str(e), "danger")
        return redirect(url_for("main.wiki_page"))
    except Exception as e:
        logger.error(f"Error in wiki route: {e}")
        return f"Wiki error: {e}", 500


@main_bp.route("/wiki/unlock", methods=["POST"])
def wiki_unlock():
    """Unlock wiki editing for the current session."""
    from ..config import get_config

    cfg = get_config()
    submitted_key = request.form.get("edit_key", "")
    page = request.form.get("page")
    expected = (cfg.wiki_edit_key or "").strip()

    if not expected:
        flash(_tr("wiki.edit_unavailable"), "warning")
        return redirect(url_for("main.wiki_page", page=page))

    if hmac.compare_digest(submitted_key, expected):
        session["wiki_edit_auth"] = _wiki_auth_digest(expected)
        flash(_tr("wiki.unlocked"), "success")
        return redirect(url_for("main.wiki_page", page=page, edit=1))

    flash(_tr("wiki.invalid_key"), "danger")
    return redirect(url_for("main.wiki_page", page=page))


@main_bp.route("/wiki/lock", methods=["POST"])
def wiki_lock():
    """Lock wiki editing for the current session."""
    page = request.form.get("page")
    session.pop("wiki_edit_auth", None)
    flash(_tr("wiki.locked"), "secondary")
    return redirect(url_for("main.wiki_page", page=page))


@main_bp.route("/wiki/save", methods=["POST"])
def wiki_save():
    """Persist wiki markdown content to the filesystem."""
    from ..config import get_config

    if not _wiki_edit_allowed():
        flash(_tr("wiki.edit_locked"), "danger")
        return redirect(url_for("main.wiki_page"))

    cfg = get_config()
    page = request.form.get("page")
    content = request.form.get("content", "")

    try:
        saved_page = WikiService.write_page(page, content, cfg)
    except ValueError as e:
        logger.warning(f"Invalid wiki save path requested: {e}")
        flash(str(e), "danger")
        return redirect(url_for("main.wiki_page"))
    except Exception as e:
        logger.error(f"Error saving wiki page: {e}")
        flash(_tr("wiki.save_failed"), "danger")
        return redirect(url_for("main.wiki_page", page=page, edit=1))

    flash(_tr("wiki.saved"), "success")
    return redirect(url_for("main.wiki_page", page=saved_page))


@main_bp.route("/wiki/delete", methods=["POST"])
def wiki_delete():
    """Delete a wiki markdown file from the filesystem."""
    from ..config import get_config

    if not _wiki_edit_allowed():
        flash(_tr("wiki.edit_locked"), "danger")
        return redirect(url_for("main.wiki_page"))

    cfg = get_config()
    page = request.form.get("page")

    try:
        deleted_page = WikiService.delete_page(page, cfg)
    except ValueError as e:
        logger.warning(f"Invalid wiki delete path requested: {e}")
        flash(str(e), "danger")
        return redirect(url_for("main.wiki_page"))
    except Exception as e:
        logger.error(f"Error deleting wiki page: {e}")
        flash(_tr("wiki.delete_failed"), "danger")
        return redirect(url_for("main.wiki_page", page=page))

    flash(_tr("wiki.deleted"), "success")
    return redirect(url_for("main.wiki_page"))


@main_bp.route("/wiki/rename", methods=["POST"])
def wiki_rename():
    """Rename a wiki markdown file on the filesystem."""
    from ..config import get_config

    if not _wiki_edit_allowed():
        flash(_tr("wiki.edit_locked"), "danger")
        return redirect(url_for("main.wiki_page"))

    cfg = get_config()
    page = request.form.get("page")
    new_page = request.form.get("new_page")

    try:
        renamed_page = WikiService.rename_page(page, new_page, cfg)
    except ValueError as e:
        logger.warning(f"Invalid wiki rename path requested: {e}")
        flash(str(e), "danger")
        return redirect(url_for("main.wiki_page", page=page, edit=1))
    except Exception as e:
        logger.error(f"Error renaming wiki page: {e}")
        flash(_tr("wiki.rename_failed"), "danger")
        return redirect(url_for("main.wiki_page", page=page, edit=1))

    flash(_tr("wiki.renamed"), "success")
    return redirect(url_for("main.wiki_page", page=renamed_page, edit=1))


@main_bp.route("/set-language/<lang>")
def set_language(lang: str):
    """Store the selected UI language in the session and return back."""
    session["lang"] = normalize_language(lang)

    next_url = request.args.get("next", "").strip()
    if next_url.startswith("/"):
        return redirect(next_url)

    return redirect(url_for("main.dashboard"))

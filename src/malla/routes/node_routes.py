"""
Node-related routes for the Meshtastic Mesh Health Web UI
"""

import logging

from flask import Blueprint, render_template, request

# Import from the new modular architecture
from ..database.repositories import NodeRepository

logger = logging.getLogger(__name__)
node_bp = Blueprint("node", __name__)
VALID_PROTOCOL_WINDOWS = {"last_hour", "last_day", "all"}


@node_bp.route("/nodes")
def nodes():
    """Node browser page using modern table interface."""
    logger.info("Nodes route accessed")
    try:
        logger.info("Nodes page rendered")
        return render_template("nodes.html")
    except Exception as e:
        logger.error(f"Error in nodes route: {e}")
        return f"Nodes error: {e}", 500


@node_bp.route("/node/<node_id>")
def node_detail(node_id):
    """Node detail page showing comprehensive information about a specific node."""
    logger.info(f"Node detail route accessed for node {node_id}")
    try:
        protocol_window = request.args.get("protocol_window", "all")
        if protocol_window not in VALID_PROTOCOL_WINDOWS:
            protocol_window = "all"

        # Handle both hex ID and integer node ID
        if isinstance(node_id, str) and node_id.startswith("!"):
            node_id_int = int(node_id[1:], 16)
        elif isinstance(node_id, str) and not node_id.isdigit():
            try:
                node_id_int = int(node_id, 16)
            except ValueError:
                return "Invalid node ID format", 400
        else:
            node_id_int = int(node_id)

        # Get node details using the repository
        node_details = NodeRepository.get_node_details(
            node_id_int, protocol_window=protocol_window
        )
        if not node_details:
            return "Node not found", 404

        logger.info("Node detail page rendered successfully")
        return render_template("node_detail.html", **node_details)
    except Exception as e:
        logger.error(f"Error in node detail route: {e}")
        return f"Node detail error: {e}", 500

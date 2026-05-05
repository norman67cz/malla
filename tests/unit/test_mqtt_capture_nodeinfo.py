from types import SimpleNamespace
from unittest.mock import patch

import pytest
from meshtastic import config_pb2, mesh_pb2, mqtt_pb2, portnums_pb2

from malla import mqtt_capture

pytestmark = pytest.mark.unit


def _build_nodeinfo_message(hw_model: int) -> SimpleNamespace:
    user = mesh_pb2.User()
    user.id = "!7f6e5d4c"
    user.long_name = "Gabriela"
    user.short_name = "GAB"
    user.hw_model = hw_model
    user.role = config_pb2.Config.DeviceConfig.Role.CLIENT

    mesh_packet = mesh_pb2.MeshPacket()
    setattr(mesh_packet, "from", 0x7F6E5D4C)
    mesh_packet.to = 0
    mesh_packet.decoded.portnum = portnums_pb2.PortNum.NODEINFO_APP
    mesh_packet.decoded.payload = user.SerializeToString()

    service_envelope = mqtt_pb2.ServiceEnvelope()
    service_envelope.channel_id = "Bulgaria"
    service_envelope.packet.CopyFrom(mesh_packet)

    return SimpleNamespace(
        topic="msh/Bulgaria/2/e/Bulgaria/!a2e96b40",
        payload=service_envelope.SerializeToString(),
    )


def _assert_logged_success(mock_log_packet_to_database) -> None:
    (
        logged_topic,
        logged_service_envelope,
        logged_mesh_packet,
        processed_successfully,
        raw_service_envelope_data,
        parsing_error,
    ) = mock_log_packet_to_database.call_args.args[:6]
    assert logged_topic == "msh/Bulgaria/2/e/Bulgaria/!a2e96b40"
    assert logged_service_envelope is not None
    assert logged_mesh_packet is not None
    assert raw_service_envelope_data is not None
    assert processed_successfully is True
    assert parsing_error is None


@patch("malla.mqtt_capture.log_packet_to_database")
@patch("malla.mqtt_capture.get_node_display_name", return_value="Gabriela")
@patch("malla.mqtt_capture.update_node_cache")
def test_on_message_updates_node_cache_for_known_hw_model(
    mock_update_node_cache,
    _mock_get_node_display_name,
    mock_log_packet_to_database,
):
    msg = _build_nodeinfo_message(mesh_pb2.HardwareModel.THINKNODE_M3)

    mqtt_capture.on_message(None, {"name": "default"}, msg)

    mock_update_node_cache.assert_called_once_with(
        node_id=0x7F6E5D4C,
        hex_id="!7f6e5d4c",
        long_name="Gabriela",
        short_name="GAB",
        hw_model="THINKNODE_M3",
        role="CLIENT",
        is_licensed=False,
        mac_address=None,
        primary_channel="Bulgaria",
    )
    _assert_logged_success(mock_log_packet_to_database)


@patch("malla.mqtt_capture.log_packet_to_database")
@patch("malla.mqtt_capture.get_node_display_name", return_value="Gabriela")
@patch("malla.mqtt_capture.update_node_cache")
def test_on_message_keeps_unknown_hw_models_as_unknown_numeric_value(
    mock_update_node_cache,
    _mock_get_node_display_name,
    mock_log_packet_to_database,
):
    msg = _build_nodeinfo_message(999)

    mqtt_capture.on_message(None, {"name": "default"}, msg)

    mock_update_node_cache.assert_called_once()
    assert mock_update_node_cache.call_args.kwargs["hw_model"] == "UNKNOWN_999"
    _assert_logged_success(mock_log_packet_to_database)

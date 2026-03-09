#!/usr/bin/env python3
"""
Tests for LoRa modem preset capture from ADMIN_APP packets.
"""

import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "../../src"))

from meshtastic.protobuf import admin_pb2, config_pb2

from malla.mqtt_capture import (
    extract_lora_modem_preset_from_admin,
    format_lora_modem_preset,
)
from src.malla.database.repositories import NodeRepository


class TestLoRaModemPresetCapture:
    """Test extraction of LoRa modem preset information from ADMIN_APP payloads."""

    @pytest.mark.unit
    def test_extract_from_get_config_response(self):
        admin_message = admin_pb2.AdminMessage()
        admin_message.get_config_response.lora.use_preset = True
        admin_message.get_config_response.lora.modem_preset = (
            config_pb2.Config.LoRaConfig.ModemPreset.MEDIUM_FAST
        )

        result = extract_lora_modem_preset_from_admin(admin_message, 123, 456)

        assert result == (123, "MEDIUM_FAST", "get_config_response")

    @pytest.mark.unit
    def test_extract_from_set_config_targets_destination_node(self):
        admin_message = admin_pb2.AdminMessage()
        admin_message.set_config.lora.use_preset = True
        admin_message.set_config.lora.modem_preset = (
            config_pb2.Config.LoRaConfig.ModemPreset.LONG_FAST
        )

        result = extract_lora_modem_preset_from_admin(admin_message, 123, 456)

        assert result == (456, "LONG_FAST", "set_config")

    @pytest.mark.unit
    def test_extract_returns_none_without_lora_preset(self):
        admin_message = admin_pb2.AdminMessage()
        admin_message.get_config_response.device.role = (
            config_pb2.Config.DeviceConfig.Role.ROUTER
        )

        result = extract_lora_modem_preset_from_admin(admin_message, 123, 456)

        assert result is None

    @pytest.mark.unit
    def test_format_lora_modem_preset(self):
        assert format_lora_modem_preset("MEDIUM_FAST") == "MEDIUM-FAST"


class TestNodeRepositoryLoRaModemPreset:
    """Test repository formatting of LoRa preset state for node detail views."""

    @pytest.mark.unit
    def test_repository_formats_missing_lora_preset_as_not_captured(
        self, monkeypatch, test_client
    ):
        monkeypatch.setattr(
            NodeRepository,
            "get_bulk_node_names",
            staticmethod(lambda node_ids: {}),
        )
        monkeypatch.setattr(
            "src.malla.database.repositories.LocationRepository.get_latest_node_location",
            staticmethod(lambda node_id: None),
        )

        result = NodeRepository.get_node_details(1128074276)

        assert result is not None
        assert result["node"]["lora_modem_preset"] is None
        assert result["node"]["lora_modem_preset_status"] == "not_captured"
        assert result["node"]["lora_modem_preset_status_label"] == "Not captured yet"

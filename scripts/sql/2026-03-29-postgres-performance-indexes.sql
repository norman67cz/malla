-- PostgreSQL performance indexes for the largest packet_history access paths.
-- Run manually on production with:
--   psql "$MALLA_POSTGRES_DSN" -f scripts/sql/2026-03-29-postgres-performance-indexes.sql
--
-- These statements use CONCURRENTLY, so they must run outside a transaction block.

CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_ph_timestamp_desc
    ON packet_history (timestamp DESC);

CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_ph_source_timestamp_desc
    ON packet_history (mqtt_source, timestamp DESC);

CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_ph_from_timestamp_desc
    ON packet_history (from_node_id, timestamp DESC);

CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_ph_source_from_timestamp_desc
    ON packet_history (mqtt_source, from_node_id, timestamp DESC);

CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_ph_gateway_timestamp_desc
    ON packet_history (gateway_id, timestamp DESC);

CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_ph_source_gateway_timestamp_desc
    ON packet_history (mqtt_source, gateway_id, timestamp DESC);

CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_ph_port_from_timestamp_desc
    ON packet_history (portnum_name, from_node_id, timestamp DESC);

CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_ph_port_source_from_timestamp_desc
    ON packet_history (portnum_name, mqtt_source, from_node_id, timestamp DESC);

CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_ph_mesh_timestamp_desc
    ON packet_history (mesh_packet_id, timestamp DESC)
    WHERE mesh_packet_id IS NOT NULL AND mesh_packet_id != 0;

CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_ph_neighbor_latest
    ON packet_history (portnum_name, mqtt_source, from_node_id, timestamp DESC)
    WHERE portnum_name = 'NEIGHBORINFO_APP';

CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_ni_role_channel_hw
    ON node_info (role, primary_channel, hw_model);

ANALYZE packet_history;
ANALYZE node_info;

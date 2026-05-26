#!/usr/bin/with-contenv bashio

# ──────────────────────────────────────────────────────────────
# OpenReef - HA Add-on Entrypoint
# ──────────────────────────────────────────────────────────────

# HA Supervisor auto-provides SUPERVISOR_TOKEN when
# homeassistant_api: true is set in config.yaml
export HA_TOKEN="${SUPERVISOR_TOKEN}"
export HA_ADDON_MODE="true"
export NEXT_PUBLIC_HA_ADDON_MODE="true"
export OPENREEF_DATA_DIR="/data"
export PORT="3000"
export HOSTNAME="0.0.0.0"

if bashio::config.has_value 'log_level'; then
    bashio::log.level "$(bashio::config 'log_level')"
fi

bashio::log.info "Starting OpenReef..."
bashio::log.info "HA Addon Mode: enabled"
bashio::log.info "Ingress port: 8099 (nginx) -> 3000 (next.js)"

# Start nginx for ingress proxy (port 8099)
nginx

# Start Next.js standalone server on port 3000
cd /app
exec node server.js

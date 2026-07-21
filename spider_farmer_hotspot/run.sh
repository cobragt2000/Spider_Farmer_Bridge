#!/usr/bin/env bash
# Spider Farmer Hotspot add-on entrypoint.
#
# Brings up a Wi-Fi access point on a dedicated radio and runs dnsmasq so that
# Spider Farmer GGS controllers which join the hotspot resolve
# sf.mqtt.spider-farmer.com to the LOCAL Spider Farmer Bridge proxy (:8883)
# instead of the real cloud. The proxy still relays to the cloud over the
# host's wired uplink, so the phone app keeps working.
#
# Two AP backends:
#   nmcli   - NetworkManager creates the AP connection. Coexists cleanly with
#             Home Assistant OS (which uses NM), so it won't fight over the
#             radio. NM sets a static IP only; our dnsmasq still does DHCP + the
#             DNS override. Preferred on HAOS.
#   hostapd - raw hostapd owns the radio directly. Use when NM isn't present or
#             isn't managing the interface.
#   auto    - use nmcli if a running NetworkManager is reachable, else hostapd.
set -uo pipefail

OPTIONS=/data/options.json
NM_CON="SF-Bridge-Hotspot"
DNSMASQ_PID=""
HOSTAPD_PID=""
BACKEND=""

log() { echo "[sf-hotspot] $*"; }
get() { jq -r "$1" "$OPTIONS"; }

ENABLED=$(get '.hotspot_enabled')
AP_BACKEND=$(get '.ap_backend')
IFACE=$(get '.wifi_interface')
SSID=$(get '.ssid')
PASSWORD=$(get '.password')
CHANNEL=$(get '.channel')
HOTSPOT_IP=$(get '.hotspot_ip')
DNS_TARGET=$(get '.dns_target')
COUNTRY=$(get '.country_code')
UNMANAGE=$(get '.unmanage_via_nmcli')

# dns_target defaults to the hotspot gateway IP (this host on the AP iface),
# which is where the sf integration's proxy listens.
if [ -z "${DNS_TARGET}" ] || [ "${DNS_TARGET}" = "null" ]; then
  DNS_TARGET="${HOTSPOT_IP}"
fi

if [ "${ENABLED}" != "true" ]; then
  log "hotspot_enabled is false - nothing to do. Sleeping."
  exec sleep infinity
fi

# --- sanity checks -------------------------------------------------------
if ! ip link show "${IFACE}" >/dev/null 2>&1; then
  log "ERROR: interface '${IFACE}' not found. Available interfaces:"
  ip -o link show | awk -F': ' '{print "  " $2}'
  log "Set 'wifi_interface' to the radio you want to dedicate to the AP."
  exec sleep infinity
fi
if [ "${PASSWORD}" = "changeme123" ]; then
  log "WARNING: still using the default password 'changeme123' - change it."
fi
if [ "${#PASSWORD}" -lt 8 ]; then
  log "ERROR: WPA2 password must be at least 8 characters."
  exec sleep infinity
fi

# Derive the /24 the hotspot serves from hotspot_ip (e.g. 192.168.10.1 -> 192.168.10).
PREFIX="${HOTSPOT_IP%.*}"
DHCP_START="${PREFIX}.10"
DHCP_END="${PREFIX}.100"
NETMASK="255.255.255.0"

# --- pick the backend ----------------------------------------------------
nm_running() {
  command -v nmcli >/dev/null 2>&1 && \
    [ "$(nmcli -t -f RUNNING general status 2>/dev/null)" = "running" ]
}
case "${AP_BACKEND}" in
  nmcli)   BACKEND="nmcli" ;;
  hostapd) BACKEND="hostapd" ;;
  auto|*)
    if nm_running; then BACKEND="nmcli"; else BACKEND="hostapd"; fi ;;
esac
if [ "${BACKEND}" = "nmcli" ] && ! nm_running; then
  log "ap_backend=nmcli but no running NetworkManager reachable - falling back to hostapd."
  BACKEND="hostapd"
fi

log "backend=${BACKEND} interface=${IFACE} ssid='${SSID}' channel=${CHANNEL} ip=${HOTSPOT_IP}"
log "DNS: sf.mqtt.spider-farmer.com -> ${DNS_TARGET}"

# --- dnsmasq config (used by BOTH backends) ------------------------------
DNSMASQ_CONF=/tmp/dnsmasq.conf
cat > "${DNSMASQ_CONF}" <<DNSM
# Serve DHCP/DNS ONLY on the hotspot interface so the host's own upstream
# lookups (over the wired uplink) are never affected - this prevents a relay
# loop where the proxy would resolve the cloud host back to itself.
interface=${IFACE}
bind-interfaces
except-interface=lo
no-resolv
server=1.1.1.1
server=8.8.8.8
dhcp-range=${DHCP_START},${DHCP_END},${NETMASK},12h
dhcp-option=3,${HOTSPOT_IP}
dhcp-option=6,${HOTSPOT_IP}
# The redirect: point the GGS cloud endpoint at the local proxy.
address=/sf.mqtt.spider-farmer.com/${DNS_TARGET}
DNSM

# --- cleanup on exit -----------------------------------------------------
cleanup() {
  log "Shutting down hotspot..."
  [ -n "${DNSMASQ_PID}" ] && kill "${DNSMASQ_PID}" 2>/dev/null || true
  [ -n "${HOSTAPD_PID}" ] && kill "${HOSTAPD_PID}" 2>/dev/null || true
  if [ "${BACKEND}" = "nmcli" ]; then
    nmcli con down "${NM_CON}" 2>/dev/null || true
    nmcli con delete "${NM_CON}" 2>/dev/null || true
  else
    ip addr flush dev "${IFACE}" 2>/dev/null || true
    ip link set "${IFACE}" down 2>/dev/null || true
  fi
}
trap cleanup EXIT INT TERM

start_dnsmasq() {
  log "Starting dnsmasq..."
  dnsmasq --keep-in-foreground --conf-file="${DNSMASQ_CONF}" &
  DNSMASQ_PID=$!
  sleep 1
  if ! kill -0 "${DNSMASQ_PID}" 2>/dev/null; then
    log "ERROR: dnsmasq failed to start. Is port 53 already bound on the host?"
    DNSMASQ_PID=""
    return 1
  fi
}

# --- backend: nmcli ------------------------------------------------------
start_nmcli() {
  log "Configuring AP via NetworkManager..."
  nmcli dev set "${IFACE}" managed yes 2>/dev/null || true
  nmcli con down "${NM_CON}" 2>/dev/null || true
  nmcli con delete "${NM_CON}" 2>/dev/null || true

  if ! nmcli con add type wifi ifname "${IFACE}" con-name "${NM_CON}" \
        ssid "${SSID}" 2>&1; then
    log "ERROR: could not create NM connection."
    return 1
  fi
  # mode ap + static IP only; DHCP/DNS handled by our dnsmasq (NOT ipv4 shared,
  # which would start NM's own dnsmasq and clobber the DNS override).
  nmcli con modify "${NM_CON}" \
    802-11-wireless.mode ap \
    802-11-wireless.band bg \
    802-11-wireless.channel "${CHANNEL}" \
    wifi-sec.key-mgmt wpa-psk \
    wifi-sec.psk "${PASSWORD}" \
    802-11-wireless.country "${COUNTRY}" 2>/dev/null || true
  nmcli con modify "${NM_CON}" \
    ipv4.method manual \
    ipv4.addresses "${HOTSPOT_IP}/24" \
    ipv6.method ignore \
    connection.autoconnect yes

  if ! nmcli con up "${NM_CON}" 2>&1; then
    log "ERROR: failed to bring up the NM AP connection."
    return 1
  fi
  # give NM a moment to assign the IP before dnsmasq binds the interface
  sleep 2
  start_dnsmasq || return 1
  log "NetworkManager AP '${SSID}' is up."
}

# --- backend: hostapd ----------------------------------------------------
start_hostapd() {
  if [ "${UNMANAGE}" = "true" ] && command -v nmcli >/dev/null 2>&1; then
    log "Marking ${IFACE} unmanaged in NetworkManager (best effort)."
    nmcli dev set "${IFACE}" managed no 2>/dev/null || true
  fi

  HOSTAPD_CONF=/tmp/hostapd.conf
  cat > "${HOSTAPD_CONF}" <<HAPD
interface=${IFACE}
driver=nl80211
ssid=${SSID}
country_code=${COUNTRY}
hw_mode=g
channel=${CHANNEL}
ieee80211n=1
wmm_enabled=1
auth_algs=1
wpa=2
wpa_passphrase=${PASSWORD}
wpa_key_mgmt=WPA-PSK
rsn_pairwise=CCMP
HAPD

  log "Configuring ${IFACE}..."
  ip link set "${IFACE}" down || true
  pkill -f "wpa_supplicant.*${IFACE}" 2>/dev/null || true
  ip addr flush dev "${IFACE}" || true
  ip link set "${IFACE}" up
  ip addr add "${HOTSPOT_IP}/24" dev "${IFACE}"

  start_dnsmasq || return 1

  log "Starting hostapd..."
  hostapd "${HOSTAPD_CONF}" &
  HOSTAPD_PID=$!
  sleep 1
  if ! kill -0 "${HOSTAPD_PID}" 2>/dev/null; then
    log "ERROR: hostapd failed to start. If NetworkManager owns ${IFACE}, set"
    log "ap_backend=nmcli or unmanage_via_nmcli=true."
    HOSTAPD_PID=""
    return 1
  fi
}

# --- run -----------------------------------------------------------------
if [ "${BACKEND}" = "nmcli" ]; then
  if ! start_nmcli; then
    log "nmcli backend failed - retrying with hostapd."
    BACKEND="hostapd"
    start_hostapd || { log "Both backends failed."; exec sleep infinity; }
  fi
else
  start_hostapd || { log "hostapd backend failed."; exec sleep infinity; }
fi

log "Hotspot running. Waiting on services..."
# Block on whichever long-lived services we started; if one dies, exit so
# Supervisor restarts the add-on (cleanup runs via trap).
while true; do
  [ -n "${DNSMASQ_PID}" ] && ! kill -0 "${DNSMASQ_PID}" 2>/dev/null && { log "dnsmasq exited."; break; }
  [ -n "${HOSTAPD_PID}" ] && ! kill -0 "${HOSTAPD_PID}" 2>/dev/null && { log "hostapd exited."; break; }
  sleep 5
done

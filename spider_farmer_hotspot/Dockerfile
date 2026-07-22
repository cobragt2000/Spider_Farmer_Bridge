# The Supervisor injects the correct per-architecture base image via the
# BUILD_FROM build-arg (archs are declared in config.yaml). The default below
# is only a fallback for a plain `docker build` and silences Docker's
# InvalidDefaultArgInFrom warning.
ARG BUILD_FROM=ghcr.io/home-assistant/amd64-base:3.19
FROM ${BUILD_FROM}

LABEL \
  org.opencontainers.image.source="https://github.com/cobragt2000/spider_farmer_bridge"

# hostapd            - AP backend when NetworkManager isn't in play
# dnsmasq            - DHCP for hotspot clients + the local DNS override
# networkmanager-cli - nmcli, the AP backend that coexists with HAOS's NM
# iw / iproute2 / wireless-tools - bring the radio up and into AP mode
# wireless-regdb     - regulatory database (channel/country rules)
# jq                 - read /data/options.json
RUN apk add --no-cache \
    hostapd \
    dnsmasq \
    networkmanager-cli \
    iw \
    iproute2 \
    nftables \
    tcpdump \
    wireless-tools \
    wireless-regdb \
    jq \
    python3

COPY run.sh /run.sh
COPY status_server.py /status_server.py
RUN chmod a+x /run.sh

CMD [ "/run.sh" ]

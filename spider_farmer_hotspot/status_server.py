#!/usr/bin/env python3
"""Tiny status page for the Spider Farmer Hotspot add-on (served via HA ingress).

Shows the AP settings, the DNS redirect target, whether the integration's proxy
is listening on :8883, and the list of connected Wi-Fi clients (DHCP leases).
"""
import html
import json
import os
import socket
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

OPTIONS = "/data/options.json"
LEASES = "/data/dnsmasq.leases"
PORT = int(os.environ.get("INGRESS_PORT", "8099"))


def opts():
    try:
        with open(OPTIONS) as f:
            return json.load(f)
    except Exception:
        return {}


def leases():
    rows = []
    try:
        with open(LEASES) as f:
            for ln in f:
                p = ln.split()
                if len(p) >= 4:
                    rows.append((p[1], p[2], p[3], p[0]))  # mac, ip, name, expiry
    except FileNotFoundError:
        pass
    return rows


def proxy_listening(port=8883):
    for fam, addr in ((socket.AF_INET, ("127.0.0.1", port)),):
        s = socket.socket(fam, socket.SOCK_STREAM)
        s.settimeout(0.4)
        try:
            if s.connect_ex(addr) == 0:
                return True
        except OSError:
            pass
        finally:
            s.close()
    return False


def page():
    o = opts()
    dns_target = o.get("dns_target") or o.get("hotspot_ip", "")
    rows = leases()
    up = proxy_listening()
    proxy_html = (
        "<span style='color:#3fb950'>listening ✓</span>" if up
        else "<span style='color:#f85149'>NOT listening ✗ — is the Spider "
             "Farmer Bridge integration running?</span>"
    )
    trs = ""
    for mac, ip, name, exp in rows:
        try:
            left = int(exp) - int(time.time())
            lease = f"{left // 60} min" if left > 0 else "expired"
        except Exception:
            lease = html.escape(exp)
        nm = "(unknown)" if name in ("*", "") else html.escape(name)
        trs += (f"<tr><td>{nm}</td><td>{html.escape(ip)}</td>"
                f"<td>{html.escape(mac)}</td><td>{lease}</td></tr>")
    if not trs:
        trs = "<tr><td colspan=4 style='opacity:.55'>No clients connected yet</td></tr>"
    e = lambda v: html.escape(str(v))
    return f"""<!doctype html><html><head><meta charset=utf-8>
<meta http-equiv=refresh content=10>
<title>Spider Farmer Hotspot</title>
<style>
body{{font-family:system-ui,sans-serif;margin:16px;background:#0e0e0e;color:#e6e6e6}}
h2{{font-weight:500;margin:.2em 0}} h3{{font-weight:500}}
table{{border-collapse:collapse;width:100%}}
td,th{{text-align:left;padding:7px 9px;border-bottom:1px solid #2a2a2a;font-size:14px}}
th{{color:#9aa;font-weight:400}}
.card{{background:#181818;border-radius:12px;padding:12px 16px;margin-bottom:14px}}
.k{{color:#8b98a5}}
</style></head><body>
<h2>Spider Farmer Hotspot</h2>
<div class=card>
  <div><span class=k>SSID:</span> {e(o.get('ssid',''))} &nbsp;
       <span class=k>Channel:</span> {e(o.get('channel',''))} &nbsp;
       <span class=k>AP IP:</span> {e(o.get('hotspot_ip',''))} &nbsp;
       <span class=k>Interface:</span> {e(o.get('wifi_interface',''))}</div>
  <div style='margin-top:6px'><span class=k>DNS redirect:</span>
       sf.mqtt.spider-farmer.com &rarr; {e(dns_target)}:8883</div>
  <div style='margin-top:6px'><span class=k>Proxy (:8883):</span> {proxy_html}</div>
</div>
<div class=card>
  <h3>Connected clients ({len(rows)})</h3>
  <table><tr><th>Name</th><th>IP</th><th>MAC</th><th>Lease left</th></tr>{trs}</table>
</div>
<p style='opacity:.5;font-size:12px'>Auto-refreshes every 10s. Grow gear should
appear here within a minute of joining the hotspot. If a device is listed here
but still offline in the app, the proxy/redirect is the next thing to check.</p>
</body></html>"""


class H(BaseHTTPRequestHandler):
    def do_GET(self):
        body = page().encode()
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *a):
        pass


if __name__ == "__main__":
    ThreadingHTTPServer(("0.0.0.0", PORT), H).serve_forever()

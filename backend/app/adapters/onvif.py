"""ONVIF Profile S adapter.

Two jobs. WS-Discovery finds cameras on the local network without anyone
typing an IP address, which is what makes bulk onboarding of a department's
existing kit practical. GetStreamUri then asks each device for its own RTSP
URL rather than guessing a vendor-specific path.

Implemented against the wire protocol directly — WS-Discovery is a small
multicast SOAP exchange and the device service is plain SOAP over HTTP — so
onboarding does not pull in a heavyweight ONVIF stack. `python-onvif-zeep` is
the drop-in upgrade if full Profile T support is ever needed.
"""

import logging
import re
import socket
import struct
import urllib.error
import urllib.request
import uuid
from urllib.parse import urlparse, urlunparse

from ..config import settings
from .base import AdapterInfo, DiscoveredCamera

log = logging.getLogger("sentinel.adapters.onvif")

WS_DISCOVERY_ADDR = ("239.255.255.250", 3702)

PROBE = """<?xml version="1.0" encoding="UTF-8"?>
<e:Envelope xmlns:e="http://www.w3.org/2003/05/soap-envelope"
            xmlns:w="http://schemas.xmlsoap.org/ws/2004/08/addressing"
            xmlns:d="http://schemas.xmlsoap.org/ws/2005/04/discovery"
            xmlns:dn="http://www.onvif.org/ver10/network/wsdl">
  <e:Header>
    <w:MessageID>uuid:{msg_id}</w:MessageID>
    <w:To e:mustUnderstand="true">urn:schemas-xmlsoap-org:ws:2005:04:discovery</w:To>
    <w:Action e:mustUnderstand="true">http://schemas.xmlsoap.org/ws/2005/04/discovery/Probe</w:Action>
  </e:Header>
  <e:Body>
    <d:Probe><d:Types>dn:NetworkVideoTransmitter</d:Types></d:Probe>
  </e:Body>
</e:Envelope>"""

GET_PROFILES = """<?xml version="1.0" encoding="UTF-8"?>
<s:Envelope xmlns:s="http://www.w3.org/2003/05/soap-envelope">
  <s:Body xmlns:trt="http://www.onvif.org/ver10/media/wsdl">
    <trt:GetProfiles/>
  </s:Body>
</s:Envelope>"""

GET_STREAM_URI = """<?xml version="1.0" encoding="UTF-8"?>
<s:Envelope xmlns:s="http://www.w3.org/2003/05/soap-envelope">
  <s:Body xmlns:trt="http://www.onvif.org/ver10/media/wsdl"
          xmlns:tt="http://www.onvif.org/ver10/schema">
    <trt:GetStreamUri>
      <trt:StreamSetup>
        <tt:Stream>RTP-Unicast</tt:Stream>
        <tt:Transport><tt:Protocol>RTSP</tt:Protocol></tt:Transport>
      </trt:StreamSetup>
      <trt:ProfileToken>{token}</trt:ProfileToken>
    </trt:GetStreamUri>
  </s:Body>
</s:Envelope>"""

XADDR_RE = re.compile(r"<[^>]*XAddrs[^>]*>([^<]+)<", re.I)
SCOPE_RE = re.compile(r"<[^>]*Scopes[^>]*>([^<]+)<", re.I)
TOKEN_RE = re.compile(r'token="([^"]+)"')
URI_RE = re.compile(r"<[^>]*Uri[^>]*>([^<]+)<", re.I)


def _scope_value(scopes: str, key: str) -> str:
    for scope in scopes.split():
        if f"/{key}/" in scope:
            return urllib.request.unquote(scope.rsplit("/", 1)[-1])
    return ""


class OnvifAdapter:
    key = "onvif"
    label = "ONVIF Profile S devices"
    vendor = "any ONVIF-conformant"
    protocols = ["ONVIF", "RTSP"]

    def configured(self) -> bool:
        return settings.onvif_discovery_enabled

    def info(self) -> AdapterInfo:
        return AdapterInfo(
            self.key, self.label, self.vendor, self.protocols, self.configured(),
            "WS-Discovery multicast on the local network"
            if self.configured() else "set ONVIF_DISCOVERY_ENABLED=true to scan")

    def discover(self) -> list[DiscoveredCamera]:
        if not self.configured():
            return []
        found = []
        for xaddr, scopes in self._ws_discover():
            cam = self._describe(xaddr, scopes)
            if cam:
                found.append(cam)
        return found

    def _ws_discover(self) -> list[tuple[str, str]]:
        """Multicast a Probe and collect whatever answers before the timeout."""
        msg = PROBE.format(msg_id=uuid.uuid4()).encode()
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.setsockopt(socket.IPPROTO_IP, socket.IP_MULTICAST_TTL,
                        struct.pack("b", 2))
        sock.settimeout(settings.onvif_discovery_timeout_s)
        results, seen = [], set()
        try:
            sock.sendto(msg, WS_DISCOVERY_ADDR)
            while True:
                try:
                    data, _ = sock.recvfrom(65535)
                except socket.timeout:
                    break
                text = data.decode("utf-8", "replace")
                m = XADDR_RE.search(text)
                if not m:
                    continue
                xaddr = m.group(1).split()[0]
                if xaddr in seen:
                    continue
                seen.add(xaddr)
                scopes = SCOPE_RE.search(text)
                results.append((xaddr, scopes.group(1) if scopes else ""))
        except OSError as exc:
            log.warning("WS-Discovery failed: %s", exc)
        finally:
            sock.close()
        return results

    def _soap(self, url: str, body: str, action: str) -> str | None:
        req = urllib.request.Request(
            url, data=body.encode(),
            headers={"Content-Type": f'application/soap+xml; charset=utf-8; action="{action}"'},
            method="POST")
        try:
            with urllib.request.urlopen(req, timeout=6) as resp:
                return resp.read().decode("utf-8", "replace")
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            log.debug("SOAP call to %s failed: %s", url, exc)
            return None

    def _describe(self, xaddr: str, scopes: str) -> DiscoveredCamera | None:
        host = urlparse(xaddr).hostname or xaddr
        name = _scope_value(scopes, "name") or f"ONVIF {host}"
        hardware = _scope_value(scopes, "hardware")

        media_url = urlunparse(urlparse(xaddr)._replace(path="/onvif/media_service"))
        profiles = self._soap(media_url, GET_PROFILES,
                              "http://www.onvif.org/ver10/media/wsdl/GetProfiles")
        rtsp = ""
        if profiles:
            token = TOKEN_RE.search(profiles)
            if token:
                uri_resp = self._soap(
                    media_url, GET_STREAM_URI.format(token=token.group(1)),
                    "http://www.onvif.org/ver10/media/wsdl/GetStreamUri")
                if uri_resp:
                    m = URI_RE.search(uri_resp)
                    if m:
                        rtsp = m.group(1).strip()

        # A device that answered discovery but not GetStreamUri is still worth
        # registering; an operator can fill the URL in by hand.
        return DiscoveredCamera(
            external_id=f"onvif-{host.replace('.', '-')}",
            name=name,
            rtsp_url=rtsp,
            department=settings.onvif_default_department,
            camera_type="IP",
            vendor=hardware or "ONVIF device",
            location_name=_scope_value(scopes, "location"),
            reachable=bool(rtsp),
            extra={"xaddr": xaddr, "scopes": scopes},
        )

    def probe(self, camera: DiscoveredCamera) -> bool | None:
        if not camera.rtsp_url:
            return None
        parsed = urlparse(camera.rtsp_url)
        if not parsed.hostname:
            return None
        try:
            with socket.create_connection((parsed.hostname, parsed.port or 554), timeout=4):
                return True
        except OSError:
            return False

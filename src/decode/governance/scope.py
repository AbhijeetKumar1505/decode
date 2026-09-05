"""Engagement scope — the authorization boundary for a mission.

A ScopePolicy is an allowlist of targets (IPs, CIDRs, hostnames, and
``*.wildcard`` domains). Anything not explicitly in scope is out of scope.
This is the hard boundary that makes an autonomous offensive agent safe to run:
no matter what the planner or an LLM proposes, execution against an
out-of-scope target is refused before a command is ever built.
"""

import ipaddress
from urllib.parse import urlparse


class ScopePolicy:
    def __init__(self, allowed: list[str] | None = None, allow_all: bool = False):
        self.allow_all = allow_all
        self._networks: list[ipaddress._BaseNetwork] = []
        self._hosts: set = set()
        self._domains: set = set()  # suffixes from *.example.com -> example.com
        for entry in allowed or []:
            self.add(entry)

    def add(self, entry: str) -> None:
        entry = (entry or "").strip()
        if not entry:
            return
        try:
            self._networks.append(ipaddress.ip_network(entry, strict=False))
            return
        except ValueError:
            pass
        if entry.startswith("*."):
            self._domains.add(entry[2:].lower())
        else:
            self._hosts.add(entry.lower())

    @staticmethod
    def _extract_host(target: str) -> str:
        target = (target or "").strip()
        if "://" in target:
            parsed = urlparse(target)
            return (parsed.hostname or "").strip()
        # strip a trailing :port for host:port (but not for bare IPv6/CIDR)
        if target.count(":") == 1 and "/" not in target:
            head = target.split(":", 1)[0]
            return head
        return target

    def is_in_scope(self, target: str) -> bool:
        if self.allow_all:
            return True
        host = self._extract_host(target)
        if not host:
            return False

        # IP address contained in an allowed network
        try:
            ip = ipaddress.ip_address(host)
            return any(ip in net for net in self._networks)
        except ValueError:
            pass

        # A network target (e.g. 10.0.0.0/24) must be a subnet of an allowed net
        try:
            net = ipaddress.ip_network(host, strict=False)
            return any(
                net.subnet_of(a) for a in self._networks if a.version == net.version
            )
        except ValueError:
            pass

        h = host.lower()
        if h in self._hosts:
            return True
        return any(h == d or h.endswith("." + d) for d in self._domains)

    def describe(self) -> str:
        if self.allow_all:
            return "ALLOW ALL (no scope restriction)"
        parts = (
            [str(n) for n in self._networks]
            + sorted(self._hosts)
            + [f"*.{d}" for d in sorted(self._domains)]
        )
        return ", ".join(parts) if parts else "(empty scope — everything denied)"

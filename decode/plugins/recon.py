from .base import Plugin, RiskLevel
import socket


class SubdomainEnumerator(Plugin):
    def __init__(self):
        super().__init__()
        self.name = "subdomain_enum"
        self.description = (
            "Discover subdomains for a given target domain using DNS lookup"
        )
        self.risk_level = RiskLevel.READ
        self.schema = {
            "required": ["domain"],
            "properties": {
                "domain": {
                    "type": "string",
                    "description": "Target base domain (e.g. google.com)",
                }
            },
        }

    def execute(self, domain: str) -> str:
        common_subdomains = [
            "www",
            "mail",
            "remote",
            "blog",
            "webmail",
            "server",
            "ns1",
            "ns2",
            "smtp",
            "secure",
            "vpn",
            "api",
            "dev",
            "staging",
        ]

        found = []
        for sub in common_subdomains:
            target_hostname = f"{sub}.{domain}"
            try:
                ip = socket.gethostbyname(target_hostname)
                found.append(f"{target_hostname} -> {ip}")
            except socket.gaierror:
                pass

        if found:
            return f"Subdomains found: {', '.join(found)}"
        return "No common subdomains resolved."

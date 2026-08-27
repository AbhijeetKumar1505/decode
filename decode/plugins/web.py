from .base import Plugin, RiskLevel
import requests


class WebScanner(Plugin):
    def __init__(self):
        super().__init__()
        self.name = "web_vuln_scan"
        self.description = "Basic web vulnerability scanner (SQLi, XSS, LFI)"
        self.risk_level = RiskLevel.WRITE
        self.schema = {
            "required": ["url"],
            "properties": {
                "url": {"type": "string", "description": "Target URL to scan"}
            },
        }

    def execute(self, url: str) -> str:
        payloads = ["' OR 1=1--", "<script>alert(1)</script>", "../etc/passwd"]
        results = []
        for payload in payloads:
            try:
                resp = requests.get(f"{url}?test={payload}", timeout=5)
                results.append(f"Payload: {payload} -> {resp.status_code}")
            except requests.RequestException:
                results.append(f"Payload: {payload} -> timeout/error")
        return " | ".join(results)


class DirBruteScanner(Plugin):
    def __init__(self):
        super().__init__()
        self.name = "dir_brute"
        self.description = "Brute-force directories and files on a web server to find hidden panels or config files"
        self.risk_level = RiskLevel.WRITE
        self.schema = {
            "required": ["url"],
            "properties": {
                "url": {
                    "type": "string",
                    "description": "Target base URL (e.g. http://example.com)",
                },
                "common_only": {
                    "type": "boolean",
                    "description": "Check only top 5 common paths",
                },
            },
        }

    def execute(self, url: str, common_only: bool = False) -> str:
        if not url.endswith("/"):
            url += "/"

        paths = [
            ".env",
            "admin/",
            "wp-admin/",
            ".git/",
            "config.php",
            "db.sqlite",
            "backup.zip",
            "api/",
            "robots.txt",
            "login.php",
        ]
        if common_only:
            paths = paths[:5]

        found = []
        for path in paths:
            target_url = f"{url}{path}"
            try:
                resp = requests.head(target_url, timeout=3, allow_redirects=False)
                if resp.status_code in [200, 301, 302, 403]:
                    found.append(f"/{path} ({resp.status_code})")
            except Exception:
                try:
                    resp = requests.get(target_url, timeout=3, allow_redirects=False)
                    if resp.status_code in [200, 301, 302, 403]:
                        found.append(f"/{path} ({resp.status_code})")
                except Exception:
                    pass

        if found:
            return f"Paths found: {', '.join(found)}"
        return "No common paths discovered."

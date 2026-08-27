from .base import Plugin, RiskLevel
import socket

try:
    import nmap

    HAS_NMAP = True
except ImportError:
    HAS_NMAP = False


class NetworkScanner(Plugin):
    def __init__(self):
        super().__init__()
        self.name = "nmap_scan"
        self.description = "Perform network port scanning and service detection"
        self.risk_level = RiskLevel.WRITE
        self.schema = {
            "required": ["target"],
            "properties": {
                "target": {"type": "string", "description": "Target IP or hostname"},
                "flags": {
                    "type": "string",
                    "description": "Nmap flags (default: -sC -sV)",
                },
            },
        }

    def execute(self, target: str, flags: str = "-sC -sV") -> str:
        if HAS_NMAP:
            try:
                nm = nmap.PortScanner()
                nm.scan(target, arguments=flags)
                return str(nm.csv()).replace("\n", " | ")
            except Exception:
                pass
        return self._python_port_scan(target)

    def _python_port_scan(self, target: str) -> str:
        common_ports = [
            21,
            22,
            23,
            25,
            53,
            80,
            110,
            111,
            135,
            139,
            143,
            443,
            445,
            993,
            995,
            1723,
            3306,
            3389,
            5900,
            8080,
        ]
        open_ports = []
        for port in common_ports:
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                s.settimeout(0.5)
                if s.connect_ex((target, port)) == 0:
                    open_ports.append(str(port))

        if open_ports:
            return (
                f"Nmap missing. Python scan found open ports: {', '.join(open_ports)}"
            )
        return "Nmap missing. Python scan found no common open ports."

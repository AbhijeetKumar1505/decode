import platform
import subprocess
from pathlib import Path
from typing import Dict, Any, List
from datetime import datetime
from pydantic import BaseModel


class BootstrapReport(BaseModel):
    system: str
    version: str
    python: str
    docker: str
    nmap: str
    ffuf: str
    timestamp: str = ""


class SecurityCheck(BaseModel):
    check: str
    status: str
    detail: str = ""


class BootstrapEngine:
    def __init__(self, data_dir: Path = Path("data")):
        self.data_dir = data_dir
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.report_path = data_dir / "bootstrap_report.json"

    def detect_distro(self) -> Dict[str, str]:
        result = {"system": platform.system(), "version": platform.version()}
        if platform.system() == "Linux":
            try:
                os_release = Path("/etc/os-release").read_text(encoding="utf-8")
                for line in os_release.splitlines():
                    if "=" in line:
                        k, v = line.split("=", 1)
                        result[k.lower()] = v.strip('"')
            except (OSError, UnicodeError):
                pass
        return result

    def system_update(self) -> Dict[str, Any]:
        raise RuntimeError(
            "system update is disabled; use a separately approved maintenance "
            "capability through ExecutionCoordinator"
        )

    def check_security(self) -> List[SecurityCheck]:
        checks = []
        items = [
            ("sudo access", self._check_command("sudo", "-V")),
            ("python version", self._check_version("python3", "--version")),
            ("pip version", self._check_version("pip3", "--version")),
            ("docker", self._check_version("docker", "--version")),
            ("git", self._check_version("git", "--version")),
            ("gcc", self._check_version("gcc", "--version")),
            ("go", self._check_version("go", "version")),
            ("rust", self._check_version("rustc", "--version")),
        ]
        for name, status in items:
            checks.append(SecurityCheck(check=name, status=status, detail=""))
        return checks

    def _check_command(self, cmd: str, arg: str) -> str:
        try:
            r = subprocess.run([cmd, arg], capture_output=True, text=True, timeout=10)
            return "installed" if r.returncode == 0 else "missing"
        except (FileNotFoundError, subprocess.TimeoutExpired):
            return "missing"

    def _check_version(self, cmd: str, arg: str) -> str:
        try:
            r = subprocess.run([cmd, arg], capture_output=True, text=True, timeout=10)
            if r.returncode == 0:
                out = r.stdout or r.stderr
                return out.splitlines()[0].strip() if out else "installed"
            return "missing"
        except (FileNotFoundError, subprocess.TimeoutExpired):
            return "missing"

    def generate_report(self) -> BootstrapReport:
        distro = self.detect_distro()
        report = BootstrapReport(
            system=distro.get("id", platform.system()),
            version=distro.get("version_id", platform.version()),
            python=self._check_version("python3", "--version"),
            docker=self._check_command("docker", "--version"),
            nmap=self._check_command("nmap", "--version"),
            ffuf=self._check_command("ffuf", "-V"),
            timestamp=datetime.now().isoformat(),
        )
        self.report_path.write_text(report.model_dump_json(indent=2))
        return report

    def run(self, do_update: bool = False) -> Dict[str, Any]:
        result: Dict[str, Any] = {
            "distro": self.detect_distro(),
            "security_checks": [c.model_dump() for c in self.check_security()],
            "bootstrap_report": self.generate_report().model_dump(),
        }
        if do_update:
            result["system_update"] = {
                "updated": False,
                "reason": (
                    "system update is disabled; use a separately approved "
                    "maintenance capability through ExecutionCoordinator"
                ),
            }
        result["timestamp"] = datetime.now().isoformat()
        return result

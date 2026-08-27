"""Capability → MITRE ATT&CK mapping.

Ties Decode's capability taxonomy to ATT&CK techniques/tactics so plans and
findings carry standard references (the findings table already has
technique_id / mitre_tactic columns). This is the backbone of the knowledge
layer: it turns "we ran a port scan" into "Discovery / T1046".
"""

from dataclasses import dataclass
from typing import Dict, Optional


@dataclass(frozen=True)
class AttackTechnique:
    technique_id: str
    name: str
    tactic: str


# capability -> ATT&CK technique
CAPABILITY_ATTACK: Dict[str, AttackTechnique] = {
    "host_discovery": AttackTechnique("T1018", "Remote System Discovery", "Discovery"),
    "port_scan": AttackTechnique("T1046", "Network Service Discovery", "Discovery"),
    "service_detection": AttackTechnique("T1046", "Network Service Discovery", "Discovery"),
    "os_detection": AttackTechnique("T1082", "System Information Discovery", "Discovery"),
    "subdomain_enum": AttackTechnique("T1590.005", "Gather Victim Network Information: IP Addresses", "Reconnaissance"),
    "osint": AttackTechnique("T1593", "Search Open Websites/Domains", "Reconnaissance"),
    "http_fingerprint": AttackTechnique("T1592.002", "Gather Victim Host Information: Software", "Reconnaissance"),
    "http_probe": AttackTechnique("T1595.002", "Active Scanning: Vulnerability Scanning", "Reconnaissance"),
    "dir_enum": AttackTechnique("T1083", "File and Directory Discovery", "Discovery"),
    "vuln_scan": AttackTechnique("T1595.002", "Active Scanning: Vulnerability Scanning", "Reconnaissance"),
    "sql_injection": AttackTechnique("T1190", "Exploit Public-Facing Application", "Initial Access"),
    "ad_enum": AttackTechnique("T1087.002", "Account Discovery: Domain Account", "Discovery"),
    "smb_enum": AttackTechnique("T1135", "Network Share Discovery", "Discovery"),
    "password_attack": AttackTechnique("T1110", "Brute Force", "Credential Access"),
    "password_cracking": AttackTechnique("T1110.002", "Brute Force: Password Cracking", "Credential Access"),
    "exploit_search": AttackTechnique("T1588.005", "Obtain Capabilities: Exploits", "Resource Development"),
}


def attack_for_capability(capability: str) -> Optional[AttackTechnique]:
    return CAPABILITY_ATTACK.get(capability)

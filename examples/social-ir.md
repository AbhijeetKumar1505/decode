# Social Account Incident Response & Attribution

The `social-ir` module provides SOC-level incident response capabilities for
social media account compromises. It focuses on **attack attribution** rather
than directly identifying attackers (which platform privacy policies prevent).

## Quick Scan

```bash
decode social-ir scan \
  --email user@example.com \
  --domain phishing-site.com \
  --platform instagram
```

## Per-Platform Investigation

```bash
decode social-ir investigate instagram --email victim@example.com
decode social-ir investigate linkedin --email victim@example.com
decode social-ir investigate x --email victim@example.com
```

## Recovery Playbooks

```bash
decode social-ir recovery instagram
decode social-ir recovery discord
decode social-ir recovery github
```

## Use Cases

| Scenario | Command |
|----------|---------|
| Account compromised | `social-ir investigate instagram --email user@dom.com` |
| Phishing domain analysis | `social-ir scan --domain suspicious-login.com` |
| Breach impact assessment | `social-ir scan --email user@dom.com` |
| Incident response guidance | `social-ir recovery linkedin` |
| Full assessment | `social-ir scan --email user@dom.com --domain phish.com --platform x` |

## Programmatic Usage (Python)

```python
from decode.skills.social_ir import SocialIRSkill

skill = SocialIRSkill()

# Breach check
result = await skill.execute(action="breach_check", email="user@example.com")

# Phishing domain analysis
result = await skill.execute(action="analyze_phishing", domain="suspicious-login.com")

# Malware scan
result = await skill.execute(action="scan_malware")

# Session audit
events = [
    {"timestamp": "2026-06-20T18:30:00", "location": "Kolkata", "ip": "103.x.x.x"},
    {"timestamp": "2026-06-20T18:40:00", "location": "Moscow", "ip": "5.x.x.x"},
]
result = await skill.execute(action="audit_sessions", events=events)

# Full compromise assessment
result = await skill.execute(action="assess_compromise", email="user@example.com")

# IOC generation
from decode.modules.social_ir.models import IOCCollection
from decode.modules.social_ir.ioc_generator import IOCGenerator

iocs = IOCCollection(
    domains=["phishing-site.com"],
    ips=["5.5.5.5"],
    emails=["attacker@evil.com"],
)
gen = IOCGenerator(iocs)
print(gen.to_json())  # JSON format
print(gen.to_csv())  # CSV format
print(gen.to_stix())  # STIX 2.1 bundle

# Attribution
from decode.modules.social_ir.attribution_engine import AttributionEngine

engine = AttributionEngine()
result = engine.build_attribution(
    breach_result=breach_data,
    phishing_result=phish_data,
    malware_result=malware_data,
)
print(result.summary)

# Recovery playbook
result = await skill.execute(action="recovery_playbook", platform="instagram")
print(result["result"]["report"])
```

## What It Can Determine

- Account was compromised via **credential stuffing from breached credentials**
- Account was compromised through a **phishing domain** hosted on ASN XXXX
- Account was compromised by a **Lumma Stealer infection**
- Session was **hijacked from Chrome cookie theft**
- **Impossible travel** event detected between locations
- **Critical OAuth risk** from malicious third-party applications

## What It Cannot Determine

- Exact identity of the attacker
- Attacker's physical location/IP (platforms do not expose this)
- Real name of the attacker

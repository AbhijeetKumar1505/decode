# Nmap Workflow Example

## Overview

This example demonstrates a complete Nmap scanning workflow using Decode, from initial reconnaissance to service fingerprinting to finding generation.

## Prerequisites

- Decode installed and configured
- `nmap` installed on the system
- Target system you have permission to scan

## Session Setup

```bash
$ decode

> /start
Assessment goal: Network reconnaissance of internal lab
Target (hostname/IP): 10.0.0.0/24
Session started: a1b2c3d4...
```

## Step 1: Network Scan

```bash
> nmap_pro target=10.0.0.0/24 flags=-sn
```

**Decision summary:** Running ping sweep to identify live hosts in the target range.

**Proposed Action:** `nmap_pro`
**Risk Level:** WRITE
**Approve execution?** [y/n]: y

**Result:**
```json
{
  "targets": [
    {"ip": "10.0.0.1", "hostname": "gateway.local", "status": "up"},
    {"ip": "10.0.0.5", "hostname": "web.local", "status": "up"},
    {"ip": "10.0.0.10", "hostname": "db.local", "status": "up"}
  ]
}
```

## Step 2: Service Scan

```bash
> nmap_pro target=10.0.0.5 flags=-sV -sC
```

**Decision summary:** Found live host 10.0.0.5 (web.local). Performing service version detection and default script scan.

**Result:**
```json
{
  "targets": [{"ip": "10.0.0.5", "hostname": "web.local", "status": "up"}],
  "ports": [
    {"port": 22, "protocol": "tcp", "service": "ssh", "product": "OpenSSH", "version": "8.9p1"},
    {"port": 80, "protocol": "tcp", "service": "http", "product": "nginx", "version": "1.24.0"},
    {"port": 443, "protocol": "tcp", "service": "https", "product": "nginx", "version": "1.24.0"}
  ],
  "os_matches": [
    {"name": "Linux 5.15.0", "accuracy": "92"}
  ]
}
```

**Findings auto-generated:**
- [MEDIUM] Open port 22/tcp - ssh (OpenSSH 8.9p1)
- [MEDIUM] Open port 80/tcp - http (nginx 1.24.0)
- [MEDIUM] Open port 443/tcp - https (nginx 1.24.0)
- [MEDIUM] OS Detection: Linux 5.15.0 (92% accuracy)

## Step 3: Full Port Scan

```bash
> nmap_pro target=10.0.0.5 ports=1-65535 flags=-sV --reason
```

**Decision summary:** Initial scan only checked common ports. Now scanning all 65535 ports for complete coverage.

**Result:**
```json
{
  "ports": [
    {"port": 22, "protocol": "tcp", "state": "open"},
    {"port": 80, "protocol": "tcp", "state": "open"},
    {"port": 443, "protocol": "tcp", "state": "open"},
    {"port": 8080, "protocol": "tcp", "state": "open", "service": "http", "product": "Apache Tomcat"}
  ]
}
```

**Finding:** Additional service discovered on port 8080 (Apache Tomcat).

## Step 4: Governed Default NSE Scan

```bash
> nmap_pro target=10.0.0.5 flags=-sV -sC --reason
```

**Decision summary:** Running Nmap's governed default-script profile. Arbitrary raw `--script` flags are rejected; additional script profiles must be added as typed adapter options with explicit risk metadata.

**Result (NSE scripts):**
```json
{
  "nse_scripts": [
    {"id": "http-title", "port": "80", "output": "Title: Internal Dashboard"},
    {"id": "http-title", "port": "443", "output": "Title: Internal Dashboard"},
    {"id": "ssl-enum-ciphers", "port": "443", "output": "TLS 1.2 supported, TLS 1.3 supported"}
  ]
}
```

## Session Context

```bash
> /session
```

```
Target: 10.0.0.5 (web.local)
┌──────┬──────────┬──────────┬────────┐
│ Port │ Service  │ Product  │ Version│
├──────┼──────────┼──────────┼────────┤
│ 22   │ ssh      │ OpenSSH  │ 8.9p1  │
│ 80   │ http     │ nginx    │ 1.24.0 │
│ 443  │ https    │ nginx    │ 1.24.0 │
│ 8080 │ http     │ Tomcat   │        │
└──────┴──────────┴──────────┴────────┘
Findings:
[MEDIUM] Open port 22/tcp - ssh
[MEDIUM] Open port 80/tcp - http
[MEDIUM] Open port 443/tcp - https
[MEDIUM] OS Detection: Linux 5.15.0
```

## Next Steps

From here you could:
- Run `web_tech_detect` on ports 80/443 to identify web frameworks
- Run `dir_bruteforce` on the web servers to find hidden paths
- Run `cve_lookup` to check for vulnerabilities in nginx 1.24.0, OpenSSH 8.9p1
- Run `report_generator` to create a structured report of findings

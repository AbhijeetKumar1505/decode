# Report Generation Example

## Overview

This example demonstrates generating structured security reports from collected findings and evidence.

## Prerequisites

- Session with findings and evidence collected
- Report generator skill available

## Basic Report

```bash
> report_generator target=example.com format=markdown
```

**Result:**
```markdown
# Security Assessment Report: example.com
**Generated:** 2026-05-27T12:00:00+00:00
**Overall Risk:** MEDIUM

## Executive Summary
- Total findings: 6
- Critical: 0
- High: 1
- Medium: 4
- Low: 1

## Findings

### 1. Open port 22/tcp - ssh
- **Severity:** MEDIUM
- **Description:** Port 22 (ssh) is open on 10.0.0.5. Product: OpenSSH 8.9p1

### 2. Open port 80/tcp - http
- **Severity:** MEDIUM
- **Description:** Port 80 (http) is open on 10.0.0.5. Product: nginx 1.24.0

### 3. Open port 443/tcp - https
- **Severity:** MEDIUM
- **Description:** Port 443 (https) is open on 10.0.0.5. Product: nginx 1.24.0

### 4. Open port 8080/tcp - http-proxy
- **Severity:** MEDIUM
- **Description:** Port 8080 (http-proxy) is open on 10.0.0.5. Product: Apache Tomcat

### 5. CVE-2025-1234 affects nginx 1.24.0
- **Severity:** HIGH
- **Description:** nginx 1.24.0 has a known vulnerability: HTTP/2 memory disclosure
- **Recommendation:** Upgrade to nginx 1.25.0 or later

### 6. OS Detection: Linux 5.15.0
- **Severity:** LOW
- **Description:** Operating system detected with 92% accuracy
```

## JSON Format

```bash
> report_generator target=example.com format=json
```

**Result:**
```json
{
  "report_metadata": {
    "title": "Security Assessment: example.com",
    "generated": "2026-05-27T12:00:00",
    "risk_score": "medium"
  },
  "findings": [
    {
      "title": "Open port 22/tcp - ssh",
      "severity": "medium",
      "description": "Port 22 (ssh) is open on 10.0.0.5",
      "recommendation": ""
    }
  ],
  "summary": {
    "total": 6,
    "risk_score": "medium",
    "severity_breakdown": {
      "critical": 0, "high": 1, "medium": 4, "low": 1
    }
  }
}
```

## Report with Attack Chain

Use the attack chain to automatically generate a report after completing the assessment:

```bash
> start
Assessment goal: Full assessment of production web server
Target (hostname/IP): web.prod.internal

> chain
# ... runs all phases ...

# After final phase:
[GREEN] All phases complete!

> session
# Shows complete target context with all findings

> report_generator target=web.prod.internal format=markdown
# Generates comprehensive report
```

# Web Application Scan Example

## Overview

This example demonstrates a comprehensive web application security assessment using Decode's web-focused skills.

## Prerequisites

- Nmap scan completed (see nmap-workflow.md)
- Web technology detection and directory brute-force skills

## Step 1: Technology Detection

```bash
> web_tech_detect url=https://example.com
```

**Result:**
```json
{
  "technologies": [
    {"name": "HTTPServer", "version": "nginx/1.24.0"},
    {"name": "JQuery", "version": "3.7.1"},
    {"name": "React", "version": ""},
    {"name": "Cloudflare", "version": ""}
  ]
}
```

## Step 2: Directory Brute-Force

```bash
> dir_bruteforce url=https://example.com/ threads=50
```

**Result:**
```json
{
  "found": [
    {"path": "/login", "status": 200, "size": 4521},
    {"path": "/api", "status": 200, "size": 89},
    {"path": "/admin", "status": 403, "size": 23},
    {"path": "/.env", "status": 404, "size": 9},
    {"path": "/dashboard", "status": 302, "size": 0}
  ],
  "total_scanned": 25
}
```

## Step 3: CVE Lookup

```bash
> cve_lookup keyword=nginx/1.24
```

**Result:**
```json
{
  "cve_data": [
    {
      "id": "CVE-2025-1234",
      "description": "nginx 1.24.0 HTTP/2 memory disclosure vulnerability",
      "cvss_score": 7.5,
      "severity": "HIGH"
    }
  ]
}
```

## Step 4: Web Vulnerability Scan

```bash
> web_vuln_scan url=https://example.com/login
```

**Result:**
```json
{
  "results": [
    {"type": "sqli", "payload": "' OR 1=1--", "status_code": 200, "length": 4521},
    {"type": "xss", "payload": "<script>alert(1)</script>", "status_code": 200, "length": 4521},
    {"type": "lfi", "payload": "../etc/passwd", "status_code": 404, "length": 9}
  ]
}
```

## Step 5: Generate Report

```bash
> report_generator target=example.com format=markdown
```

# Bootstrap Engine

`BootstrapEngine` in `decode/bootstrap/engine.py` inspects the host environment, reports prerequisite state, invokes tool discovery, and writes `data/bootstrap_report.json`.

## Default workflow

```text
Detect OS and runtime
  -> inspect prerequisite commands
  -> discover configured tool providers
  -> report available and degraded capabilities
  -> write bootstrap report and tool registry
```

Bootstrap must not treat a detected tool as authorized execution and must not count unsupported versions as capability coverage.

## CLI

```bash
decode bootstrap
decode bootstrap --update
```

The default command is diagnostic. `--update` may invoke a platform package-manager update and therefore mutates the host; use it only with an explicit user request and appropriate operating-system privileges. Missing individual tools are reported, not installed automatically.

Generated reports can include host paths and environment details. Treat them as deployment data rather than source documentation.

Runtime tool discovery is handled by the governed `list_tools` capability (a `$PATH` scan); see [System Architecture](SYSTEM_ARCHITECTURE.md).

# Bootstrap and Environment Discovery

**Status:** Current diagnostic bootstrap; provider-aware discovery is Target

Bootstrap reports prerequisites, configured providers, PATH tools, versions,
privileges, resources, and degraded capabilities. Detection is not authorization.

```text
load provider config -> identify environment -> health
 -> discover inside provider -> validate adapter compatibility
 -> publish provider-scoped report
```

Distinguish installed, executable, supported, authorized, healthy. Reports may be
sensitive and belong in local state.

Current commands: `decode bootstrap` and mutating
`decode bootstrap --update`, which requires explicit intent/policy. Missing
tools are reported, not silently installed.

Runtime `list_tools` must use the same provider-aware discovery rather than an
unrelated process PATH.

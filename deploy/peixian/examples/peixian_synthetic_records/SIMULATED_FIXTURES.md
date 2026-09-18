# `DEMO-SNAPSHOT-20260918-01` simulated fixture batch

This overlay is a fixed, read-only, entirely fictional data batch for the
private `peixian-synthetic-records` service.  It does not query, cache, proxy,
or derive from any real business system.  Every stable identifier is synthetic
and starts with `DEMO-`.

| Module | Fixed record count | Example contents |
| --- | ---: | --- |
| `funds` | 8 | synthetic account transfers and transaction references |
| `calls` | 8 | synthetic call references, durations, and cell references |
| `portrait` | 6 | synthetic co-presence events, no biometric data |
| `composite` | 6 | declared cross-record relations, not a risk score |
| `night` | 8 | synthetic late-night events and time windows |
| `vehicle` | 6 | synthetic gate/lane passages; no real plate data |
| `lookup` | 8 | explicit cross-record lookup references |

The public response envelope is kept compatible with the initial `1.0.0`
plugin contract.  It reports `synthetic: true`, `data_status: complete`,
`rule_version: demo-v1.1`, and `rule_status: demo_only` for this snapshot.

## Deployment boundary

`records_service_simulated.py` imports the existing validated HTTP service and
replaces only its fixed fixture and response builder.  The systemd drop-in
changes the process entry point without changing the original service unit.
Removing the drop-in and restarting the service returns it to the original
fixture implementation.

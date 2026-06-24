# Runtime Topology Map

The runtime topology map replaces the old idea that red/yellow/green job cards are a heat map. Job cards still exist as a runtime summary, but topology answers where a slow job is executing and what runtime signal is active.

## What The Map Shows

The map connects:

1. Customer / workstream / job run
2. ESS request, process ID, job ID, or API invocation
3. App, WLS, or ESS server when known or inferred
4. Oracle DB RAC instance and DB host
5. Active DB session
6. SQL_ID, plan hash, wait class, and wait event

The seeded APJ Direct CalculatePVT run demonstrates this path:

`APJ Direct CalculatePVT -> ESS-APJ-90045 -> ESS_SOAServer_as24_01 -> DBRAC_inst1 / dbhost-a -> SQL_ID dp9u1803k8k7f`

The DB instance and DB host are confirmed by DB session metadata. The app server is inferred from session `MACHINE` / `PROGRAM` until WLS or OCI telemetry confirms it.

## Confidence Labels

- `confirmed`: direct evidence from read-only session or instance metadata.
- `likely`: strong metadata but missing one corroborating source.
- `inferred`: derived from session machine, program, module, action, client identifier, or ECID.
- `unknown`: no trustworthy placement evidence yet.

## API

- `GET /api/topology/current`
- `GET /api/runs/{id}/topology`
- `POST /api/runs/{id}/correlate-topology`
- `GET /api/nodes`
- `GET /api/nodes/{id}`
- `GET /api/nodes/{id}/metrics`

## Local Data

Local mode seeds:

- `ESS_SOAServer_as12_01`
- `ESS_SOAServer_as24_01`
- `ESS_SOAServer_as27_01`
- `MWServer_as1_01`
- `MWServer_as11_01`
- `DBRAC_inst1` through `DBRAC_inst4`

No real IP addresses are stored or displayed. IP fields should remain hashed/redacted unless an explicit production policy allows display.

## Production Extension

Production topology should be built from read-only connector templates and telemetry:

- Oracle DB: `GV$SESSION`, `GV$INSTANCE`, `GV$SQL`, optional ASH/AWR-style views.
- ESS/API: request/process/job status and request identifiers.
- WLS/OCI/Grafana/Prometheus: middleware host, GC, RJVM, CPU/load, and service metrics.

The app remains non-destructive. It may inspect and correlate; it must not control jobs, alter DB objects, execute PL/SQL, or remediate customer pods.

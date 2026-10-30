# CONTRIBUTING.md

Research prototype for a confidence-aware network digital twin (IOE Thapathali Campus case study).
Pipeline: 01 evidence ingest → **02 twin builder** → **03 intent library** → 04 partial observability → 05 confidence → 06 probes → 07 fault localizer → 08 report. Only 02 and 03 are implemented. Do not scaffold the missing components or add their dependencies unasked.

- `docs/proposal.md` — research questions, fault classes, metrics, ethics (§11).
- `docs/slides.md` — architecture and pipeline diagrams.

## Commands

- Tests (from repo root): `.venv/bin/pytest -q`
- Single test: `.venv/bin/pytest tests/test_twin_builder.py::test_name -q`
- There is no lint, format, typecheck, or CI config. Don't invent one.
- `.venv/` is the working environment (Python 3.12). Dependencies are declared in `pyproject.toml` (`Jinja2`, `PyYAML`, `pydantic>=2`; dev extra `pytest`; optional `verify` extra `pybatfish`). `pybatfish` is imported lazily inside `verifier.py` only; nothing else may import it at module level.
- CLI (`src/twin_builder/cli.py`, script `twin-builder`): `compile <json> [-o OUT] [--visualize]`, `verify <snapshot_dir> [--src-ip --dst-ip [--node | --evidence JSON]] [--host --port --network]`, `graph <clab_yaml>` (runs `sudo containerlab graph -t ...` via an argument list, never `shell=True`), `check-intents <snapshot_dir> <intents_json> [--evidence JSON] [--groups JSON] [--json-out FILE]`, `add-intent --intents JSON (--evidence JSON | --groups JSON)`. A bare `twin-builder <json>` is kept as an alias for `compile`.

## Architecture

- `src/twin_builder/schema.py` uses stdlib `dataclasses` (not Pydantic) with validation in `__post_init__`; IPv4 only. Graph: `NetworkEvidence` → `Node` (`router`/`switch`/`host`) → `Interface` / `StaticRoute` / `ACL` / `OSPFConfig`; `Link` joins `node:interface`. Validation rejects duplicate names, links to unknown or already-used interfaces, OSPF on non-routers, and interfaces referencing undefined ACLs.
- `src/twin_builder/builder.py` is the only engine; the public API is re-exported from `src/twin_builder/__init__.py`.
- Templates in `templates/*.j2` render with Jinja2 `StrictUndefined`: every key a template uses must be produced by the matching `_batfish_node_context` / `_frr_node_context` / `_containerlab_context` helper. Template and context edits go together.
- Outputs are created under the `output_dir` argument (never hardcoded):
  - `build_batfish_snapshot()` → `<out>/batfish_snapshot/configs/<node>.cfg`, returns the snapshot dir.
  - `build_containerlab()` → `<out>/containerlab/<evidence.name>.clab.yml` plus `<out>/containerlab/clab-configs/<node>/{frr.conf,daemons}`, returns the topology path.
- CIDR → dotted netmask/wildcard conversion happens in the context helpers; templates never receive `/24`. Keep conversion out of templates.
- `prune_evidence()` returns a new validated `NetworkEvidence` with links/static routes removed (counterfactual hook for Component 07); it must not mutate the input.
- `src/twin_builder/verifier.py` (`TwinVerifier`) talks only to a local Batfish service (default `localhost:9996`) about generated snapshots. Sessions open lazily; connection failures (`OSError`, which includes `requests.ConnectionError`) become `BatfishUnavailableError`, other query failures `VerificationError`. `test_trace` maps `DENIED_IN/OUT` → `DENIED`, `ACCEPTED/DELIVERED_TO_SUBNET/EXITS_NETWORK` → `ACCEPTED`, and passes other Batfish dispositions through. With `start_node=None`, `resolve_start_location()` picks the location from the evidence attached via `load_snapshot(..., evidence=...)`: host with that exact IP → router's own IP → longest-prefix router subnet as `@enter(Node[Iface])`. `compile` writes `<out>/evidence.json` so `verify` can find it.
- `.gitignore` excludes generated `out/`, `batfish_snapshot/`, `containerlab/`, `*.clab.yml`; write artifacts to those locations or `tmp_path`, not into `src/`.

## Intent Library (Component 03)

- `src/intent_library/` uses **Pydantic v2** models (`extra="forbid"`), unlike Component 02's dataclasses. `Intent` enforces `expected` per type (isolation → `DENIED`, reachability/service_access → `ACCEPTED`, loop_free → `LOOP_FREE`).
- It imports Component 02 only via `intent_library/_twin.py`, which picks relative (`src.` layout, tests) or absolute (installed) imports from `__package__`; `twin_builder/cli.py` mirrors this. Keep that so both layouts share one copy of each class.
- `auto_discover_groups(evidence)`: host → `<host_slug>` (`/32`s); interface description → `<description_slug>`; `vlan_id` → `vlan_<id>`; otherwise non-host interface → `net_<cidr_slug>`. Groups with the same name merge. Curated groups may declare `aliases`; `EndpointGroupRegistry.get_group` matches names first, then aliases, and the validator rejects any name/alias collision. `examples/thapathali_intents.json` uses auto-discovered names, which `examples/thapathali_groups.json` lists as aliases.
- `IntentResolver.resolve_intent` makes the src × dst Cartesian product; each source's start location is `TwinVerifier.resolve_start_location(<network address>)`, so subnets enter as `@enter(Router[Iface])` and `/32` hosts start at the host. Destination `any` becomes `0.0.0.0/0`; source `any` is rejected.
- `IntentEvaluator` calls `TwinVerifier.test_trace(..., protocol=, dst_port=)` / `detect_loops()`. Status precedence per intent: any mismatch → FAILED, else any error → ERROR, else PASSED. Isolation is deliberately strict: only `DENIED` (filter drop) passes; blackholes such as `NO_ROUTE` fail with a "blocked, but not by an ACL/filter" hint. `verification_coverage` (V_q) = passed / total.
- `add-intent` wizard logic lives in `intent_library/wizard.py` (injectable input/output); saves are atomic (`loader._save`).

## Containerlab / FRR mapping quirks

- `router` → `frrouting/frr:v8.5.2`, clab kind `linux`, binds both `frr.conf` and `daemons`.
- `switch` → clab `kind: bridge`, no image, no exec commands.
- `host` → `alpine:latest`, clab kind `linux`, with `exec:` `ip` commands for addressing/routes.
- Container interface names: linked interfaces become `eth1..N` in link iteration order, `Loopback*` → `lo`, remaining interfaces become dummy `ethN`. FRR configs are emitted for routers only.
- Batfish config: Cisco IOS syntax with netmask, wildcard masks, and `router ospf 1`. FRR config: CIDR with `network <prefix> area <id>`. ACLs render only in the Batfish snapshot.

## Testing quirks

- Tests assert exact rendered CLI strings (e.g. `ip address 10.0.12.1 255.255.255.0`, `permit tcp 10.0.1.0 0.0.0.255 ... eq 443`) and parsed YAML, so template edits usually require test updates.
- The suite needs only `pytest`, `PyYAML`, `pydantic`, and `tmp_path`; no running Batfish, Containerlab, or Docker. Keep it that way. `tests/test_verifier.py` injects fake pybatfish sessions via `TwinVerifier(session_factory=..., header_factory=...)` and mocks `subprocess.run` for `graph`; one test uses real pybatfish against closed port 1 and is skipped when pybatfish is absent. `tests/test_intent_library.py` uses a `PolicySession` fake that emulates the `SECURITY_POLICY_CORE` ACL of `examples/thapathali_complex.json`, and scripts the wizard by patching `builtins.input`.
- Add a test in `tests/test_twin_builder.py` for every schema, builder, or template change.

## Safety boundaries (proposal §11 — non-negotiable)

- Never target live campus devices: no SSH, config push, or command execution against production. Faults run only inside Containerlab or Batfish.
- No credentials, passwords, or SNMP community strings in code, tests, or templates.
- Use synthetic names (`R1`, `SW-CORE-01`) and private/example ranges (`10.0.0.0/8`, `192.168.0.0/16`, `192.0.2.0/24` in tests).

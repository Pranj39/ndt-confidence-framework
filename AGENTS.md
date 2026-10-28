# AGENTS.md

Research prototype for a confidence-aware network digital twin (IOE Thapathali Campus case study).
Pipeline: 01 evidence ingest → **02 twin builder (only implemented component)** → 03 intents → 04 partial observability → 05 confidence → 06 probes → 07 fault localizer → 08 report. Do not scaffold the missing components or add their dependencies unasked.

- `docs/proposal.md` — research questions, fault classes, metrics, ethics (§11).
- `docs/slides.md` — architecture and pipeline diagrams.

## Commands

- Tests (from repo root): `.venv/bin/pytest -q`
- Single test: `.venv/bin/pytest tests/test_twin_builder.py::test_name -q`
- There is no lint, format, typecheck, or CI config. Don't invent one.
- `.venv/` is the working environment (Python 3.12). Dependencies are declared in `pyproject.toml` (`Jinja2`, `PyYAML`; dev extra `pytest`). `pybatfish` happens to be installed but is **not** a declared dependency — Component 02 only renders files and never talks to Batfish.

## Architecture

- `src/twin_builder/schema.py` uses stdlib `dataclasses` (not Pydantic) with validation in `__post_init__`; IPv4 only. Graph: `NetworkEvidence` → `Node` (`router`/`switch`/`host`) → `Interface` / `StaticRoute` / `ACL` / `OSPFConfig`; `Link` joins `node:interface`. Validation rejects duplicate names, links to unknown or already-used interfaces, OSPF on non-routers, and interfaces referencing undefined ACLs.
- `src/twin_builder/builder.py` is the only engine; the public API is re-exported from `src/twin_builder/__init__.py`.
- Templates in `templates/*.j2` render with Jinja2 `StrictUndefined`: every key a template uses must be produced by the matching `_batfish_node_context` / `_frr_node_context` / `_containerlab_context` helper. Template and context edits go together.
- Outputs are created under the `output_dir` argument (never hardcoded):
  - `build_batfish_snapshot()` → `<out>/batfish_snapshot/configs/<node>.cfg`, returns the snapshot dir.
  - `build_containerlab()` → `<out>/containerlab/<evidence.name>.clab.yml` plus `<out>/containerlab/clab-configs/<node>/{frr.conf,daemons}`, returns the topology path.
- CIDR → dotted netmask/wildcard conversion happens in the context helpers; templates never receive `/24`. Keep conversion out of templates.
- `prune_evidence()` returns a new validated `NetworkEvidence` with links/static routes removed (counterfactual hook for Component 07); it must not mutate the input.
- `.gitignore` excludes generated `out/`, `batfish_snapshot/`, `containerlab/`, `*.clab.yml`; write artifacts to those locations or `tmp_path`, not into `src/`.

## Containerlab / FRR mapping quirks

- `router` → `frrouting/frr:v8.5.2`, clab kind `linux`, binds both `frr.conf` and `daemons`.
- `switch` → clab `kind: bridge`, no image, no exec commands.
- `host` → `alpine:latest`, clab kind `linux`, with `exec:` `ip` commands for addressing/routes.
- Container interface names: linked interfaces become `eth1..N` in link iteration order, `Loopback*` → `lo`, remaining interfaces become dummy `ethN`. FRR configs are emitted for routers only.
- Batfish config: Cisco IOS syntax with netmask, wildcard masks, and `router ospf 1`. FRR config: CIDR with `network <prefix> area <id>`. ACLs render only in the Batfish snapshot.

## Testing quirks

- Tests assert exact rendered CLI strings (e.g. `ip address 10.0.12.1 255.255.255.0`, `permit tcp 10.0.1.0 0.0.0.255 ... eq 443`) and parsed YAML, so template edits usually require test updates.
- The suite needs only `pytest`, `PyYAML`, and `tmp_path`; no Batfish, Containerlab, or Docker. Keep it that way.
- Add a test in `tests/test_twin_builder.py` for every schema, builder, or template change.

## Safety boundaries (proposal §11 — non-negotiable)

- Never target live campus devices: no SSH, config push, or command execution against production. Faults run only inside Containerlab or Batfish.
- No credentials, passwords, or SNMP community strings in code, tests, or templates.
- Use synthetic names (`R1`, `SW-CORE-01`) and private/example ranges (`10.0.0.0/8`, `192.168.0.0/16`, `192.0.2.0/24` in tests).

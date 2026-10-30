# Confidence-Aware Network Digital Twin (NDT)

> **Safe Change Validation and Fault Localization Under Partial Observability: A Thapathali Campus Case Study**  
> *Faculty Research Grant 2083/84 (Class B Dry-Lab)*  
> Tribhuvan University, Institute of Engineering (IOE), Thapathali Campus

- **Principal Investigator:** Er. Kobid Karkee  
- **Student Co-Investigators:** Plan Ghimire, Pranjal Shrestha
- **Documentation:** [docs/proposal.md](docs/proposal.md) | [docs/slides.md](docs/slides.md) | [examples/README.md](examples/README.md)

---

## Overview

Modern campus networks experience continuous configuration mutations and partial observability due to unmonitored links, legacy devices, or delayed telemetry. This research framework develops a **confidence-calibrated network digital twin** capable of:
1. Translating normalized network state into twin environments (Batfish static verification and Containerlab emulation).
2. Quantifying twin prediction uncertainty under incomplete network evidence.
3. Formulating active probe selection and counterfactual fault localization.

---

## Framework Architecture

The framework is organized into 8 modular components:

```
01 Evidence Ingestor ──► 02 Twin Builder ──► 03 Intent Library
                              │
     ┌────────────────────────┴────────────────────────┐
     ▼                                                 ▼
04 Partial-Observability Generator             05 Confidence Engine
     │                                                 │
     ▼                                                 ▼
06 Probe Selector                              07 Fault Localizer
     └────────────────────────┬────────────────────────┘
                              ▼
                      08 Operator Report
```

- **01 Evidence Ingestor:** Parses heterogeneous configs and telemetry into a unified Network Evidence graph.
- **02 Twin Builder (`src/twin_builder/` - implemented):** Compiles evidence into Batfish snapshots, Containerlab topologies (FRRouting + Linux containers), and interactive visualizations.
- **03 Intent Library (`src/intent_library/` - implemented):** Declarative reachability, isolation, service-access, and loop-freedom intents over endpoint groups, verified against the twin with Batfish.
- **04 Partial-Observability Generator:** Controlled injection of topological missingness and telemetry staleness.
- **05 Confidence Engine:** Calibrates confidence scores for twin query answers under missing evidence.
- **06 Probe Selector:** Information-theoretic selection of active probes under budget constraints.
- **07 Fault Localizer:** Counterfactual graph mutations to pinpoint root causes for invariant violations.
- **08 Operator Report:** Emits actionable verdicts (`SAFE`, `UNSAFE`, `UNCERTAIN`) with explanations.

---

## Installation & Setup

### Prerequisites
- Python 3.10+
- Optional: [Docker](https://docs.docker.com/get-docker/) (for running Batfish)
- Optional: [Containerlab](https://containerlab.dev/install/) (for emulation on Linux)

### Environment Setup

Clone the repository and install dependencies:

```bash
# Clone the repository
git clone https://github.com/your-org/ndt-confidence-framework.git
cd ndt-confidence-framework

# Create and activate a virtual environment
python -m venv .venv
source .venv/bin/activate  # On Windows: .venv\Scripts\activate

# Install core dependencies and CLI in editable mode
pip install -e .

# Optional: Install test suite runner
pip install -e .[dev]

# Optional: Install Batfish verification bindings
pip install -e .[verify]
```

---

## Component 02: Twin Builder CLI

The `twin-builder` tool provides end-to-end compilation, verification, and topology visualization.

### 1. Compile Network Evidence

Compile a canonical JSON evidence file into Batfish configs, Containerlab FRR configurations, and an interactive Vis.js HTML map:

```bash
twin-builder compile examples/thapathali_lab.json -o dist --visualize
```

Generated artifacts under `dist/`:
- `batfish_snapshot/configs/<node>.cfg`: Vendor-neutral Cisco IOS configs for Batfish.
- `containerlab/<topology>.clab.yml`: Containerlab topology specification.
- `containerlab/clab-configs/<node>/frr.conf`: FRRouting configurations with OSPF and interface addressing.
- `topology.html`: Standalone interactive visualization (open in any web browser).
- `evidence.json`: Preserved evidence snapshot for downstream validation.

### 2. Verify with Batfish

Analyze configurations offline using Batfish to compute the routing information base (RIB) and perform hop-by-hop packet traceroutes:

1. Start a local Batfish service:
   ```bash
   docker run -d -p 9996:9996 batfish/allinone
   ```

2. Run verification with automated source location resolution:
   ```bash
   twin-builder verify dist/batfish_snapshot \
     --src-ip 10.0.10.100 \
     --dst-ip 10.0.20.10
   ```

   The verifier automatically determines the entry node or interface (e.g. `Student-Lab-PC` or `@enter(...)`) based on the evidence, evaluates routing and ACL policies, and reports hop-by-hop forwarding steps or ACL drops.

### 3. Launch Containerlab Web Graph

On a Linux host with Containerlab installed:

```bash
twin-builder graph dist/containerlab/thapathali-lab.clab.yml
```

Opens Containerlab's interactive browser UI displaying the active emulation topology.

---

## Component 03: Intent Library

Intents are declarative L2/L3 properties over **endpoint groups** (proposal §5, §8.2, §8.5). Each
intent has a type, an expected outcome, and a severity:

| Type | Expected | Example |
|---|---|---|
| `isolation` | `DENIED` | Students must not reach the exam database |
| `reachability` | `ACCEPTED` | Faculty must reach the exam database |
| `service_access` | `ACCEPTED` | Students reach the EMIS portal over `web` (tcp/443) |
| `loop_free` | `LOOP_FREE` | The data plane has no forwarding loops |

Sources and destinations are `group:<name>` references, raw IPv4 addresses/CIDRs, or `any`
(destination only). Services map to ports: `web`/`https` → tcp/443, `http` → tcp/80,
`ssh` → tcp/22, `dns` → udp/53.

**Endpoint groups** come from a curated file such as
[examples/thapathali_groups.json](examples/thapathali_groups.json) or are auto-discovered
from the evidence:
- each host becomes `<hostname>`;
- each interface description becomes `<description>`;
- each VLAN becomes `vlan_<id>`;
- any other router subnet becomes `net_<cidr>`.

A curated group can list `aliases`, such as `students` with alias `student_lab`. An intent
that references either name resolves to the same group. Aliases let one intent file work with
both a curated groups file and auto-discovered groups. Names and aliases must be unique across
the registry.

**Isolation is strict.** An isolation intent passes only if every flow is `DENIED` by an
ACL/filter. Traffic that is blackholed (`NO_ROUTE`, `NULL_ROUTED`, …) counts as FAILED, because
the next routing change could silently restore reachability.

### Check an intent suite

```bash
twin-builder compile examples/thapathali_complex.json -o dist
twin-builder check-intents dist/batfish_snapshot examples/thapathali_intents.json \
  --groups examples/thapathali_groups.json --json-out dist/intent_report.json
```

Each intent is expanded into the Cartesian product of its source and destination prefixes. Each
flow starts where its source attaches to the twin (a host, or `@enter(Router[Interface])` for a
subnet) and is traced in Batfish. `loop_free` intents use Batfish `detectLoops`. The report shows:
- PASSED/FAILED/ERROR for each intent;
- every expanded check with its path;
- the ACL that dropped traffic, if any;
- the **dependency cone** (nodes and interfaces each verdict relied on);
- **verification coverage** `V_q` = passed / total.

Omit `--groups` to use auto-discovered groups. The example suite uses auto-discovered names, and
the curated file lists them as aliases, so it passes either way. The command exits with 1 if any
intent is not PASSED.

### Author a new intent interactively

```bash
twin-builder add-intent --intents examples/thapathali_intents.json \
  --evidence dist/evidence.json --groups examples/thapathali_groups.json
```

The wizard lists the groups as `[1] students`, `[2] exam_db`, and so on. It then asks for:
- the intent ID and name;
- the type;
- the source and destination groups;
- the service or port;
- the severity.

It appends the validated intent to the suite and saves the file.

---

## Running Tests

Unit and integration tests run entirely offline without requiring live networking daemons:

```bash
pytest -q
```

---

## Strict Safety & Ethical Boundaries

In adherence to Section 11 of the research proposal:
1. **Zero Production Interaction:** No code in this repository connects to, queries, or pushes configuration to live production campus switches or routers.
2. **Safe Testbed Execution:** All network mutations, fault injections, and verification routines execute strictly inside isolated Docker containers (Containerlab) or analytical memory models (Batfish).
3. **No Embedded Credentials:** No passwords, SNMP community strings, or sensitive campus credentials are stored in code, templates, or test datasets. Synthetic and anonymized network configurations are used throughout.

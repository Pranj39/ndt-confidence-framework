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
- **02 Twin Builder (`src/twin_builder/` - Current Implementation):** Compiles evidence into Batfish snapshots, Containerlab topologies (FRRouting + Linux containers), and interactive visualizations.
- **03 Intent Library:** Declarative policy checks for reachability, isolation, and routing invariants.
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

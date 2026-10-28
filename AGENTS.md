# AGENTS.md — Instructions for AI Coding Assistants (OpenCode)

## 1. Project Overview & Context
- **Project Title:** Confidence-Aware Network Digital Twin for Safe Change Validation and Fault Localization Under Partial Observability: A Thapathali Campus Case Study
- **Grant:** Tribhuvan University, IOE Thapathali Campus — Faculty Research Grant 2083/84 (Class B Dry-Lab)
- **Principal Investigator:** Er. Kobid Karkee
- **Student Co-Investigators:** Plan Ghimire, Pranjal Shrestha, Chitra Raj Joshi
- **Primary References:**
  - `docs/proposal.md` — Full proposal text, research questions (RQ1–RQ4), fault classes, and metrics.
  - `docs/slides.md` — High-level architecture, pipeline flowchart, and baseline definitions.

---

## 2. Architecture & Component Boundaries
The project consists of 8 modular components. **Respect component separation:**
1. **01 Evidence Ingestor:** Normalizes raw configs and state into an Evidence Graph (JSON/IR).
2. **02 Twin Builder [CURRENT FOCUS]:** Transforms the Evidence Graph into Batfish snapshots and Containerlab topologies.
3. **03 Intent Library:** Defines declarative reachability, isolation, and routing policies.
4. **04 Partial-Observability Generator:** Injects missingness (100%, 90%, 75%, 50%, 25%) and staleness.
5. **05 Confidence Engine:** Calibrates confidence $C_q$ using logistic/isotonic regression.
6. **06 Probe Selector:** Recommends active probes based on information gain per cost.
7. **07 Fault Localizer:** Runs counterfactual repairs to rank candidate root causes.
8. **08 Operator Report:** Emits final verdicts (SAFE, UNSAFE, UNCERTAIN) and diagnostics.

---

## 3. Current Focus: Component 02 (Twin Builder)
The Twin Builder is the compiler between the abstract network model and runnable twins.
- **Input:** Canonical `NetworkEvidence` intermediate representation (Nodes, Interfaces, Links, Routes, OSPF).
- **Outputs Required:**
  1. **Batfish Snapshot:** Folder structure with `configs/<node>.cfg` formatted in Cisco IOS / Batfish-compatible syntax. Subnet masks must be converted from CIDR (e.g. `/24` → `255.255.255.0`).
  2. **Containerlab Topology:** `<name>.clab.yml` deploying FRRouting routers (`frrouting/frr:v8.5.2`) and Linux hosts (`alpine:latest`), binding `/etc/frr/frr.conf` and `/etc/frr/daemons`.
- **Location:** All code must live under `src/twin_builder/`.

---

## 4. Tech Stack & Dependencies
- **Language:** Python 3.10+
- **Configuration Templating:** Jinja2
- **Data Validation:** Pydantic (v2) or Python dataclasses with strict type hints
- **Testing:** `pytest` (mandatory for every module)
- **Networking Engines:** Batfish (`pybatfish`), Containerlab CLI, FRRouting (FRR)
- **Data Formats:** YAML, JSON

---

## 5. Strict Ethical & Safety Boundaries
As per Section 13 of `docs/proposal.md`:
1. **NO Live Production Interaction:** Never write code that attempts to SSH, push configurations, or execute commands on actual campus production switches/routers.
2. **Credential Safety:** Never hardcode credentials, passwords, or SNMP community strings in code, tests, or config templates.
3. **Data Anonymization:** Use synthetic or pseudonymized device names (e.g., `R1`, `SW-CORE-01`) and standard private IP ranges (`10.0.0.0/8`, `192.168.0.0/16`).
4. **Controlled Environment:** All fault injections, link toggles, and counterfactual mutations run strictly inside Containerlab containers or Batfish memory.

---

## 6. Coding & Git Conventions
- **Code Style:** PEP 8 compliant, explicit type annotations on all function signatures, clean docstrings.
- **Error Handling:** Fail gracefully with descriptive exceptions rather than silent `None` returns.
- **Testing Standard:** Every new feature must include a corresponding test under `tests/`. Tests must pass locally via `pytest` before completing a task.
- **Directory Layout:**
  ```text
  ndt-confidence-framework/
  ├── docs/                      # proposal.md, slides.md
  ├── src/
  │   └── twin_builder/          # Component 02 package
  │       ├── __init__.py
  │       ├── schema.py          # Data models
  │       ├── builder.py         # TwinBuilder engine
  │       └── templates/         # Jinja2 templates (.j2)
  ├── tests/                     # Unit and integration tests
  └── AGENTS.md                  # This file
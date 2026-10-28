# Slide Deck: Confidence-Aware Network Digital Twin for Safe Change Validation and Fault Localization Under Partial Observability
**Context:** Faculty Research Grant 2083/84 Presentation Defense  
**Affiliation:** Tribhuvan University | Institute of Engineering | Thapathali Campus  
**Authors:** Er. Kobid Karkee (PI), Plan Ghimire, Pranjal Shrestha  
**Date:** August 2026 (Bhadra 2083)  

---

### Slide 1: Title Slide
- **Title:** Confidence-Aware Network Digital Twin for Safe Change Validation and Fault Localization Under Partial Observability
- **Subtitle:** A Thapathali Campus Case Study
- **Grant:** Faculty Research Grant 2083/84
- **Team:** Er. Kobid Karkee • Plan Ghimire • Pranjal Shrestha
- **Institution:** Tribhuvan University | Institute of Engineering | Thapathali Campus

---

### Slide 2: Problem Overview
- Campus networks are critical for teaching, administration, laboratories, and research.
- Network changes are routine but risky: ACL updates, VLAN migrations, and route changes.
- Current verification tools return a binary pass/fail based strictly on the supplied model.
- **Key challenge:** Documentation is incomplete, devices come from multiple vendors, and measurements may be outdated.
- *Diagram:* Network Change -> Current Verification Tool -> PASS / FAIL.
- **Core Dilemma:** Is the model complete? Is the verdict trustworthy?

---

### Slide 3: Research Problem & Objectives
- **Core Research Question:** How can a campus network digital twin provide a calibrated and explainable confidence level along with its change-validation verdict?
- **General Objective:** Build and evaluate a confidence-aware campus network digital twin for safer pre-change verification and fault localization under incomplete or stale network information.
- **Specific Objectives:**
  1. Build a reproducible digital-twin model for an approved campus segment.
  2. Quantify the impact of missing/stale evidence on validation.
  3. Develop an interpretable and calibrated confidence model.
  4. Design a low-overhead probe-selection method.
  5. Develop a counterfactual fault-localization method.
  6. Compare performance with existing approaches.
  7. Implement and document a usable prototype.

---

### Slide 4: Literature Review: Strengths and Unresolved Issues
- **Formal Verification:** Strong reachability & policy checking | *Gap:* Verdict is strictly for the supplied model; trust under missing/stale evidence is uncalibrated.
- **Test Coverage:** Shows which configuration lines are exercised | *Gap:* Coverage is not the probability that the verdict is correct.
- **Configuration Synthesis:** Fills declared holes or mines specs | *Gap:* Targets synthesis, not operational uncertainty.
- **High-Fidelity NDT / Emulation:** Supports safe pre-deployment replay | *Gap:* Assumes full data; low-resource constraints underexplored.
- **Automated Multi-Tool Workflows (e.g. Aether):** Combines maps, verification, and AI | *Gap:* Assumes up-to-date digital maps; no task-level confidence calibration.
- **Research Gap:** A testable way to decide when a twin verdict is reliable enough to act on—and when the system should admit uncertainty.

---

### Slide 5: Conceptual Framework
- **Flowchart Workflow:**
  1. Validation Question $q$
  2. Evidence Ingestion $(A, F, M, V, P)$
  3. Confidence Estimation ($C_q$)
  4. Decision Node: $C_q \ge \theta$?
     - **Yes:** Return `SAFE` / `UNSAFE`
     - **No:** Return `UNCERTAIN` -> Select Next Probe (Information Gain / Cost) -> Gather new evidence -> Loop back to Ingestion.
- **Features Defined:** $A$ = Coverage, $F$ = Freshness, $M$ = Model Agreement, $V$ = Verification Coverage, $P$ = Probe Consistency.

---

### Slide 6: System Architecture
- **01 Evidence Ingestor:** Normalizes configs, state, and topology + provenance.
- **02 Twin Builder:** Builds Batfish snapshots and Containerlab/FRR environments.
- **03 Intent Library:** Reachability, isolation, service access, and routing paths.
- **04 Partial-Obs Generator (Experiment Control):** Applies controlled missingness/staleness treatments.
- **Verification Core:** Differential checks + Batfish intent evaluation.
- **05 Confidence Engine:** Generates calibrated query-level $C_q$.
- **06 Probe Selector:** Recommends highest-value approved active probe on low confidence.
- **07 Fault Localizer:** Runs counterfactual repair and ranks causes on observation mismatch.
- **08 Operator Report:** Outputs verdict, confidence, probes, gaps, and ranked causes.
- **Tech Stack:** Batfish/pyBatfish, Containerlab, FRRouting, Python, Git.

---

### Slide 7: Methodology Overview
- **Study Design:** Design-science approach with controlled experiments.
- **Study Environment:**
  - Approved campus segment: 8–20 logical elements, 4–10 endpoint groups.
  - Fully controlled reference topology in Containerlab (FRRouting + Linux hosts).
- **Scope:** L2/L3 reachability, isolation, routing, VLAN, addressing, ACL changes. **No production fault injection.**
- **Data Sources:** Topology (LLDP/diagrams), Configuration (sanitized models), State (read-only routes/status), Active Observations (rate-limited ICMP/TCP checks), Experiment Labels.

---

### Slide 8: Confidence Estimation
- **Definition:** $\text{Confidence} = P(\text{Verdict matches Ground Truth} \mid \text{Available Evidence})$
- **Candidate Features:**
  1. Proportion of required artifacts present ($A_q$)
  2. Age of artifacts relative to freshness window ($F_q$)
  3. Amount of unsupported or translated configuration
  4. Verification coverage ($V_q$)
  5. Agreement between Batfish and emulated behavior
  6. Consistency with approved probes ($P_q$)
  7. Agreement across plausible completions of missing evidence ($M_q$)
- **Model:** Logistic regression + Isotonic regression calibration.
- **Baselines:** B1 (Binary Batfish), B2 (Completeness heuristic), B3 (Uncalibrated score).
- **Evaluation:** Brier score, Expected Calibration Error (ECE), Reliability diagrams.

---

### Slide 9: Active Probe Selection
- **Goal:** Select probes that maximize information gain per cost.
- **Selection Criterion:** Estimate expected uncertainty reduction and divide by normalized cost (traffic, time, sensitivity): $\max \frac{\Delta H}{\text{Cost}}$.
- **Stopping Criteria:** Confidence $\ge \theta$ OR Probe budget exhausted OR No useful probe remains.
- **Comparisons:** Random probing, Fixed endpoint probing, Exhaustive permitted probing.
- **Pre-approved Probe Types:** ICMP checks, TCP service tests, traceroute, interface-status queries, SNMP reads.

---

### Slide 10: Fault Localization & Partial Observability
- **Partial Observability Levels:** 100%, 90%, 75%, 50%, 25%.
- **Degradation Forms:** Random evidence removal, targeted removal of path-critical items, staleness/conflict.
- **Fault Classes Evaluated:**
  - *ACL / Firewall:* Service unreachable or isolation violated.
  - *VLAN:* Endpoint isolated or unintended boundary crossing.
  - *Addressing:* Partial or asymmetric reachability.
  - *Routing:* Blackhole, detour, or routing loop.
  - *Link / State:* Loss of reachability or resilience.
  - *Documentation / Model:* Twin-to-real mismatch without production fault.
- **Fault Localization Logic:** Identify elements affecting failed intent -> Counterfactually toggle suspected items -> Re-evaluate predictions -> Rank candidates by path relevance, freshness, and model simplicity.

---

### Slide 11: Experimental Design
- **Minimum Automated Target:** 480 labeled trials per topology ($6 \text{ fault classes} \times 8 \text{ instances} \times 5 \text{ completeness levels} \times 2 \text{ missingness patterns}$).
- **8-Step Experimental Procedure:**
  1. Freeze baseline topology and intents.
  2. Create candidate change or inject labeled fault.
  3. Verify true outcome using complete evidence.
  4. Apply missingness/staleness treatment.
  5. Run baseline verifiers and proposed verifier.
  6. If uncertain, execute active-probe selection loop.
  7. Record verdict, confidence, affected intent, ranked causes, probes, and runtime.
  8. Reset and repeat with fixed random seeds.
- **Evaluation Measures:** Unsafe-change recall/precision/F1; Brier score, ECE; Top-1, Top-3, MRR; Probe overhead; Operational latency.

---

### Slide 12: Baselines & Ablation Studies
- **Baselines:**
  - B1 — Binary Verifier (Batfish pass/fail without confidence).
  - B2 — Completeness Heuristic (Confidence = available evidence ratio).
  - B3 — Random Probing (Equal budget, random selection).
  - B4 — Fixed/Full Probing (Predefined endpoint matrix or exhaustive scan).
- **Ablation Studies:** Remove Freshness, Model-agreement, Verification-coverage, or Probe-consistency features one at a time.
- **Performance Targets ($\ge 75\%$ evidence):**
  - Unsafe-change recall $\ge 0.90$
  - Expected Calibration Error (ECE) $\le 0.10$
  - $\ge 30\%$ fewer probes than exhaustive testing with comparable Top-3 localization.

---

### Slide 13: Timeline (11 Months)
- Month 1: Approvals, security/data plan, pilot topology demo.
- Month 2: Baseline study, evidence collection, reference topology frozen.
- Month 3: Batfish snapshots, Containerlab emulation, intent library.
- Month 4: Change/fault scenario library and test automation.
- Month 5: Missingness models, baselines, and pilot runs.
- Month 6: Confidence model development and Mid-Term Progress Review.
- Month 7: Probe selector and counterfactual fault localizer.
- Month 8: Automated experiments (480 trials) and robustness checks.
- Month 9: Lab/campus validation replay and stakeholder feedback.
- Month 10: Statistical analysis, checklist, manuscript drafting and submission.
- Month 11: Revision, artifact archiving, final report, and seminar.

---

### Slide 14: Budget Allocation (NPR 75,000 — Class B)
- **A. Infrastructure & Computing (NPR 23,000 | 30.7%):**
  - A1: Consumables (patch cords, connectors): NPR 7,000
  - A2: Secure backup/media for snapshots: NPR 6,000
  - A3: Hosted compute / backup fallback: NPR 10,000
- **B. Research & Publication (NPR 30,000 | 40.0%):**
  - B1: Off-hour measurements & local travel: NPR 7,000
  - B2: Data prep & reproducibility archive: NPR 5,000
  - B3: Peer-reviewed publication processing: NPR 18,000
- **C. Support & Dissemination (NPR 22,000 | 29.3%):**
  - C1: Student research support for lab work: NPR 12,000
  - C2: Printing, binding, and final report: NPR 4,000
  - C3: Seminar, poster, and demo materials: NPR 3,000
  - C4: Communication and coordination: NPR 2,000
  - C5: Approved contingency: NPR 1,000
- **Total:** NPR 75,000 (*No investigator salaries or capital hardware purchases*).

---

### Slide 15: Expected Outputs & Dissemination
- **Tangible Outputs:**
  1. Working confidence-aware digital-twin prototype (CLI + operator report).
  2. Documented campus-segment model or anonymized equivalent.
  3. Labeled dataset of change, fault, and partial-observability scenarios.
  4. Reproducible experiment scripts and analysis notebooks.
- **Practical Deliverables:**
  - Pre-change operational checklist.
  - Final technical report.
  - Three formal presentations: Proposal defense, Mid-term review, Final seminar.
  - At least one submitted peer-reviewed manuscript.
- **Student Training:** Hands-on experience in network verification, emulation, statistical calibration, and technical writing.

---

### Slide 16: Risk Mitigation
- **High Risks:**
  - *Campus data access:* Secure approval in Month 1; freeze lab replica fallback by Month 2.
  - *Mixed-vendor parsing:* Normalize into vendor-neutral schema; check against forwarding state.
  - *Production safety:* Read-only collection, probe allow-list, zero production fault injection.
  - *Publication delay:* Select venue by Month 5; draft from Month 8; maintain backup venue.
- **Medium/Low Risks:**
  - *Scope creep:* Limit strictly to L2/L3 intents.
  - *Scenario diversity:* Pre-register 6 fault classes, 2 topologies, and held-out test sets.
  - *Compute limits:* Lightweight FRR containers + conditional hosted compute fallback.
- **Core Principle:** Controlled lab replica + fixed scope + read-only data + predefined test scenarios.

---

### Slide 17: Ethical & Safety Considerations
- **Authorization:** Written approval specifying devices, fields, time windows, and probe rates.
- **Production Safety:** Strictly read-only collection; no configuration pushes or production fault injection.
- **Data Minimization:** Collect only L2/L3 headers/configs required for declared intents; no payload inspection.
- **Credential Protection:** Zero credentials in code/repos; least-privilege service accounts.
- **Anonymization:** Device names, IP addresses, and physical locations pseudonymized.
- **Responsible Disclosure:** Privately notify campus ICT unit of any newly discovered vulnerabilities before dissemination.
- **Safety Principle:** Authorized + Read-only + Minimal Data + Controlled Experiments.

---

### Slide 18: Novelty, Limitations, and Claim Boundary
- **Novel Elements:**
  1. Confidence as a first-class output for query and evidence state.
  2. Partial observability treated as a controlled experimental variable.
  3. Probe-efficient uncertainty reduction based on information gain.
  4. Integrated verification, observation mismatch, and counterfactual diagnosis.
  5. Low-resource campus design using open-source tools and read-only interaction.
- **What the Study Will NOT Claim:**
  - Not an autonomous campus-wide controller or full agentic-AI stack.
  - Not a general probability that the entire network is healthy.
  - Not a replacement for operator authorization or production safety controls.
  - Not generalizable beyond similar educational networks without external validation.
- **Core Contribution:** A decision framework for determining when to trust a digital-twin verdict and when to admit uncertainty.

---

### Slide 19: Summary & Closing
- **The Problem:** Network changes are risky; existing verification tools assume complete evidence and cannot quantify model uncertainty.
- **Our Solution:** A confidence-aware network digital twin that estimates verdict reliability, recommends targeted probes when uncertain, and counterfactually ranks faults.
- **Key Contributions:** Calibrated confidence, partial-observability benchmarks, minimal probing, and low-resource campus applicability.
- **Expected Impact:** Safer changes at Thapathali Campus, reproducible datasets, peer-reviewed publication, and student research development.
- **Take-Home Message:** *How confident are we that the verdict is correct?*

---

### Slide 20: Thank You & Q&A
- **Principal Investigator:** Er. Kobid Karkee (`kobid@tcioe.edu.np`)
- **Student Co-Investigators:** Plan Ghimire • Pranjal Shrestha
- **Acknowledgments:** Thapathali Campus Administration, Research and Development Unit, and the open-source communities behind Batfish, Containerlab, FRRouting, and Python.
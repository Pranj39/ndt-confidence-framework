# Confidence-Aware Network Digital Twin for Safe Change Validation and Fault Localization under Partial Observability: A Thapathali Campus Case Study

**Institution:** Tribhuvan University, Institute of Engineering, Thapathali Campus  
**Unit:** Research and Development Unit  
**Grant Program:** Faculty Research Grant 2083/84  
**Research Class:** Class B — dry-lab / software testbed with limited real-network validation  
**Cluster:** Electronics and Computer Engineering  
**Specialization:** Computer Networking and Cybersecurity  
**Principal Investigator:** Er. Kobid Karkee  
**Student Co-Investigators:** Plan Ghimire, Pranjal Shrestha, Chitra Raj Joshi  
**Submission Date:** 06/04/2083  

---

## Abstract
Keeping a campus network running while making changes to it is a routine but risky part of network administration. Access-control rules, VLANs, routes, IP addressing, and physical links may all need to be changed, yet teaching, administration, and laboratory services are still expected to remain available. The problem becomes harder when documentation is incomplete, devices come from different vendors, or the available measurements are already outdated. Most verification and digital-twin tools can tell an operator what the supplied model predicts, but they say much less about how much that prediction should be trusted when the model itself is incomplete.

This research proposes a confidence-aware network digital twin (NDT) for an approved segment of Thapathali Campus, with a laboratory replica used where direct access is not possible. The proposed system will bring together sanitized read-only configuration and topology data, Batfish-based verification, Containerlab/FRRouting emulation, and a limited set of approved active probes. For each validation question, the system will estimate confidence from the evidence that is actually available, including its coverage, freshness, consistency, verification coverage, and agreement across plausible versions of missing information. When the confidence is too low, the system will recommend the next authorized measurement that is expected to remove the most uncertainty. A counterfactual fault-localization step will then rank the network elements most likely to explain any mismatch between predicted and observed behavior.

We will evaluate the prototype with controlled configuration changes and injected faults in a fully managed test environment. The experiments will deliberately remove, age, or selectively hide network evidence so that the effect of partial observability can be measured rather than assumed. The evaluation will focus on unsafe-change detection, top-k fault-localization accuracy, time to diagnosis, execution time, probe overhead, and confidence calibration. Results will be compared with ordinary binary Batfish verification and simpler completeness-based confidence baselines. No production fault will be injected into the campus network. Any real-campus validation will be limited to authorized read-only observations, approved historical snapshots, or a laboratory replica. The project is planned for 11 months with a Class B budget of NPR 75,000. Its main outputs will be a reproducible prototype, an anonymized scenario dataset, an operational checklist, a final report, and a manuscript prepared for peer-reviewed publication.

**Keywords:** Network digital twin; network verification; partial observability; confidence calibration; active probing; fault localization; campus networks.

---

## 1. Background
Modern university work depends heavily on the network, even when that dependency is not always visible to users. Teaching, examinations, administration, laboratories, library systems, communication platforms, and research services all rely on stable connectivity. At the same time, a campus network is rarely uniform. Enterprise Wi-Fi, computer labs, servers, access switches, routers, security gateways, student devices, cameras, biometric systems, and older equipment may all operate together under different technical and budget constraints. Because of these dependencies, a change that looks small on one device can create an unexpected effect somewhere else. An ACL update, VLAN migration, route change, or maintenance activity can accidentally isolate a laboratory, expose a service that should remain protected, or create an asymmetric forwarding path.

Thapathali Campus already relies on centrally supported digital services, so network reliability has a direct operational value. The public EMIS Wi-Fi guidance, for example, mentions a regular Sunday maintenance window, asks users to report the building and room when connection problems continue, and recommends advance verification for events and laboratory activities [1]. These public instructions do not reveal the internal network design, and this proposal does not assume that they prove any particular outage. They do, however, show that planned maintenance, service verification, and troubleshooting are practical campus concerns. For that reason, the exact size, device mix, and documentation quality of the study segment will be established only after approval and baseline observation.

A network digital twin (NDT) can be understood as a virtual network model that remains connected to evidence from the real system it represents. ITU-T Y.3090 and the IRTF NMRG reference architecture describe NDTs as tools for analysis, diagnosis, emulation, and safer evaluation of proposed network changes [2], [3]. The important difference from a stand-alone simulator is the link back to actual network evidence. For a campus environment, this creates a practical opportunity: intended changes can be checked in a controlled model before they are applied to services used by students, staff, and administration.

That advantage only holds when the twin is faithful enough for the question being asked. If a topology diagram is incomplete, an interface state is old, a vendor feature is not modeled correctly, or a critical ACL is missing, the twin may still return a confident-looking answer that is wrong. The IRTF architecture also identifies data accuracy, model complexity, synchronization, heterogeneous data integration, and information leakage as continuing challenges [3]. These issues are especially relevant in resource-constrained environments, where inventories may be partly manual and a single unified management platform may not exist.

### 1.1 Operational Motivation
* Campus changes are often carried out within limited maintenance windows, so lengthy manual checking can increase both risk and pressure on the operator.
* Useful network knowledge may be scattered across configuration files, diagrams, spreadsheets, live measurements, and the experience of the people who maintain the system.
* A simple PASS result is not enough when the model may be missing the exact ACL, route, VLAN, or link that determines the answer.
* Collecting every possible measurement is also not practical. It creates extra traffic, takes time, and may expose information that is not needed for the decision at hand.
* What an operator really needs is a result that explains what may fail, how reliable the prediction is, which evidence is missing, and where the next investigation should start.

---

## 2. Problem Statement
This study focuses on a practical weakness in current network-change verification: the result is only as reliable as the network evidence supplied to the model, yet most tools do not quantify that limitation for the operator. Configuration-analysis systems can calculate forwarding behavior and support what-if analysis before a change is deployed [4], [5]. However, the resulting answer is normally based on a single supplied snapshot. When important configuration, topology, or state information is missing or stale, a binary pass/fail result does not show how much uncertainty remains or whether the operator should trust the verdict.

The central question of the study is therefore straightforward: how can a campus network digital twin report not only a change-validation verdict, but also a calibrated and explainable level of confidence in that verdict, and how can it identify the smallest useful set of additional observations when the available evidence is not enough? The proposed solution is designed to answer this without experimenting on the production network.

**Scope Boundary:** The study is limited to L2/L3 reachability, isolation, routing, VLAN, addressing, and ACL-related changes in one selected campus segment or its laboratory replica. It will not attempt to build a campus-wide autonomous controller, reproduce the full Aether agentic-AI stack, or introduce faults into the production network.

---

## 3. Literature Review and Research Gap

### 3.1 Network Verification and Configuration Analysis
Formal network verification has already shown that many configuration problems can be found before a change reaches the live network. Header Space Analysis introduced a systematic way to reason about reachability, loops, and isolation by tracking how packet headers are transformed by network rules [6]. Batfish later combined configuration parsing with control-plane and data-plane reasoning, allowing operators to test reachability and other network properties against configuration snapshots [4]. Its evaluation included two large university networks and reported operator-confirmed configuration problems [4]. Minesweeper applies satisfiability-based reasoning to network-wide verification [5], while Plankton uses model checking to improve scalability [7]. Together, these systems provide strong foundations for proactive verification. Their main limitation for our problem is that they generally reason about the model they are given; they do not directly tell the operator how trustworthy that model is when important evidence is missing or outdated.

### 3.2 Test Coverage, Specifications, and Partial Configurations
Another part of the literature looks at whether the right parts of a configuration are being tested. NetCov showed that a test suite used with the Internet2 network exercised only 26% of configuration lines, and that coverage information could be used to design better tests [8]. Config2Spec reduces the manual effort of writing formal intent by extracting likely specifications from existing configurations [9]. NetComplete synthesizes values for configuration parameters deliberately left open [10]. These studies improve test adequacy, specification discovery, or configuration synthesis. Our problem is different: missing information is not intentionally declared in advance, and the question is how much confidence should be placed in an operational verdict when evidence is missing, stale, or inconsistent.

### 3.3 Network Digital Twins and Change Validation
Network digital twins link a virtual representation to evidence from the real network. A simulator such as ns-3 models behavior at an abstract level, while an emulator such as Containerlab runs virtualized network functions that behave like real routers and hosts. An NDT uses both alongside configuration, topology, state, and measurement data. Reference architectures in [2] and [3] describe this through data, models, mappings, interfaces, and operational functions. CrystalNet showed that high-fidelity emulation can reproduce control-plane behavior from production networks [11]. Aether combined a network digital map, Batfish, simulation tools, and AI agents for automated change validation [12]. However, Aether assumes an up-to-date digital map and does not make uncertainty caused by partial observability its primary focus.

### 3.4 Research Gap Summary Table
| Research Stream | Established Strength | Unresolved Issue Addressed Here |
| :--- | :--- | :--- |
| **Formal verification** | Proactive reachability and policy checking | Usually returns a verdict for the supplied model; trust under missing/stale evidence is not calibrated. |
| **Test coverage** | Shows which configuration elements are exercised | Coverage is not the same as probability that a verdict is correct under partial observability. |
| **Configuration synthesis / specification mining** | Fills declared holes or derives intended behavior | Targets construction of policies/configuration, not residual operational uncertainty in an incomplete twin. |
| **High-fidelity NDT / emulation** | Safe replay and validation before deployment | Fidelity assumes adequate data and can be expensive; low-resource campus constraints are underexplored. |
| **Aether (Agentic AI)** | Automated multi-tool change-validation workflow | Assumes a consistent, up-to-date digital map; no task-level confidence calibration or minimum-probe strategy. |

---

## 4. Foundational and Preliminary Work
No experimental performance result is being claimed at the proposal stage. What we have completed so far is a feasibility check of the intended implementation path. Batfish supports snapshot-based and differential reachability analysis [13]; Containerlab can define and repeatedly deploy container-based network topologies [14]; and FRRouting provides OSPF, BGP, and static-routing behavior in lightweight Linux environments [15]. These tools are open source and can run on existing laboratory resources.

**Campus Access and Fallback Plan:** We will request sanitized, read-only evidence for one approved network segment. If access is delayed or denied, the same research questions will be tested on a laboratory-scale campus replica built using Containerlab/FRR and physical switches.

---

## 5. Conceptual Framework
For each validation question $q$ (e.g., whether a laboratory subnet remains reachable after an ACL change), the twin returns a predicted verdict $\hat{Y}_q$ together with a confidence value $C_q$:
$$C_q = P(Y_q = \hat{Y}_q \mid A_q, F_q, M_q, V_q, P_q)$$

* $A_q$: Coverage of evidence relevant to the question.
* $F_q$: Freshness of the artifacts.
* $M_q$: Agreement across plausible completions of missing information.
* $V_q$: Verification coverage across paths and rules.
* $P_q$: Consistency with approved probe results.

When confidence $C_q < \theta$, the system returns `UNCERTAIN` and triggers the **Probe Selector**, which selects the authorized probe maximizing expected uncertainty reduction per unit cost. After new evidence is collected, confidence is updated and the **Fault Localizer** ranks potential root causes counterfactually.

---

## 6. Research Objectives

### 6.1 General Objective
To build and experimentally evaluate a confidence-aware campus network digital twin that can support safer pre-change verification and fault localization when network information is incomplete or stale.

### 6.2 Specific Objectives
1. Build a reproducible digital-twin model for one approved campus network segment, or an equivalent laboratory topology, using available configuration, topology, and authorized measurement evidence.
2. Measure how the amount, type, and location of missing or stale evidence affect change-validation results and fault localization.
3. Develop an interpretable confidence model and test whether its probability estimates are well calibrated against known outcomes.
4. Design a low-overhead probe-selection method that recommends the most useful next observation when the current evidence is not sufficient.
5. Develop a counterfactual fault-localization method that ranks likely configuration or topology causes when predicted and observed behavior do not match.
6. Compare the proposed workflow with binary verification, completeness-based confidence, and random or exhaustive probing using accuracy, calibration, latency, and overhead measures.
7. Produce a usable prototype, an operational checklist, an anonymized and reproducible experiment package, the final research report, and a manuscript for peer-reviewed publication.

---

## 7. Research Questions and Hypotheses

| ID | Research Question |
| :--- | :--- |
| **RQ1** | How do the amount, type, and location of missing or stale network evidence affect pre-change validation and fault-localization accuracy? |
| **RQ2** | Can an interpretable evidence- and model-agreement-based score provide well-calibrated confidence in a digital-twin verdict? |
| **RQ3** | Can targeted active probes recover confidence and localization accuracy with less overhead than random or exhaustive probing? |
| **RQ4** | How closely do results from the virtual twin match an approved lab-scale or read-only campus validation environment? |

### 7.1 Testable Hypotheses
* **H1:** Removing evidence from path-critical links, ACLs, VLANs, or routes will reduce validation accuracy more than removing the same amount of evidence at random.
* **H2:** The calibrated confidence model will produce lower Brier score and expected calibration error (ECE) than a confidence score based only on evidence completeness.
* **H3:** The proposed probe-selection method will reduce uncertainty and improve top-3 fault localization more efficiently per probe than random selection.
* **H4:** For the L2/L3 fault classes included in this study, the proposed workflow will reduce median diagnostic time compared with manual inspection supported only by ping, traceroute, and configuration differences.

**Performance Targets:** With $\ge 75\%$ evidence available: Unsafe-change recall $\ge 0.90$, Expected Calibration Error $\le 0.10$, and $\ge 30\%$ fewer probes than exhaustive testing.

---

## 8. Study Design, Methods, Tools, and Data Analysis

### 8.1 Research Design
Design-science approach supported by controlled experiments. The unit of analysis is one change-validation question evaluated against a defined network snapshot and evidence condition.

### 8.2 Study Environment and Delimitation
* Approved campus segment: 8–20 logical elements, 4–10 endpoint groups.
* Reference topology: Containerlab + FRRouting routers + Linux hosts + VLAN-aware bridges.
* Scope boundary: L2/L3 reachability, isolation, routing, VLAN, addressing, and ACL changes. No live production fault injection.

### 8.3 Data Sources
| Evidence Type | Planned Content |
| :--- | :--- |
| **Topology** | Approved diagrams, LLDP neighbor relations, interface inventory, verified links. |
| **Configuration** | Sanitized device configurations or vendor-neutral normalized model. |
| **State** | Read-only interface/route status, timestamps, approved SNMP command outputs. |
| **Active Observations** | Directed ICMP, traceroute, and approved TCP service checks (rate-limited). |
| **Experiment Labels** | Ground-truth safe/unsafe outcome, fault class/location, evidence completeness, runtime. |

### 8.4 Toolchain
* **Batfish / pyBatfish:** Static configuration parsing, control-plane/data-plane reachability analysis.
* **Containerlab:** Containerized topology deployment and lifecycle management.
* **FRRouting (FRR):** Lightweight routing engine (OSPF, BGP, static routes) in Linux containers.
* **Python:** Evidence graph, confidence calibration, probe selection, counterfactual analysis.
* **Git:** Version control for all snapshots, intents, and experiment seeds.

### 8.5 Prototype Components (Architecture Blocks)
1. **Evidence Ingestor (01):** Normalizes topology, configs, state, and provenance into an Evidence Graph.
2. **Twin Builder (02):** Generates Batfish snapshots and Containerlab/FRR configs from accepted evidence.
3. **Intent Library (03):** Defines formal reachability, isolation, path, and security properties.
4. **Partial-Observability Generator (04):** Degrades evidence (missingness, staleness, conflicts) for experiments.
5. **Confidence Engine (05):** Calibrates verdict probability $C_q$ using logistic and isotonic regression.
6. **Probe Selector (06):** Recommends next probe based on Information Gain per Cost.
7. **Fault Localizer (07):** Counterfactually tests and ranks candidate root causes.
8. **Operator Report (08):** Emits SAFE, UNSAFE, or UNCERTAIN verdict with diagnostic evidence and next actions.

### 8.6 Change and Fault Scenario Library
| Class | Example Manipulation | Observable Consequence |
| :--- | :--- | :--- |
| **ACL / Firewall** | Wrong permit/deny order, omitted exception | Service unreachable or isolation violated |
| **VLAN** | Wrong access VLAN, missing allowed VLAN | Endpoint group isolated or boundary crossing |
| **Addressing** | Wrong subnet mask, duplicate gateway IP | Asymmetric or partial reachability |
| **Routing** | Missing static route, passive-interface error | Blackhole, detour, or routing loop |
| **Link / State** | Administratively disabled interface | Loss of reachability or resilience |
| **Documentation / Model**| Stale neighbor, missing interface entry | Twin-to-real mismatch without production fault |

### 8.7 Partial-Observability Treatments
* **Completeness Levels:** 100%, 90%, 75%, 50%, 25%.
* **Degradation Forms:** Random removal, targeted removal of path-critical items, staleness/conflict.
* **Trial Matrix:** 6 fault classes $\times$ 8 instances $\times$ 5 completeness levels $\times$ 2 missingness patterns = **480 automated labeled trials per topology**, plus at least 30 lab replays.

### 8.8 Baselines and Ablation Studies
* **B1 (Binary Verifier):** Batfish verification without confidence estimation.
* **B2 (Completeness Heuristic):** Confidence = proportion of nominally required evidence present.
* **B3 (Random Probing):** Probes selected uniformly at random within budget.
* **B4 (Fixed / Full Probing):** Predefined test matrix or exhaustive probing.
* **Ablations:** Removing Freshness ($F_q$), Model Agreement ($M_q$), Verification Coverage ($V_q$), and Probe Consistency ($P_q$) individually.

---

## 9. Budget Allocation (NPR 75,000 — Class B)

| Code | Category | Item & Justification | NPR |
| :--- | :--- | :--- | :--- |
| **A1** | Infrastructure & Computing | Patch cords, RJ45 connectors, cable consumables | 7,000 |
| **A2** | Infrastructure & Computing | Secure backup/removable media for snapshots | 6,000 |
| **A3** | Infrastructure & Computing | Hosted compute / backup services (fallback) | 10,000 |
| **Subtotal A** | **30.7% (Ceiling: 50%)** | | **23,000** |
| **B1** | Research & Publication | Approved off-hour measurement sessions & travel | 7,000 |
| **B2** | Research & Publication | Data preparation & reproducibility archive | 5,000 |
| **B3** | Research & Publication | Peer-reviewed publication processing & presentation | 18,000 |
| **Subtotal B** | **40.0% (Ceiling: 40%)** | | **30,000** |
| **C1** | Support & Dissemination | Student research support for scheduled lab work | 12,000 |
| **C2** | Support & Dissemination | Printing, binding, and final report preparation | 4,000 |
| **C3** | Support & Dissemination | Internal seminar, poster, and demo materials | 3,000 |
| **C4** | Support & Dissemination | Communication and coordination expenses | 2,000 |
| **C5** | Support & Dissemination | Contingency for approved research expenses | 1,000 |
| **Subtotal C** | **29.3% (Ceiling: 30%)** | | **22,000** |
| **TOTAL** | | **Class B Grant Total** | **75,000** |

*Note: No investigator salary or capital hardware purchases are included.*

---

## 10. Timeline (11 Months)
* **Month 1:** Approvals, security/data protocol, pilot demonstration (2-router test).
* **Month 2:** Campus baseline observation, evidence schema normalization, fallback replica frozen.
* **Month 3:** Batfish snapshots, Containerlab/FRR emulation, intent library integration.
* **Month 4:** Scenario library automation (reset, inject, label).
* **Month 5:** Partial observability generators, baseline algorithms (B1, B2).
* **Month 6:** Confidence calibration engine, Mid-Term Progress Review and Report.
* **Month 7:** Active probe selector and counterfactual fault localizer.
* **Month 8:** Full factorial experiment runs (480 automated trials) and ablation checks.
* **Month 9:** Laboratory validation replay (30 cases) and operator usability feedback.
* **Month 10:** Statistical analysis, operational checklist, manuscript drafting and submission.
* **Month 11:** Artifact archiving, final project report, final campus seminar.

---

## 11. Ethical, Safety, and Security Protocol
* **Authorization:** Written approval from campus administration specifying exact devices, fields, and windows.
* **Production Safety:** Strictly read-only data collection. Zero live configuration pushes. Zero production fault injection.
* **Data Minimization & Anonymization:** Device hostnames, IP subnets, and user details pseudonymized. No payload inspection.
* **Responsible Disclosure:** Any configuration flaws discovered in campus gear will be privately reported to the ICT section before public dissemination.

---

## References
1. Thapathali Campus EMIS, "WiFi Guide," 2026.
2. ITU-T, "Digital twin network — Requirements and architecture," Rec. Y.3090, 2022.
3. C. Zhou et al., "Network Digital Twin Concepts and Reference Architecture," IRTF Draft, 2026.
4. A. Fogel et al., "A General Approach to Network Configuration Analysis," USENIX NSDI, 2015.
5. R. Beckett et al., "A General Approach to Network Configuration Verification," ACM SIGCOMM, 2017.
6. P. Kazemian et al., "Header Space Analysis: Static Checking for Networks," USENIX NSDI, 2012.
7. S. Prabhu et al., "Plankton: Scalable Network Configuration Verification," USENIX NSDI, 2020.
8. X. Xu et al., "Test Coverage for Network Configurations," USENIX NSDI, 2023.
9. R. Birkner et al., "Config2Spec: Mining Network Specifications," USENIX NSDI, 2020.
10. A. El-Hassany et al., "NetComplete: Practical Network-Wide Configuration Synthesis," USENIX NSDI, 2018.
11. H. H. Liu et al., "CrystalNet: Faithfully Emulating Large Production Networks," ACM SOSP, 2017.
12. J. Auge et al., "Aether: Network Validation Using Agentic AI and Digital Twin," arXiv:2604.18233, 2026.
13. The Batfish Open Source Project, pyBatfish Documentation.
14. Containerlab Project Documentation.
15. FRRouting Project Documentation.
16. A. Niculescu-Mizil & R. Caruana, "Predicting Good Probabilities with Supervised Learning," ICML, 2005.
17. H. H. Liu et al., "Pingmesh: A Large-Scale System for Data Center Latency," ACM SIGCOMM, 2015.
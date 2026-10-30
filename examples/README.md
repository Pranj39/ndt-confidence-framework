# Twin Builder example

The [sample evidence](thapathali_lab.json) is a synthetic teaching-lab network,
not a description of the production Thapathali Campus network.

From the repository root, using the project's Python environment:

```powershell
python -m src.twin_builder.cli compile examples\thapathali_lab.json --output dist --visualize
```

An installed package also provides `twin-builder` and
`python -m twin_builder.cli` with the same arguments. The older form without
`compile` still works as an alias.
Omit `--visualize` to generate only the twin configurations.

The command validates JSON before writing artifacts, then reports:

- `dist/batfish_snapshot/configs/<node>.cfg`
- `dist/containerlab/thapathali-lab.clab.yml`
- `dist/containerlab/clab-configs/R1-Core/frr.conf` and `daemons`
- `dist/topology.html` when visualization is requested

Open the HTML file in a browser to drag nodes, zoom, and hover over interface
addresses and ingress/egress ACL names. All evidence is embedded in the file;
Vis.js itself loads from the specified public CDN, so the interactive view
requires an internet connection. No Python visualization dependencies are added.

## Verifying with Batfish

Install the optional dependency (`pip install -e .[verify]`) and start a local
Batfish service, for example `docker run -d -p 9996:9996 batfish/allinone`. Then:

```bash
twin-builder verify dist/batfish_snapshot \
  --node R1-Core --src-ip 10.0.10.50 --dst-ip 10.0.20.10
```

This uploads the generated snapshot to that Batfish service, prints per-file
parse status and init issues, prints the computed routing table
(Node / Network / Next_Hop_IP / Protocol), and, when `--node`, `--src-ip`, and
`--dst-ip` are all given, traces the flow hop by hop. For this example, the
expected result is `DENIED` by `BLOCK_STUDENT_TO_EXAM`.

`--node` is optional. Without it, the start location is auto-detected from
`--src-ip` using the evidence JSON (`--evidence <json>`, or by default the
`evidence.json` that `compile` writes next to `batfish_snapshot/`):

1. a host whose interface has exactly that IP → the host (for example
   `10.0.10.100` → `Student-Lab-PC` in `thapathali_complex.json`);
2. a router's own interface IP → that router;
3. otherwise the most specific router interface subnet containing it →
   `@enter(Router[Interface])`, so that interface's ingress ACL applies.

An IP outside every known subnet fails with "Source IP does not belong to any
known network in evidence." Use `--host`/`--port`
for a non-default endpoint. The command exits with 1 if Batfish is unreachable
or the snapshot has parse errors. From Python, use `twin_builder.TwinVerifier`.

## Containerlab web graph

```bash
twin-builder graph dist/containerlab/thapathali-lab.clab.yml
```

This runs `sudo containerlab graph -t <file>` (without `sudo` when already
root). The process serves a local web view until you press Ctrl+C. It needs a
Linux host with Containerlab installed; it reads only the local topology file.

## Model and execution boundaries

- The core has two distribution-facing interfaces: `10.0.10.1/24` for students
  and `10.0.20.1/24` for exam services, plus `Loopback0`.
- Both hosts have a default route through their corresponding core address.
- OSPF area 0 contains both subnets and the loopback; all interfaces are passive
  because this single-router sample has no OSPF neighbor.
- `BLOCK_STUDENT_TO_EXAM` denies `10.0.10.0/24` to the exam server
  `10.0.20.10/32`, then permits other IPv4 traffic.
- The distribution switch is an untagged shared bridge, not a VLAN-isolated
  production switch. The two IP subnets share Layer 2. This example does not
  claim VLAN isolation or protection against endpoints changing their address.
- ACLs are rendered **only in Batfish**; FRR/Containerlab ACL enforcement is not
  implemented. The map shows supplied evidence, not measured forwarding results.
- `compile` only generates files; `verify` and `graph` only use local Batfish
  and Containerlab tooling. The CLI does not start Batfish, create the
  Containerlab host bridge, deploy containers, or contact campus devices.
  Containerlab `kind: bridge` requires a pre-created Linux bridge in a controlled
  Linux lab. Linux interface names are limited to 15 characters; before any
  deployment, shorten `SW1-Distribution` (16 characters) consistently in the
  evidence and links, then regenerate the topology and create that bridge.

`NetworkEvidence.model_validate_json()` retains the existing dataclass models
and uses only the standard library. It constructs nested models, rejects unknown
fields and incorrect JSON types, and applies the existing address/ACL/link
validation. Invalid input exits the CLI with status 2; write errors use status 1.

## Intent Library examples

- [thapathali_complex.json](thapathali_complex.json) is the two-router campus core
  used by the intents. Its router interfaces carry descriptions (`Student Lab`,
  `Faculty LAN`, `Exam Servers`, `EMIS Services`), which auto-discovery turns
  into groups such as `student_lab`.
- [thapathali_groups.json](thapathali_groups.json) is a curated endpoint-group
  registry: `students`, `exam_db`, `emis_portal`, and `faculty`. Its `aliases`
  map the auto-discovered names onto those groups: `student_lab` → `students`,
  `exam_db_server` → `exam_db`, `faculty_lan` → `faculty`.
- [thapathali_intents.json](thapathali_intents.json) contains four intents. They
  use the auto-discovered names, so they work with or without `--groups`:
  - INT-001: `student_lab` is isolated from `exam_db_server`;
  - INT-002: `student_lab` reaches `emis_portal` over HTTPS;
  - INT-003: `faculty_lan` reaches `exam_db_server`;
  - INT-004: the core is loop-free.

  These match `SECURITY_POLICY_CORE` on `R1-Core-Admin`, so a correct snapshot
  should report `V_q = 1.00`.

```bash
twin-builder compile examples/thapathali_complex.json -o dist
twin-builder check-intents dist/batfish_snapshot examples/thapathali_intents.json
twin-builder check-intents dist/batfish_snapshot examples/thapathali_intents.json \
  --groups examples/thapathali_groups.json
```

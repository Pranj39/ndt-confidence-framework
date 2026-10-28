"""Generate a topology map using only the standard library and browser-side Vis.js."""

import json
from pathlib import Path

from .schema import NetworkEvidence


_NODE_STYLES = {
    "router": {"color": "#ff6b6b", "shape": "box"},
    "switch": {"color": "#4ecdc4", "shape": "diamond"},
    "host": {"color": "#ffe66d", "shape": "dot"},
}

_HTML = """<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Network Digital Twin - Topology</title>
  <style>
    body { margin: 0; font: 16px system-ui, sans-serif; color: #17212b; }
    header { padding: 16px 24px; background: #f3f6f9; }
    h1 { margin: 0 0 8px; font-size: 24px; }
    p { margin: 6px 0; }
    #network { height: 75vh; min-height: 360px; border-top: 1px solid #ccd5de; }
    #status { color: #8a3200; }
    .vis-tooltip pre { margin: 0; white-space: pre-wrap; max-width: 420px; }
  </style>
  <script type="text/javascript" src="https://unpkg.com/vis-network/standalone/umd/vis-network.min.js"></script>
</head>
<body>
  <header>
    <h1 id="heading">Network topology</h1>
    <p>Red box: router | Teal diamond: switch | Yellow circle: host</p>
    <p>Drag nodes, scroll to zoom, and hover for interface and ACL details.</p>
    <p>Evidence view only. ACL enforcement is currently modeled in Batfish, not Containerlab.</p>
    <p id="status" role="status">Loading map. Internet access is required for Vis.js.</p>
  </header>
  <div id="network" aria-label="Interactive network topology"></div>
  <script id="topology-data" type="application/json">__TOPOLOGY_DATA__</script>
  <script>
    const data = JSON.parse(document.getElementById("topology-data").textContent);
    document.getElementById("heading").textContent = data.name + " - Topology";
    const status = document.getElementById("status");
    if (typeof vis === "undefined") {
      status.textContent = "Map unavailable: Vis.js could not load from the CDN. " +
        "Check your internet connection and reload.";
    } else {
      const nodes = data.nodes.map(node => {
        const title = document.createElement("pre");
        title.textContent = node.title;
        return {...node, title};
      });
      const options = {
        physics: {enabled: true, stabilization: {iterations: 150}},
        interaction: {dragNodes: true, dragView: true, zoomView: true, hover: true},
        nodes: {size: 25, font: {size: 16}, borderWidth: 2},
        edges: {font: {size: 12, align: "middle"}, smooth: {type: "dynamic"}}
      };
      const network = new vis.Network(
        document.getElementById("network"),
        {nodes: new vis.DataSet(nodes), edges: new vis.DataSet(data.edges)},
        options
      );
      status.textContent = data.nodes.length + " nodes | " + data.edges.length + " links";
    }
  </script>
</body>
</html>
"""


def generate_interactive_map(
    evidence: NetworkEvidence, output_html: str = "topology.html"
) -> str:
    """Write an HTML evidence map and return its path.

    The HTML embeds all topology data, but loads Vis.js from its public CDN.
    No Python visualization package, server, or deployment is required.
    """
    nodes: list[dict[str, object]] = []
    for node in evidence.nodes:
        tooltip = [f"{node.name} ({node.kind})"]
        for interface in node.interfaces:
            tooltip.append(
                f"{interface.name}: {interface.ip_address or 'No IP address'} "
                f"({'enabled' if interface.enabled else 'disabled'})"
            )
            if interface.applied_ingress_acl:
                tooltip.append(f"  Ingress ACL: {interface.applied_ingress_acl}")
            if interface.applied_egress_acl:
                tooltip.append(f"  Egress ACL: {interface.applied_egress_acl}")
        nodes.append(
            {
                "id": node.name,
                "label": node.name,
                "title": "\n".join(tooltip),
                **_NODE_STYLES[node.kind],
            }
        )
    edges = [
        {
            "id": index,
            "from": link.source_node,
            "to": link.target_node,
            "label": f"{link.source_iface} <-> {link.target_iface}",
            "title": (
                f"{link.source_node}:{link.source_iface} <-> "
                f"{link.target_node}:{link.target_iface}"
            ),
        }
        for index, link in enumerate(evidence.links)
    ]
    payload = json.dumps({"name": evidence.name, "nodes": nodes, "edges": edges})
    # Prevent evidence text from terminating the embedded script element.
    payload = payload.replace("&", "\\u0026").replace("<", "\\u003c").replace(">", "\\u003e")
    output_path = Path(output_html)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(_HTML.replace("__TOPOLOGY_DATA__", payload), encoding="utf-8")
    return str(output_path)

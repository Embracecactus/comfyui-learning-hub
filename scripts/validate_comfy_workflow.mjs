#!/usr/bin/env node

import fs from "node:fs";

const workflowPaths = process.argv.slice(2);
if (workflowPaths.length === 0) {
  console.error("Usage: node scripts/validate_comfy_workflow.mjs <workflow.json> [...]");
  process.exit(2);
}

function isSubgraphId(value) {
  return typeof value === "string" && /^[0-9a-f-]{36}$/.test(value);
}

for (const workflowPath of workflowPaths) {
  const workflow = JSON.parse(fs.readFileSync(workflowPath, "utf8"));
  const nodeIds = new Set(workflow.nodes.map((node) => node.id));
  if (nodeIds.size !== workflow.nodes.length) {
    throw new Error(`${workflowPath}: duplicate top-level node id`);
  }

  const linkIds = new Set();
  for (const [id, originId, , targetId] of workflow.links || []) {
    if (linkIds.has(id)) throw new Error(`${workflowPath}: duplicate link ${id}`);
    linkIds.add(id);
    if (!nodeIds.has(originId) || !nodeIds.has(targetId)) {
      throw new Error(`${workflowPath}: dangling link ${id}: ${originId} -> ${targetId}`);
    }
  }

  const subgraphs = new Map(
    (workflow.definitions?.subgraphs || []).map((subgraph) => [subgraph.id, subgraph]),
  );

  for (const node of workflow.nodes) {
    if (isSubgraphId(node.type) && !subgraphs.has(node.type)) {
      throw new Error(`${workflowPath}: missing subgraph definition ${node.type}`);
    }
  }

  for (const subgraph of subgraphs.values()) {
    const internalIds = new Set(subgraph.nodes.map((node) => node.id));
    if (subgraph.inputNode?.id !== undefined) internalIds.add(subgraph.inputNode.id);
    if (subgraph.outputNode?.id !== undefined) internalIds.add(subgraph.outputNode.id);

    for (const link of subgraph.links || []) {
      if (!internalIds.has(link.origin_id) || !internalIds.has(link.target_id)) {
        throw new Error(
          `${workflowPath}: dangling subgraph link ${subgraph.name}:${link.id} `
            + `${link.origin_id} -> ${link.target_id}`,
        );
      }
    }

    for (const node of subgraph.nodes) {
      if (isSubgraphId(node.type) && !subgraphs.has(node.type)) {
        throw new Error(`${workflowPath}: missing nested subgraph definition ${node.type}`);
      }
    }
  }

  const internalNodeCount = [...subgraphs.values()].reduce(
    (total, subgraph) => total + subgraph.nodes.length,
    0,
  );
  console.log(
    `${workflowPath}: OK (${workflow.nodes.length} top-level nodes, `
      + `${workflow.links?.length || 0} top-level links, ${subgraphs.size} subgraphs, `
      + `${internalNodeCount} internal nodes)`,
  );
}

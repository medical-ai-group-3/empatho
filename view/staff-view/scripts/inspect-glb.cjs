const fs = require("fs");
const path = process.argv[2];
const buf = fs.readFileSync(path);
const jsonChunkLength = buf.readUInt32LE(12);
const jsonBytes = buf.slice(20, 20 + jsonChunkLength);
const json = JSON.parse(jsonBytes.toString("utf8"));

console.log("asset:", JSON.stringify(json.asset));
console.log("scenes:", json.scenes?.length, "default scene:", json.scene);
console.log("nodes count:", json.nodes?.length);
console.log("meshes count:", json.meshes?.length);
console.log("materials count:", json.materials?.length);
console.log("animations count:", json.animations?.length);

console.log("\n--- top-level scene node roots ---");
const scene = json.scenes[json.scene ?? 0];
console.log("root node indices:", scene.nodes);

console.log("\n--- node tree (name, mesh, children) ---");
function printNode(i, depth) {
  const n = json.nodes[i];
  const indent = "  ".repeat(depth);
  console.log(`${indent}[${i}] ${n.name || "(no name)"}${n.mesh != null ? " mesh=" + n.mesh : ""}`);
  if (n.children) n.children.forEach((c) => printNode(c, depth + 1));
}
scene.nodes.forEach((i) => printNode(i, 0));

console.log("\n--- mesh names ---");
json.meshes?.forEach((m, i) => console.log(i, m.name || "(no name)", "primitives:", m.primitives.length));

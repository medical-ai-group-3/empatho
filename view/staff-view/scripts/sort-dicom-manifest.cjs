const fs = require("fs");
const path = require("path");
const dicomParser = require("dicom-parser");

const dir = process.argv[2];
if (!dir) {
  console.error("usage: node sort-dicom-manifest.cjs <dir>");
  process.exit(1);
}

const files = fs.readdirSync(dir).filter((f) => f.endsWith(".dcm"));

const rows = files.map((f) => {
  const buf = fs.readFileSync(path.join(dir, f));
  const byteArray = new Uint8Array(buf);
  const ds = dicomParser.parseDicom(byteArray);
  const instanceNumber = ds.intString("x00200013");
  const ipp = ds.string("x00200032"); // ImagePositionPatient "x\y\z"
  const z = ipp ? parseFloat(ipp.split("\\")[2]) : null;
  return { file: f, instanceNumber, z };
});

const haveInstanceNumber = rows.every((r) => r.instanceNumber !== undefined && r.instanceNumber !== null);
rows.sort((a, b) => (haveInstanceNumber ? a.instanceNumber - b.instanceNumber : a.z - b.z));

console.log(`sorted by ${haveInstanceNumber ? "InstanceNumber" : "ImagePositionPatient.z"}`);
console.log(`first: ${rows[0].file} (instanceNumber=${rows[0].instanceNumber}, z=${rows[0].z})`);
console.log(`last:  ${rows[rows.length - 1].file} (instanceNumber=${rows[rows.length - 1].instanceNumber}, z=${rows[rows.length - 1].z})`);

fs.writeFileSync(path.join(dir, "manifest.json"), JSON.stringify(rows.map((r) => r.file)));
console.log(`wrote manifest.json with ${rows.length} files`);

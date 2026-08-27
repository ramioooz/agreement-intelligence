#!/usr/bin/env node

import { execFileSync } from "node:child_process";
import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import process from "node:process";

const outputDirectory = path.resolve(
  process.argv[2] ?? "artifacts/manual-qa/fixtures",
);
fs.mkdirSync(outputDirectory, { recursive: true });

function pdfWithText(text) {
  const escaped = text
    .replaceAll("\\", "\\\\")
    .replaceAll("(", "\\(")
    .replaceAll(")", "\\)");
  const stream = `BT /F1 10 Tf 54 730 Td (${escaped}) Tj ET`;
  const objects = [
    "<< /Type /Catalog /Pages 2 0 R >>",
    "<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
    "<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Resources << /Font << /F1 5 0 R >> >> /Contents 4 0 R >>",
    `<< /Length ${Buffer.byteLength(stream)} >>\nstream\n${stream}\nendstream`,
    "<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
  ];
  let pdf = "%PDF-1.4\n";
  const offsets = [0];
  objects.forEach((object, index) => {
    offsets.push(Buffer.byteLength(pdf));
    pdf += `${index + 1} 0 obj\n${object}\nendobj\n`;
  });
  const xrefOffset = Buffer.byteLength(pdf);
  pdf += `xref\n0 ${objects.length + 1}\n0000000000 65535 f \n`;
  pdf += offsets
    .slice(1)
    .map((offset) => `${String(offset).padStart(10, "0")} 00000 n \n`)
    .join("");
  pdf += `trailer\n<< /Size ${objects.length + 1} /Root 1 0 R >>\nstartxref\n${xrefOffset}\n%%EOF\n`;
  return Buffer.from(pdf);
}

function blankPdf() {
  return pdfWithText("");
}

function writeDocx(destination, text) {
  const temporary = fs.mkdtempSync(
    path.join(os.tmpdir(), "agreement-intelligence-docx-"),
  );
  try {
    fs.mkdirSync(path.join(temporary, "_rels"), { recursive: true });
    fs.mkdirSync(path.join(temporary, "word"), { recursive: true });
    fs.writeFileSync(
      path.join(temporary, "[Content_Types].xml"),
      '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>' +
        '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">' +
        '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>' +
        '<Default Extension="xml" ContentType="application/xml"/>' +
        '<Override PartName="/word/document.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/>' +
        "</Types>",
    );
    fs.writeFileSync(
      path.join(temporary, "_rels/.rels"),
      '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>' +
        '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">' +
        '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="word/document.xml"/>' +
        "</Relationships>",
    );
    const escaped = text
      .replaceAll("&", "&amp;")
      .replaceAll("<", "&lt;")
      .replaceAll(">", "&gt;");
    fs.writeFileSync(
      path.join(temporary, "word/document.xml"),
      '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>' +
        '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">' +
        `<w:body><w:p><w:r><w:t>${escaped}</w:t></w:r></w:p><w:sectPr/></w:body></w:document>`,
    );
    const fixed = new Date("1980-01-01T00:00:00Z");
    for (const relative of [
      "[Content_Types].xml",
      "_rels",
      "_rels/.rels",
      "word",
      "word/document.xml",
    ]) {
      fs.utimesSync(path.join(temporary, relative), fixed, fixed);
    }
    fs.rmSync(destination, { force: true });
    execFileSync(
      "zip",
      ["-q", "-X", "-r", destination, "[Content_Types].xml", "_rels", "word"],
      { cwd: temporary },
    );
  } finally {
    fs.rmSync(temporary, { recursive: true, force: true });
  }
}

const v1 =
  "SYNTHETIC CLIENT AGREEMENT. Parties: Northstar Demo Markets Ltd and Cedar Demo Trading LLC. " +
  "Governing law: England and Wales. Termination notice: 30 days. Liability cap: fees paid in 12 months. " +
  "Confidentiality survives 3 years. Evidence marker: NORTHSTAR-SYNTHETIC-ALPHA.";
const v2 =
  "SYNTHETIC CLIENT AGREEMENT VERSION 2. Parties: Northstar Demo Markets Ltd and Cedar Demo Trading LLC. " +
  "Governing law: England and Wales. Termination notice: 60 days. Liability cap: fees paid in 6 months. " +
  "Confidentiality survives 5 years. Evidence marker: NORTHSTAR-SYNTHETIC-BETA.";
const lp =
  "SYNTHETIC LIQUIDITY PROVIDER AGREEMENT. Parties: Aurora Demo Exchange Ltd and Pine Demo Liquidity LLC. " +
  "Minimum quote availability: 95 percent. Termination notice: 45 days. Governing law: DIFC. " +
  "Evidence marker: AURORA-SYNTHETIC-GAMMA.";

fs.writeFileSync(
  path.join(outputDirectory, "client-agreement-v1.pdf"),
  pdfWithText(v1),
);
fs.writeFileSync(
  path.join(outputDirectory, "client-agreement-v2.pdf"),
  pdfWithText(v2),
);
fs.writeFileSync(
  path.join(outputDirectory, "image-only-diagnostic.pdf"),
  blankPdf(),
);
fs.writeFileSync(
  path.join(outputDirectory, "invalid-signature.pdf"),
  "This is intentionally not a PDF. It contains only synthetic test text.\n",
);
writeDocx(path.join(outputDirectory, "liquidity-provider-v1.docx"), lp);

console.log(`Synthetic agreement fixtures written to ${outputDirectory}`);

#!/usr/bin/env node

import fs from "node:fs";
import path from "node:path";
import process from "node:process";

const root = path.resolve(process.argv[2] ?? process.cwd());
const ignoredDirectories = new Set([
  ".git",
  ".next",
  ".pytest_cache",
  ".venv",
  ".worktrees",
  "artifacts",
  "dist",
  "node_modules",
  "test-results",
]);

function collectMarkdown(directory) {
  const files = [];
  for (const entry of fs.readdirSync(directory, { withFileTypes: true })) {
    if (entry.isDirectory() && ignoredDirectories.has(entry.name)) continue;
    const absolute = path.join(directory, entry.name);
    if (entry.isDirectory()) files.push(...collectMarkdown(absolute));
    else if (entry.isFile() && entry.name.endsWith(".md")) files.push(absolute);
  }
  return files;
}

function githubSlug(value) {
  return value
    .trim()
    .toLowerCase()
    .replace(/<[^>]+>/g, "")
    .replace(/[`*_~]/g, "")
    .replace(/[^\p{Letter}\p{Number}\s-]/gu, "")
    .replace(/\s+/g, "-")
    .replace(/-+/g, "-");
}

function anchorsFor(markdown) {
  const anchors = new Set();
  const counts = new Map();
  let fenced = false;
  for (const line of markdown.split("\n")) {
    if (/^\s*```/.test(line)) {
      fenced = !fenced;
      continue;
    }
    if (fenced) continue;
    const heading = line.match(/^#{1,6}\s+(.+?)\s*#*\s*$/);
    if (heading) {
      const base = githubSlug(heading[1]);
      const count = counts.get(base) ?? 0;
      anchors.add(count === 0 ? base : `${base}-${count}`);
      counts.set(base, count + 1);
    }
    for (const match of line.matchAll(/<a\s+(?:name|id)=["']([^"']+)["']/gi)) {
      anchors.add(match[1]);
    }
  }
  return anchors;
}

function linksFor(markdown) {
  const links = [];
  let fenced = false;
  for (const [index, line] of markdown.split("\n").entries()) {
    if (/^\s*```/.test(line)) {
      fenced = !fenced;
      continue;
    }
    if (fenced) continue;
    const prose = line.replace(/`+[^`]*`+/g, "");
    for (const match of prose.matchAll(/!?\[[^\]]*\]\(([^)]+)\)/g)) {
      let destination = match[1].trim();
      if (destination.startsWith("<") && destination.endsWith(">")) {
        destination = destination.slice(1, -1);
      }
      destination = destination.replace(/\s+["'][^"']*["']$/, "");
      links.push({ destination, line: index + 1 });
    }
  }
  return links;
}

function resolveTarget(source, destination) {
  const hashIndex = destination.indexOf("#");
  const filePart =
    hashIndex === -1 ? destination : destination.slice(0, hashIndex);
  const anchor =
    hashIndex === -1
      ? ""
      : decodeURIComponent(destination.slice(hashIndex + 1));
  const queryless = filePart.split("?", 1)[0];
  const target = queryless
    ? path.resolve(path.dirname(source), decodeURIComponent(queryless))
    : source;
  return { anchor, target };
}

const failures = [];
const markdownFiles = collectMarkdown(root);
const anchorCache = new Map();

for (const source of markdownFiles) {
  const markdown = fs.readFileSync(source, "utf8");
  for (const { destination, line } of linksFor(markdown)) {
    if (
      !destination ||
      /^(?:https?:|mailto:|tel:|data:)/i.test(destination) ||
      destination.includes("{{")
    ) {
      continue;
    }
    if (destination.startsWith("/")) {
      failures.push(
        `${path.relative(root, source)}:${line}: repository link must be relative: ${destination}`,
      );
      continue;
    }
    const { anchor, target } = resolveTarget(source, destination);
    let actualTarget = target;
    if (fs.existsSync(target) && fs.statSync(target).isDirectory()) {
      actualTarget = path.join(target, "README.md");
    }
    if (!fs.existsSync(actualTarget)) {
      failures.push(
        `${path.relative(root, source)}:${line}: missing target: ${destination}`,
      );
      continue;
    }
    if (anchor && actualTarget.endsWith(".md")) {
      let anchors = anchorCache.get(actualTarget);
      if (!anchors) {
        anchors = anchorsFor(fs.readFileSync(actualTarget, "utf8"));
        anchorCache.set(actualTarget, anchors);
      }
      if (!anchors.has(anchor)) {
        failures.push(
          `${path.relative(root, source)}:${line}: missing anchor #${anchor} in ${path.relative(root, actualTarget)}`,
        );
      }
    }
  }
}

const collectionPath = path.join(
  root,
  "docs/testing/insomnia/agreement-intelligence.yaml",
);
if (process.env.OPENAPI_URL && fs.existsSync(collectionPath)) {
  const response = await fetch(process.env.OPENAPI_URL);
  if (!response.ok) {
    failures.push(
      `OpenAPI fetch failed: ${response.status} ${process.env.OPENAPI_URL}`,
    );
  } else {
    const schema = await response.json();
    const paths = new Set(Object.keys(schema.paths ?? {}));
    const collection = fs.readFileSync(collectionPath, "utf8");
    for (const match of collection.matchAll(
      /^\s*url:\s*["']?([^"'\n]+)["']?\s*$/gm,
    )) {
      const raw = match[1].trim();
      if (!raw.includes("{{ _.base_url }}")) continue;
      const normalized = raw
        .replace("{{ _.base_url }}", "")
        .replace(/{{\s*_.([a-z0-9_]+)\s*}}/gi, "{$1}")
        .split("?", 1)[0];
      if (!paths.has(normalized)) {
        failures.push(
          `Insomnia request path is absent from OpenAPI: ${normalized}`,
        );
      }
    }
  }
}

if (failures.length > 0) {
  console.error(failures.join("\n"));
  process.exit(1);
}

console.log(
  `Documentation links pass (${markdownFiles.length} Markdown files).`,
);

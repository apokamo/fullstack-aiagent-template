#!/usr/bin/env node

const fs = require("node:fs");
const path = require("node:path");
const MarkdownIt = require("markdown-it");

const root = process.cwd();
const roots = ["docs", "designs", "evals-evidence", ".claude/skills"];
const individualFiles = [
  "README.md",
  "CONTRIBUTING.md",
  "AGENTS.md",
  "CLAUDE.md",
  "apps/web/AGENTS.md",
  "apps/web/CLAUDE.md",
];
const ignored = new Set([".git", ".next", ".venv", "node_modules", "test-artifacts"]);
const markdown = new MarkdownIt();
// anchor の収集では `<a id="...">` も拾うため HTML を token にする。
const anchorMarkdown = new MarkdownIt({ html: true });

// markdown-it normally percent-encodes malformed percent signs, making `%zz`
// indistinguishable from a valid literal percent (`%25zz`). Preserve the raw
// destination so the validator can classify encoding errors itself.
markdown.normalizeLink = (destination) => destination;

function markdownFiles(entry) {
  const absolute = path.join(root, entry);
  if (!fs.existsSync(absolute)) return [];
  const stat = fs.lstatSync(absolute);
  if (stat.isSymbolicLink()) return [];
  if (stat.isFile()) return absolute.endsWith(".md") ? [absolute] : [];
  return fs
    .readdirSync(absolute, { withFileTypes: true })
    .sort((left, right) => left.name.localeCompare(right.name))
    .flatMap((item) => {
      if (ignored.has(item.name)) return [];
      return markdownFiles(path.relative(root, path.join(absolute, item.name)));
    });
}

const files = [
  ...individualFiles.flatMap(markdownFiles),
  ...roots.flatMap(markdownFiles),
].sort();
const failures = [];
const anchorCache = new Map();

function recordFailure(file, target, reason) {
  failures.push(`${path.relative(root, file)}: ${target}: ${reason}`);
}

function localDestinations(content) {
  const tokens = markdown.parse(content, {});
  return tokens.flatMap((token) => {
    if (!token.children) return [];
    return token.children.flatMap((child) => {
      if (child.type === "link_open") return [child.attrGet("href")];
      if (child.type === "image") return [child.attrGet("src")];
      return [];
    });
  });
}

// GitHub が見出しに付ける id と同じ規則: 小文字化し、文字・数字・`_`・`-`・空白以外を
// 除き、空白を `-` にする。同じ slug が続くと `-1`、`-2` を付ける。
function githubSlug(text) {
  return text
    .toLowerCase()
    .replace(/[^\p{L}\p{M}\p{N}\p{Pc}\- ]/gu, "")
    .replace(/ /g, "-");
}

function headingText(inline) {
  return (inline.children || [])
    .filter((child) => child.type === "text" || child.type === "code_inline")
    .map((child) => child.content)
    .join("");
}

function anchorsOf(file) {
  if (anchorCache.has(file)) return anchorCache.get(file);
  const tokens = anchorMarkdown.parse(fs.readFileSync(file, "utf8"), {});
  const anchors = new Set();
  const seen = new Map();
  const htmlIds = /\s(?:id|name)\s*=\s*["']([^"']+)["']/g;
  tokens.forEach((token, index) => {
    if (token.type === "heading_open") {
      const base = githubSlug(headingText(tokens[index + 1]));
      const count = seen.get(base) || 0;
      seen.set(base, count + 1);
      anchors.add(count ? `${base}-${count}` : base);
    }
    const html = [token, ...(token.children || [])].filter((item) =>
      item.type.startsWith("html_"),
    );
    for (const item of html) {
      for (const match of item.content.matchAll(htmlIds)) anchors.add(match[1]);
    }
  });
  anchorCache.set(file, anchors);
  return anchors;
}

function validateAnchor(file, target, markdownFile, encodedFragment) {
  if (!encodedFragment || !markdownFile.endsWith(".md")) return;
  let fragment;
  try {
    fragment = decodeURIComponent(encodedFragment);
  } catch {
    recordFailure(file, target, "malformed percent encoding");
    return;
  }
  if (!anchorsOf(markdownFile).has(fragment)) {
    recordFailure(file, target, "missing anchor");
  }
}

function validateLocalTarget(file, target) {
  // 同じ文書内の fragment は markdownlint の MD051 が検査する。
  if (
    !target ||
    target.startsWith("#") ||
    target.startsWith("//") ||
    /^[a-z][a-z0-9+.-]*:/i.test(target)
  ) {
    return;
  }

  const suffixStarts = [target.indexOf("?"), target.indexOf("#")].filter(
    (index) => index !== -1,
  );
  const suffixStart = suffixStarts.length ? Math.min(...suffixStarts) : target.length;
  const encodedPath = target.slice(0, suffixStart);
  if (!encodedPath) return;

  if (encodedPath.startsWith("/")) {
    recordFailure(file, target, "repository-root absolute path is not allowed");
    return;
  }

  let decodedPath;
  try {
    decodedPath = decodeURIComponent(encodedPath);
  } catch {
    recordFailure(file, target, "malformed percent encoding");
    return;
  }

  const resolved = path.resolve(path.dirname(file), decodedPath);
  const relative = path.relative(root, resolved);
  const escapesRoot = relative === ".." || relative.startsWith(`..${path.sep}`);
  if (escapesRoot || path.isAbsolute(relative)) {
    recordFailure(file, target, "link escapes repository");
  } else if (!fs.existsSync(resolved)) {
    recordFailure(file, target, "missing target");
  } else if (fs.statSync(resolved).isFile()) {
    const hashIndex = target.indexOf("#");
    if (hashIndex !== -1)
      validateAnchor(file, target, resolved, target.slice(hashIndex + 1));
  }
}

for (const file of files) {
  try {
    const content = fs.readFileSync(file, "utf8");
    for (const target of localDestinations(content)) {
      try {
        validateLocalTarget(file, target);
      } catch (error) {
        const errorName = error instanceof Error ? error.name : "UnknownError";
        recordFailure(file, target, `validation failed (${errorName})`);
      }
    }
  } catch (error) {
    const errorName = error instanceof Error ? error.name : "UnknownError";
    recordFailure(file, "<document>", `Markdown scan failed (${errorName})`);
  }
}

if (failures.length) {
  console.error(failures.join("\n"));
  process.exit(1);
}

console.log(`checked ${files.length} Markdown files`);

// SPDX-License-Identifier: Apache-2.0
/** Documentation guards for docs/errors.md.
 *
 * These tests fail if a new exception is exported from the public API but is
 * not mentioned in the shared error reference, or if either package README
 * stops linking to it. */

import { describe, expect, it } from "vitest";
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { dirname, resolve } from "node:path";
import * as sdk from "./index.js";

const repoRoot = resolve(dirname(fileURLToPath(import.meta.url)), "..", "..", "..");
const docsFile = resolve(repoRoot, "docs", "errors.md");
const pythonReadme = resolve(repoRoot, "packages", "python-sdk", "README.md");
const tsReadme = resolve(repoRoot, "packages", "ts-sdk", "README.md");

function isErrorClass(value: unknown): value is new (...args: unknown[]) => Error {
  if (typeof value !== "function") {
    return false;
  }
  const ctor = value as () => unknown;
  let proto: unknown = ctor.prototype;
  while (proto) {
    if (proto === Error.prototype) {
      return true;
    }
    proto = Object.getPrototypeOf(proto);
  }
  return false;
}

const exportedErrors = Object.entries(sdk)
  .filter(([, value]) => isErrorClass(value))
  .map(([name]) => name)
  .sort();

describe("docs/errors.md", () => {
  it("exists and is linked from both package READMEs", () => {
    const docsContent = readFileSync(docsFile, "utf8");
    expect(docsContent.trim().length).toBeGreaterThan(0);

    expect(readFileSync(pythonReadme, "utf8")).toContain("docs/errors.md");
    expect(readFileSync(tsReadme, "utf8")).toContain("docs/errors.md");
  });

  it("documents every exported TypeScript exception", () => {
    const docsContent = readFileSync(docsFile, "utf8");
    const missing = exportedErrors.filter((name) => !docsContent.includes(name));
    expect(missing).toEqual([]);
  });
});

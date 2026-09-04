import { readdirSync, readFileSync, statSync } from "node:fs";
import { join } from "node:path";

import type { Variants } from "framer-motion";
import { describe, expect, it } from "vitest";

import * as motion from "@/lib/motion";
import { collapseSection } from "@/lib/motion";

const SRC = join(import.meta.dirname, "..");

function sourceFiles(dir: string): string[] {
  return readdirSync(dir).flatMap((entry) => {
    const path = join(dir, entry);
    if (statSync(path).isDirectory()) return sourceFiles(path);
    return /\.tsx?$/.test(path) && !/\.test\.tsx?$/.test(path) ? [path] : [];
  });
}

/** THE ONE RULE THIS FILE EXISTS FOR, and why it is a source scan rather than
 * a rendered assertion.
 *
 * In this stack (framer-motion 12 + React 19) an exit animation RUNS and then
 * never reports completion, so `AnimatePresence` never unmounts the subtree it
 * was given. Measured three separate times on three surfaces: a drawer left a
 * full-screen invisible backdrop swallowing every click, a filtered card list
 * kept the cards the filter had just excluded, and a hub panel stopped
 * updating after the second switch.
 *
 * None of that reproduces under jsdom, which has no compositor and settles
 * animations instantly -- so a rendering test would pass whether the wrapper
 * were there or not, and would be worse than no test at all: it would read as
 * proof. The rule is therefore pinned where it IS observable, in the source.
 * If a future upgrade fixes the underlying bug, delete this file deliberately
 * rather than let a wrapper drift back in.
 */
describe("no exit animations anywhere in this app", () => {
  it("mounts and unmounts outright -- nothing imports AnimatePresence", () => {
    const offenders = sourceFiles(SRC).filter((path) =>
      /^import[^;]*\bAnimatePresence\b[^;]*from "framer-motion";/m.test(readFileSync(path, "utf8")),
    );
    expect(offenders).toEqual([]);
  });

  it("ships no `exit` variant for one to drive", () => {
    // A dead `exit` key is an invitation to wire the wrapper back up, so the
    // shared vocabulary carries none -- including the one a factory builds.
    const sets: [string, Variants][] = [
      ...Object.entries(motion).filter(
        (entry): entry is [string, Variants] =>
          typeof entry[1] === "object" && entry[1] !== null,
      ),
      ["collapseSection(240)", collapseSection(240)],
    ];
    expect(sets.length).toBeGreaterThan(5);
    for (const [name, variants] of sets) {
      expect({ name, keys: Object.keys(variants) }).toEqual({
        name,
        keys: Object.keys(variants).filter((key) => key !== "exit"),
      });
    }
  });
});

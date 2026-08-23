"use client";

import * as echarts from "echarts";

/* ===========================================================================
 * Shared plumbing for the app's three ECharts geo maps (region-map, hub-map,
 * route-signal-map).
 *
 * The loader below was copy-pasted in two components before this file existed;
 * the third map made that a pattern rather than an accident. It has to be a
 * module-level singleton, not per-component state: `echarts.registerMap` is
 * global, and two components mounting at once would otherwise fetch and
 * register the same 455KB outline twice.
 * ======================================================================== */

// The world outline is fetched from /geo/world.json rather than imported.
// Importing it emitted a ~1MB JavaScript chunk that had to be parsed as code;
// as a plain asset it is 455KB, cached by the browser like any other file, and
// never touches the JS graph. Coordinates are rounded to 3 decimals (~110m),
// which is far below one pixel at these maps' zoom.
let mapPromise: Promise<void> | null = null;

/** Fetch and register the "world" map, once per page load. Safe to call from
 * every map component's mount effect. */
export function ensureWorldMap(): Promise<void> {
  if (!mapPromise) {
    mapPromise = fetch("/geo/world.json")
      .then((res) => res.json())
      .then((geoJson) => {
        echarts.registerMap("world", geoJson);
      })
      .catch(() => {
        mapPromise = null; // let a later mount retry
      });
  }
  return mapPromise;
}

// Marker *area*, not radius, tracks magnitude: a point with four times the
// count should look four times as big, and scaling the radius would make it
// sixteen. Magnitude is carried by size alone -- one hue throughout, so no map
// here needs a categorical palette or a legend of colors.
const MIN_SYMBOL = 7;
const MAX_SYMBOL = 26;

/** Area-proportional marker size for a scatter point. `max` is the largest
 * count in the series; `count` of 0 (or a degenerate max) floors at the
 * minimum so a zero-count marker is still visible and still clickable. */
export function symbolSize(count: number, max: number): number {
  if (max <= 0 || count <= 0) return MIN_SYMBOL;
  const area = (count / max) * (MAX_SYMBOL ** 2 - MIN_SYMBOL ** 2) + MIN_SYMBOL ** 2;
  return Math.sqrt(area);
}

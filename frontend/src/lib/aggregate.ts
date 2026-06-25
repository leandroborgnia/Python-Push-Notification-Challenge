// PURE per-UTC-hour aggregation for the personal dashboard (FR-030/031/033, research R7). Mirrors
// the backend's emailed-graph definition exactly: count every per-recipient delivery that reached
// `sent`, bucketed by the UTC hour of that transition. Counting is per delivery, not per dispatch.

import type { Dispatch } from "../api/types";

export interface HourAggregate {
  buckets: number[]; // length 24, index = UTC hour 00..23
  totalSent: number; // sum of buckets
  dispatchesScanned: number;
  mostRecentSentAt: string | null;
  capped: boolean; // true when the scan stopped at the cap (a recent window, not all-time)
}

/**
 * Aggregate the given dispatch pages. `capped` is supplied by the caller (the page knows whether the
 * scan stopped because it hit the dispatch cap rather than exhausting the history).
 */
export function aggregate(dispatches: Dispatch[], capped = false): HourAggregate {
  const buckets = new Array<number>(24).fill(0);
  let totalSent = 0;
  let mostRecentSentAt: string | null = null;
  let mostRecentMs = -Infinity;

  for (const dispatch of dispatches) {
    for (const delivery of dispatch.deliveries) {
      for (const transition of delivery.transitions) {
        if (transition.to_status !== "sent" || !transition.at) continue;
        const ms = Date.parse(transition.at);
        if (Number.isNaN(ms)) continue; // skip degenerate/unparseable timestamps
        buckets[new Date(ms).getUTCHours()] += 1;
        totalSent += 1;
        if (ms > mostRecentMs) {
          mostRecentMs = ms;
          mostRecentSentAt = transition.at;
        }
      }
    }
  }

  return { buckets, totalSent, dispatchesScanned: dispatches.length, mostRecentSentAt, capped };
}

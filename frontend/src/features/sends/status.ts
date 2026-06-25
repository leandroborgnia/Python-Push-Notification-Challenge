// Shared delivery-state presentation + the terminal-vs-in-progress rule that gates polling
// (data-model "Delivery lifecycle"): queued/sent are in-progress, delivered/failed are terminal.

import type { DeliveryState, Dispatch } from "../../api/types";

export const STATE_COLOR: Record<DeliveryState, string> = {
  queued: "default",
  sent: "processing",
  delivered: "success",
  failed: "error",
};

export const STATE_ORDER: DeliveryState[] = ["queued", "sent", "delivered", "failed"];

export function isTerminal(state: DeliveryState): boolean {
  return state === "delivered" || state === "failed";
}

/** True while any delivery in the dispatch is still progressing (drives the 4s poll). */
export function dispatchInProgress(dispatch: Dispatch): boolean {
  return dispatch.deliveries.some((d) => !isTerminal(d.status));
}

/** True while any dispatch in the list is still progressing. */
export function anyInProgress(dispatches: Dispatch[] | undefined): boolean {
  return Boolean(dispatches?.some(dispatchInProgress));
}

/** Count deliveries per state for the compact history-row summary. */
export function stateCounts(dispatch: Dispatch): Record<DeliveryState, number> {
  const counts: Record<DeliveryState, number> = { queued: 0, sent: 0, delivered: 0, failed: 0 };
  for (const d of dispatch.deliveries) counts[d.status] += 1;
  return counts;
}

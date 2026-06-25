import { describe, expect, it } from "vitest";

import type { Dispatch, Transition } from "../api/types";
import { aggregate } from "./aggregate";

let counter = 0;
const uid = () => `id-${counter++}`;

function sentTransition(at: string | null): Transition {
  return { from_status: "queued", to_status: "sent", reason: null, attempt: 1, at };
}

function dispatch(transitions: Transition[][]): Dispatch {
  return {
    dispatch_id: uid(),
    channel: "email",
    created_at: "2026-06-24T00:00:00Z",
    deliveries: transitions.map((ts) => ({
      delivery_id: uid(),
      recipient_name: "Ada",
      destination: "ada@x.com",
      status: "sent",
      failure_reason: null,
      transitions: ts,
    })),
  };
}

describe("aggregate", () => {
  it("buckets sent transitions by their UTC hour", () => {
    const result = aggregate([
      dispatch([[sentTransition("2026-06-24T09:30:00Z")]]),
      dispatch([[sentTransition("2026-06-24T09:59:59Z")]]),
      dispatch([[sentTransition("2026-06-24T23:00:00Z")]]),
    ]);
    expect(result.buckets[9]).toBe(2);
    expect(result.buckets[23]).toBe(1);
    expect(result.totalSent).toBe(3);
    expect(result.buckets).toHaveLength(24);
  });

  it("counts per delivery, not per dispatch", () => {
    // One dispatch, three recipients each reaching `sent` → three counted.
    const result = aggregate([
      dispatch([
        [sentTransition("2026-06-24T05:00:00Z")],
        [sentTransition("2026-06-24T05:10:00Z")],
        [sentTransition("2026-06-24T05:20:00Z")],
      ]),
    ]);
    expect(result.buckets[5]).toBe(3);
    expect(result.totalSent).toBe(3);
    expect(result.dispatchesScanned).toBe(1);
  });

  it("returns all-zero buckets when nothing reached sent", () => {
    const queuedOnly: Transition = {
      from_status: null,
      to_status: "queued",
      reason: null,
      attempt: null,
      at: "2026-06-24T10:00:00Z",
    };
    const result = aggregate([dispatch([[queuedOnly]])]);
    expect(result.totalSent).toBe(0);
    expect(result.buckets.every((b) => b === 0)).toBe(true);
    expect(result.mostRecentSentAt).toBeNull();
  });

  it("skips sent transitions with a null or unparseable `at`", () => {
    const result = aggregate([
      dispatch([[sentTransition(null)]]),
      dispatch([[sentTransition("not-a-date")]]),
      dispatch([[sentTransition("2026-06-24T07:00:00Z")]]),
    ]);
    expect(result.totalSent).toBe(1);
    expect(result.buckets[7]).toBe(1);
  });

  it("tracks the most recent sent timestamp regardless of input order", () => {
    const result = aggregate([
      dispatch([[sentTransition("2026-06-24T08:00:00Z")]]),
      dispatch([[sentTransition("2026-06-24T20:00:00Z")]]),
      dispatch([[sentTransition("2026-06-24T12:00:00Z")]]),
    ]);
    expect(result.mostRecentSentAt).toBe("2026-06-24T20:00:00Z");
  });

  it("reflects the caller-supplied capped flag and dispatch count", () => {
    const dispatches = [dispatch([[sentTransition("2026-06-24T01:00:00Z")]])];
    expect(aggregate(dispatches, true).capped).toBe(true);
    expect(aggregate(dispatches).capped).toBe(false);
    expect(aggregate(dispatches).dispatchesScanned).toBe(1);
  });
});

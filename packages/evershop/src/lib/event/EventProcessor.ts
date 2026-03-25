import { callSubscribers } from './callSubscibers.js';
import { debug, error } from '../log/logger.js';
import type { EventRow, EventStorage } from './EventStorage.js';

const BATCH_SIZE = 10;

type Subscriber = {
  event: string;
  subscriber: (data: unknown) => void | Promise<void>;
};

type EventProcessorDeps = {
  storage: Pick<EventStorage, 'claimBatch' | 'markDoneAndDelete'>;
  subscribers: Subscriber[];
};

/**
 * Pure event processing logic. Accepts storage and subscribers as dependencies
 * so both can be replaced with mocks in tests — no real DB or filesystem needed.
 */
export function createEventProcessor({
  storage,
  subscribers
}: EventProcessorDeps) {
  // Guard: prevents concurrent DB claim transactions while one is in-flight
  let isProcessing = false;

  async function executeSubscribers(event: EventRow): Promise<void> {
    try {
      const matchingSubscribers = subscribers
        .filter((s) => s.event === event.name)
        .map((s) => s.subscriber);
      await callSubscribers(matchingSubscribers, event.data);
    } catch (e) {
      error(e);
    } finally {
      try {
        await storage.markDoneAndDelete(event.uuid);
      } catch (e) {
        error(e);
      }
    }
  }

  async function loadAndProcess(): Promise<void> {
    if (isProcessing) return;
    isProcessing = true;
    try {
      let events: EventRow[];
      try {
        events = await storage.claimBatch(BATCH_SIZE);
      } catch (e) {
        error(e);
        return;
      }

      if (events.length === 0) return;

      debug(`Processing ${events.length} event(s)`);

      // Each event runs concurrently; errors are isolated per event
      events.forEach((event) => {
        executeSubscribers(event).catch((e) => error(e));
      });

      // Full batch — more rows likely waiting, schedule next claim immediately
      if (events.length === BATCH_SIZE) {
        setImmediate(() => loadAndProcess().catch((e) => error(e)));
      }
    } finally {
      // Reset before subscribers finish so new notifications can trigger
      // a fresh claim while current subscribers are still running
      isProcessing = false;
    }
  }

  return { loadAndProcess };
}

export function startSafePolling(handler, intervalMs, onError) {
  let inFlight = false;
  const timer = setInterval(async () => {
    if (inFlight) return;
    inFlight = true;
    try {
      const shouldStop = await handler();
      if (shouldStop) clearInterval(timer);
    } catch (e) {
      clearInterval(timer);
      if (onError) onError(e);
    } finally {
      inFlight = false;
    }
  }, intervalMs);
  return () => clearInterval(timer);
}


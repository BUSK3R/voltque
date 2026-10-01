import { createContext, useContext, useEffect, useState, type ReactNode } from "react";

import { STATION_ID, type Snapshot } from "../api";

interface Feed {
  snap: Snapshot | null;
  /** performance.now() when `snap` arrived, used to interpolate the simulation clock */
  at: number;
  connected: boolean;
}

const FeedContext = createContext<Feed>({ snap: null, at: 0, connected: false });

/** One WebSocket per page; reconnects with a 1 s backoff. Pushes arrive within ~0.5 s. */
export function FeedProvider({ children }: { children: ReactNode }) {
  const [state, setState] = useState<{ snap: Snapshot | null; at: number }>({ snap: null, at: 0 });
  const [connected, setConnected] = useState(false);

  useEffect(() => {
    let ws: WebSocket | null = null;
    let timer: number | undefined;
    let closed = false;

    const connect = () => {
      const proto = window.location.protocol === "https:" ? "wss" : "ws";
      ws = new WebSocket(`${proto}://${window.location.host}/api/ws/stations/${STATION_ID}`);
      ws.onopen = () => setConnected(true);
      ws.onmessage = (e: MessageEvent<string>) => {
        setState({ snap: JSON.parse(e.data) as Snapshot, at: performance.now() });
      };
      ws.onclose = () => {
        setConnected(false);
        if (!closed) timer = window.setTimeout(connect, 1000);
      };
    };
    connect();

    return () => {
      closed = true;
      window.clearTimeout(timer);
      ws?.close();
    };
  }, []);

  return (
    <FeedContext.Provider value={{ ...state, connected }}>{children}</FeedContext.Provider>
  );
}

export function useFeed(): Feed {
  return useContext(FeedContext);
}

/** Simulation clock in epoch ms, advancing smoothly at the simulator speed between pushes. */
export function useSimNow(): number {
  const { snap, at } = useFeed();
  const [, setTick] = useState(0);
  useEffect(() => {
    const id = window.setInterval(() => setTick((n) => n + 1), 250);
    return () => window.clearInterval(id);
  }, []);
  if (!snap) return Date.now();
  const base = Date.parse(snap.sim.now);
  return snap.sim.running ? base + (performance.now() - at) * snap.sim.speed : base;
}

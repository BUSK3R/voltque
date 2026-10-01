import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useRef,
  useState,
  type ReactNode,
} from "react";

import { api, ApiError, type Session } from "../api";
import { useFeed } from "../feed";
import { storeSessionId, storedSessionId } from "./store";

interface SessionCtx {
  id: number | null;
  session: Session | null;
  /** why the previous session ended without finishing (cancelled / no-show / unknown) */
  endedMessage: string | null;
  start: (id: number) => void;
  clear: () => void;
}

const Ctx = createContext<SessionCtx>({
  id: null,
  session: null,
  endedMessage: null,
  start: () => undefined,
  clear: () => undefined,
});

/** Follows my session on the server, so a page refresh restores everything. */
export function SessionProvider({ children }: { children: ReactNode }) {
  const { at } = useFeed();
  const [id, setId] = useState<number | null>(() => storedSessionId());
  const [session, setSession] = useState<Session | null>(null);
  const [endedMessage, setEndedMessage] = useState<string | null>(null);
  const busy = useRef(false);
  const missed = useRef(false); // a push arrived while a fetch was in flight
  const current = useRef(id); // id being followed now; a stale fetch must not resurrect a cleared session
  const [retry, setRetry] = useState(0);

  const clear = useCallback(() => {
    current.current = null;
    storeSessionId(null);
    setId(null);
    setSession(null);
  }, []);

  const start = useCallback((newId: number) => {
    current.current = newId;
    storeSessionId(newId);
    setEndedMessage(null);
    setSession(null);
    setId(newId);
  }, []);

  useEffect(() => {
    if (id === null) return;
    if (busy.current) {
      missed.current = true;
      return;
    }
    busy.current = true;
    api
      .session(id)
      .then((s) => {
        if (current.current !== id) return;
        if (s.status === "cancelled") {
          setEndedMessage("대기를 취소했습니다.");
          clear();
        } else if (s.status === "no_show") {
          setEndedMessage("호출 후 진입하지 않아 대기가 종료되었습니다. 다시 등록해 주세요.");
          clear();
        } else {
          setSession(s);
        }
      })
      .catch((e: unknown) => {
        if (current.current !== id) return;
        if (e instanceof ApiError && e.status === 404) {
          setEndedMessage("대기 정보를 찾을 수 없습니다. 시뮬레이션이 초기화되었을 수 있어요.");
          clear();
        }
      })
      .finally(() => {
        busy.current = false;
        if (missed.current) {
          missed.current = false;
          setRetry((n) => n + 1);
        }
      });
    // `at` changes with every push from the server
  }, [id, at, retry, clear]);

  return (
    <Ctx.Provider value={{ id, session, endedMessage, start, clear }}>{children}</Ctx.Provider>
  );
}

export function useMySession(): SessionCtx {
  return useContext(Ctx);
}

export function pathFor(status: Session["status"]): string {
  if (status === "charging") return "/m/charging";
  if (status === "done") return "/m/done";
  return "/m/queue";
}

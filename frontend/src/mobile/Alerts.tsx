import type { ReactElement } from "react";

import { useFeed, useSimNow } from "../feed";
import { hhmm, kw, mmss } from "./format";
import { useMySession } from "./session";
import { Banner } from "./ui";

/** In-app banners for D-05 (ending soon, called, no-show countdown) and D-06 (limit / delay reason). */
export function Alerts() {
  const { snap, connected } = useFeed();
  const { session } = useMySession();
  const now = useSimNow();
  const banners: ReactElement[] = [];

  if (!connected) {
    banners.push(
      <Banner key="conn" tone="danger" label="연결 끊김">
        서버와 다시 연결하는 중입니다.
      </Banner>,
    );
  } else if (snap && !snap.sim.running) {
    banners.push(
      <Banner key="sim" tone="info" label="정지">
        시뮬레이션이 멈춰 있어 시간이 흐르지 않습니다. 관제 화면에서 시작해 주세요.
      </Banner>,
    );
  }

  if (session) {
    if (session.status === "called" && session.no_show_at) {
      const left = Date.parse(session.no_show_at) - now;
      banners.push(
        <Banner key="called" tone="warn" label="호출">
          충전기 {session.charger_id}번으로 진입해 주세요. 미진입 시 대기 맨 뒤로 이동합니다 · 유예{" "}
          <b className="tabular-nums">{mmss(left)}</b>
        </Banner>,
      );
    }
    if (session.status === "waiting" && session.no_show_count > 0) {
      banners.push(
        <Banner key="noshow" tone="warn" label="순번 조정">
          호출 후 진입하지 않아 대기 맨 뒤로 이동했습니다. (한 번 더 놓치면 대기가 종료됩니다)
        </Banner>,
      );
    }
    if (session.status === "waiting" && session.notice) {
      banners.push(
        <Banner key="delay" tone="warn" label="시작 지연">
          {session.notice}
          {session.resume_at && <> 예상 시작 {hhmm(session.resume_at)}.</>}
        </Banner>,
      );
    }
    if ((session.status === "called" || session.status === "charging") && session.alloc_kw) {
      banners.push(
        <Banner key="limit" tone="warn" label="출력 제한">
          {session.notice ?? `충전소 부하 보호를 위해 출력을 ${kw(session.alloc_kw)}로 제한합니다.`}
          {session.planned_end && <> 새 예상 종료 {hhmm(session.planned_end)}.</>}
        </Banner>,
      );
    }
    if (session.status === "done" && session.parked) {
      banners.push(
        session.nudged_at ? (
          <Banner key="nudge" tone="warn" label="이동 요청">
            관제에서 차량 이동을 요청했습니다. 다음 대기 차량이 기다리고 있어요.
          </Banner>
        ) : (
          <Banner key="parked" tone="info" label="충전 완료">
            충전이 끝났습니다. 차량을 이동해 주세요.
          </Banner>
        ),
      );
    }
    if (session.status === "charging" && session.planned_end) {
      const left = Date.parse(session.planned_end) - now;
      if (left <= 5 * 60_000) {
        banners.push(
          <Banner key="soon" tone="ok" label="곧 완료">
            약 {Math.max(0, Math.ceil(left / 60_000))}분 뒤 충전이 끝납니다. 이동 준비를 해 주세요.
          </Banner>,
        );
      }
    }
  }

  if (banners.length === 0) return null;
  return <div className="space-y-2">{banners}</div>;
}

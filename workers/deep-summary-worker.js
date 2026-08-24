/**
 * 심화요약 트리거 릴레이 (Cloudflare Worker)
 *
 * 역할: 노션 "Open link" 버튼(브라우저 GET)을 받아
 *       클로드 루틴의 API 트리거로 POST를 쏴주는 변환기.
 *       노션 무료 플랜은 버튼에서 직접 외부 POST(Send webhook)를 못 쓰므로
 *       "GET으로 열기 → 여기서 POST로 변환"하는 얇은 다리 역할만 한다.
 *
 * 흐름:
 *   노션 버튼(Open link) → GET https://<worker>.workers.dev/?key=XXXX
 *     → Worker가 클로드 루틴 API 트리거 URL로 POST
 *     → 사용자에겐 "요청 전송됨" 안내 페이지 반환
 *
 * 배포:
 *   1) https://dash.cloudflare.com → Workers & Pages → Create → Worker
 *   2) 이 파일 내용을 붙여넣고 Deploy
 *   3) Settings → Variables and Secrets 에 아래 3개를 "Secret"으로 추가
 *        TRIGGER_URL    : 클로드 루틴 API 트리거 URL (루틴 생성 시 발급)
 *        TRIGGER_SECRET : (선택) 트리거 URL이 헤더 인증을 요구하면 그 토큰. 없으면 빈 값
 *        BUTTON_KEY     : 아무 임의 문자열. 노션 버튼 URL의 ?key= 값과 똑같이 맞춤
 *                         (아무나 워커 주소를 눌러 루틴을 깨우는 걸 막는 최소 자물쇠)
 *   4) 배포된 주소(예: https://deep-summary.<계정>.workers.dev)에 ?key=<BUTTON_KEY> 를 붙여
 *      노션 버튼의 Open link 대상으로 넣는다.
 */

export default {
  async fetch(request, env) {
    const url = new URL(request.url);

    // 0) 최소 자물쇠: ?key= 가 BUTTON_KEY와 일치해야 동작
    if (env.BUTTON_KEY && url.searchParams.get("key") !== env.BUTTON_KEY) {
      return htmlResponse("❌ 잘못된 키입니다.", 403);
    }

    if (!env.TRIGGER_URL) {
      return htmlResponse("⚙️ TRIGGER_URL이 설정되지 않았습니다. Worker 환경변수를 확인하세요.", 500);
    }

    // 0.5) 중복 발사 방지(디바운스)
    // 브라우저/노션이 같은 URL을 짧은 시간에 두 번 요청해도 트리거는 한 번만 쏜다.
    // 별도 설정 없이 Cloudflare 엣지 캐시를 마커로 사용(기본 30초).
    const debounceSec = Number(env.DEBOUNCE_SECONDS || 30);
    const cache = caches.default;
    const debounceKey = new Request("https://debounce.deep-summary/last");
    if (await cache.match(debounceKey)) {
      return htmlResponse(
        "⏳ 방금 요청을 보냈습니다.<br>중복 방지를 위해 이번 클릭은 건너뜁니다. 이미 처리 중이니 잠시만 기다리세요."
      );
    }
    await cache.put(
      debounceKey,
      new Response("1", { headers: { "Cache-Control": `max-age=${debounceSec}` } })
    );

    // 1) 클로드 루틴 API 트리거로 POST 변환
    const headers = {
      "Content-Type": "application/json",
      // 트리거 엔드포인트(Anthropic)가 요구하는 버전 헤더
      "anthropic-version": "2023-06-01",
    };
    if (env.TRIGGER_SECRET) {
      headers["Authorization"] = `Bearer ${env.TRIGGER_SECRET}`;
    }

    const payload = {
      source: "notion-deep-summary-button",
      requested_at: new Date().toISOString(),
      // 참고용 신호일 뿐, 루틴은 이 값에 의존하지 않고 노션에서 체크된 행을 직접 읽는다.
      note: "심화요약요청=체크된 행을 모두 처리하라",
    };

    try {
      const resp = await fetch(env.TRIGGER_URL, {
        method: "POST",
        headers,
        body: JSON.stringify(payload),
      });

      if (!resp.ok) {
        const text = await resp.text().catch(() => "");
        return htmlResponse(
          `⚠️ 트리거 전송 실패 (HTTP ${resp.status}). 잠시 후 다시 시도하세요.<br><small>${escapeHtml(text).slice(0, 300)}</small>`,
          502
        );
      }
    } catch (e) {
      return htmlResponse(`⚠️ 트리거 전송 중 오류: ${escapeHtml(String(e))}`, 502);
    }

    // 2) 사용자 안내 페이지
    return htmlResponse(
      "✅ 심화요약 요청을 보냈습니다.<br>체크해 둔 기사들이 곧 처리됩니다. 이 탭은 닫고 노션으로 돌아가세요."
    );
  },
};

function htmlResponse(message, status = 200) {
  const body = `<!doctype html>
<html lang="ko"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>심화요약 요청</title>
<style>
  body{font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif;
       display:flex;align-items:center;justify-content:center;height:100vh;margin:0;
       background:#fafafa;color:#222}
  .card{max-width:480px;padding:32px 36px;background:#fff;border-radius:16px;
        box-shadow:0 4px 24px rgba(0,0,0,.08);font-size:17px;line-height:1.6;text-align:center}
</style></head>
<body><div class="card">${message}</div></body></html>`;
  return new Response(body, {
    status,
    headers: { "Content-Type": "text/html; charset=utf-8" },
  });
}

function escapeHtml(s) {
  return s.replace(/[&<>"']/g, (c) => (
    { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]
  ));
}

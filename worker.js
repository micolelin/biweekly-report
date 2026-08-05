/**
 * 報告頁的存取保護。
 *
 * Cloudflare Zero Trust 的免費方案要求綁定付款方式，本專案原則是只用免費且
 * 不需付款資訊的方案，因此改由 Worker 自己擋：用瀏覽器內建的 Basic 認證，
 * 主管點連結會跳出帳號密碼框，不需要註冊任何帳號。
 *
 * 帳號密碼存在 Cloudflare 的 Secret（REPORT_USER / REPORT_PASSWORD），
 * 不會進入版控。
 *
 * 重要：wrangler.jsonc 必須設 assets.run_worker_first = true，
 * 否則 Cloudflare 會先送靜態檔案而完全不執行這段程式碼 —— 那樣密碼等於沒設，
 * 而且從外面看不出來，是最危險的那種失效。
 */

const REALM = '雙週工作報告';

export default {
  async fetch(request, env) {
    if (!isAuthorized(request, env)) {
      return new Response('需要帳號密碼才能檢視這份報告。\n', {
        status: 401,
        headers: {
          'WWW-Authenticate': `Basic realm="${REALM}", charset="UTF-8"`,
          'Content-Type': 'text/plain; charset=utf-8',
          'Cache-Control': 'no-store',
        },
      });
    }

    const response = await env.ASSETS.fetch(request);
    const headers = new Headers(response.headers);
    // 報告內容不該被中介伺服器或搜尋引擎留存
    headers.set('Cache-Control', 'no-store');
    headers.set('X-Robots-Tag', 'noindex, nofollow');
    return new Response(response.body, {
      status: response.status,
      statusText: response.statusText,
      headers,
    });
  },
};

function isAuthorized(request, env) {
  const user = env.REPORT_USER;
  const password = env.REPORT_PASSWORD;

  // 沒設定密碼就一律拒絕。寧可打不開，也不要在「以為有保護」的狀態下
  // 把公司內部報告公開在網路上。
  if (!user || !password) return false;

  const header = request.headers.get('Authorization') || '';
  if (!header.startsWith('Basic ')) return false;

  let decoded;
  try {
    decoded = atob(header.slice(6));
  } catch {
    return false;
  }

  const separator = decoded.indexOf(':');
  if (separator < 0) return false;

  return (
    safeEqual(decoded.slice(0, separator), user) &&
    safeEqual(decoded.slice(separator + 1), password)
  );
}

/** 固定時間比對，避免從回應時間反推密碼。 */
function safeEqual(a, b) {
  if (a.length !== b.length) return false;
  let diff = 0;
  for (let i = 0; i < a.length; i += 1) {
    diff |= a.charCodeAt(i) ^ b.charCodeAt(i);
  }
  return diff === 0;
}

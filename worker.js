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

const REALM = 'Biweekly Work Report';

/** 每次改動 worker.js 都要加一。整合測試用它確認新版本已經部署完成。 */
const API_VERSION = 7;

export default {
  async fetch(request, env) {
    if (!isAuthorized(request, env)) {
      return new Response('Authentication required to view this report.\n', {
        status: 401,
        headers: {
          'WWW-Authenticate': `Basic realm="${REALM}", charset="UTF-8"`,
          'Content-Type': 'text/plain; charset=utf-8',
          'Cache-Control': 'no-store',
        },
      });
    }

    // 認證通過才進路由，API 因此與頁面共用同一道密碼保護
    const url = new URL(request.url);
    if (url.pathname.startsWith('/api/')) {
      return handleApi(request, env, url);
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

// ===== API 路由 =====

/** 統一的 JSON 回應格式，所有 API 回應都經過這裡。 */
function jsonResponse(payload, status = 200) {
  return new Response(JSON.stringify(payload), {
    status,
    headers: {
      'Content-Type': 'application/json; charset=utf-8',
      'Cache-Control': 'no-store',
    },
  });
}

async function handleApi(request, env, url) {
  if (url.pathname === '/api/version') {
    return jsonResponse({ version: API_VERSION });
  }

  if (url.pathname === '/api/table') {
    // 缺任何一個 Secret 都直接拒絕。用預設值硬跑會在「看起來正常」的狀態下
    // 產生解不開的資料，比直接壞掉更難發現。
    if (!env.GH_TOKEN) return jsonResponse({ error: '伺服器未設定 GH_TOKEN' }, 500);
    if (!env.TABLE_KEY) return jsonResponse({ error: '伺服器未設定 TABLE_KEY' }, 500);

    const slot = slotName(url);
    // hasOwnProperty 才是真的查白名單本身；一般的 [] 存取會沿原型鏈往上找，
    // slot=constructor / toString 這類名稱會拿到 Object.prototype 上的東西，
    // 讓白名單形同虛設。
    if (!Object.prototype.hasOwnProperty.call(SLOT_FILES, slot)) {
      return jsonResponse({ error: `不合法的 slot：${slot}` }, 400);
    }
    const path = SLOT_FILES[slot];

    if (request.method === 'GET') return handleGetTable(env, path);
    if (request.method === 'PUT') return handlePutTable(request, env, path);
    if (request.method === 'DELETE') {
      // 刪除只是測試用的工具，正式資料一律不給刪
      if (slot !== 'test') {
        return jsonResponse({ error: '正式資料不提供刪除。' }, 405);
      }
      try {
        await deleteFile(env, path);
        return jsonResponse({ deleted: true });
      } catch (error) {
        return jsonResponse({ error: error.message }, 502);
      }
    }
    return jsonResponse({ error: `不支援的方法：${request.method}` }, 405);
  }

  return jsonResponse({ error: `沒有這個端點：${url.pathname}` }, 404);
}

// ===== /api/table：讀表格 =====

function emptyTable() {
  return { v: 1, updated: null, rows: [] };
}

async function handleGetTable(env, path) {
  let file;
  try {
    file = await readFile(env, path);
  } catch (error) {
    return jsonResponse({ error: error.message }, 502);
  }

  if (file.text === null) {
    return jsonResponse({ data: emptyTable(), sha: null });
  }

  let envelope;
  try {
    envelope = JSON.parse(file.text);
  } catch (error) {
    // 檔案內容本身壞掉（不是合法 JSON），跟密碼對不對無關，訊息要分開講，
    // 不然會讓人跑去查一個其實沒問題的 TABLE_KEY。
    return jsonResponse(
      { error: `資料檔內容不是合法的 JSON，資料未被更動：${error.message}` },
      500,
    );
  }

  try {
    const data = await decryptJson(envelope, env.TABLE_KEY);
    return jsonResponse({ data, sha: file.sha });
  } catch (error) {
    // 絕不能在這裡回空表。回空表會讓人以為資料被清掉，接著一存就真的清掉了。
    if (error.iterTooHigh) {
      // 疊代數超標是這支檔案本身的問題，不是 TABLE_KEY 的問題——
      // 不要套用下面那句會把人導去查 TABLE_KEY 的通用訊息。
      return jsonResponse({ error: error.message }, 500);
    }
    return jsonResponse(
      { error: `解密失敗，資料未被更動。請確認 TABLE_KEY 是否正確：${error.message}` },
      500,
    );
  }
}

// ===== /api/table：寫表格 =====

/** 台北時間，格式 2026-08-06T18:00:00+08:00。 */
function taipeiNow() {
  const shifted = new Date(Date.now() + 8 * 60 * 60 * 1000);
  return `${shifted.toISOString().slice(0, 19)}+08:00`;
}

async function handlePutTable(request, env, path) {
  let body;
  try {
    body = await request.json();
  } catch {
    return jsonResponse({ error: '送出的內容不是合法的 JSON。' }, 400);
  }

  const rows = body?.data?.rows;
  if (!Array.isArray(rows)) {
    return jsonResponse({ error: 'data.rows 必須是陣列。' }, 400);
  }

  // updated 由伺服器決定。瀏覽器的時鐘不可信，而且不同裝置會不一致。
  const data = { v: 1, updated: taipeiNow(), rows };

  try {
    const envelope = await encryptJson(data, env.TABLE_KEY);
    const result = await writeFile(
      env,
      path,
      JSON.stringify(envelope),
      body.sha ?? null,
      `chore(table): 更新專案追蹤表 ${data.updated}`,
    );
    return jsonResponse({ sha: result.sha, updated: data.updated });
  } catch (error) {
    if (error.conflict) return jsonResponse({ error: error.message }, 409);
    return jsonResponse({ error: error.message }, 502);
  }
}

// ===== 加解密 =====
//
// 規格必須與 m-agent/codelist/dashboard/crypto.py 完全一致，
// 這樣同一份密文兩邊都解得開。改動任一邊都要一起改。

const CRYPTO_VERSION = 1;
const KDF_NAME = 'PBKDF2-SHA256';
// Cloudflare Workers 的 PBKDF2 實作硬性限制最多 100000 次疊代，
// 超過會直接丟錯（'Pbkdf2 failed: iteration counts above 100000 are not
// supported'），不是這裡能調的效能問題，是平台上限。
// m-agent/codelist/dashboard/crypto.py 的預設仍是 300000，兩邊不需要一致：
// 解密時雙方都是讀封包裡的 iter 欄位重新算 key（不是各自的常數），
// 所以只要封包忠實記錄加密當下用的疊代次數，兩邊互解就不受影響。
const KDF_ITERATIONS = 100000;
const SALT_BYTES = 16;
const IV_BYTES = 12;

function toBase64(bytes) {
  let binary = '';
  for (const byte of bytes) binary += String.fromCharCode(byte);
  return btoa(binary);
}

function fromBase64(text) {
  const binary = atob(text);
  const bytes = new Uint8Array(binary.length);
  for (let i = 0; i < binary.length; i += 1) bytes[i] = binary.charCodeAt(i);
  return bytes;
}

async function deriveKey(passphrase, salt, iterations) {
  const material = await crypto.subtle.importKey(
    'raw',
    new TextEncoder().encode(passphrase),
    'PBKDF2',
    false,
    ['deriveKey'],
  );
  return crypto.subtle.deriveKey(
    { name: 'PBKDF2', salt, iterations, hash: 'SHA-256' },
    material,
    { name: 'AES-GCM', length: 256 },
    false,
    ['encrypt', 'decrypt'],
  );
}

async function encryptJson(payload, passphrase) {
  // salt 與 iv 每次都重新產生。重複使用 iv 會讓 AES-GCM 的保護整個失效。
  const salt = crypto.getRandomValues(new Uint8Array(SALT_BYTES));
  const iv = crypto.getRandomValues(new Uint8Array(IV_BYTES));
  const key = await deriveKey(passphrase, salt, KDF_ITERATIONS);
  const plaintext = new TextEncoder().encode(JSON.stringify(payload));
  const ciphertext = await crypto.subtle.encrypt({ name: 'AES-GCM', iv }, key, plaintext);

  return {
    v: CRYPTO_VERSION,
    kdf: KDF_NAME,
    iter: KDF_ITERATIONS,
    salt: toBase64(salt),
    iv: toBase64(iv),
    ct: toBase64(new Uint8Array(ciphertext)),
  };
}

async function decryptJson(envelope, passphrase) {
  if (envelope.v !== CRYPTO_VERSION) {
    throw new Error(`不支援的封包版本：${envelope.v}`);
  }
  if (envelope.iter > KDF_ITERATIONS) {
    // 不能直接丟給 deriveKey：Cloudflare 的 PBKDF2 實作遇到超過上限的疊代數
    // 會丟一個看起來像平台故障的錯誤，跟金鑰對不對完全無關，卻很容易被誤
    // 認成 TABLE_KEY 設錯。多半是用 m-agent 的 crypto.py（預設 300000 次）
    // 重新加密了這個檔案，這裡先攔下來，講清楚是疊代數的問題。
    const error = new Error(
      `這份檔案的疊代次數（${envelope.iter}）超過 Cloudflare Workers 的上限 ` +
        `${KDF_ITERATIONS}，無法在這裡解密，與 TABLE_KEY 是否正確無關。若是用 ` +
        `crypto.py 重新加密的，請把疊代次數改成 ${KDF_ITERATIONS} 再重新加密一次。`,
    );
    error.iterTooHigh = true;
    throw error;
  }
  const key = await deriveKey(passphrase, fromBase64(envelope.salt), envelope.iter);
  const plaintext = await crypto.subtle.decrypt(
    { name: 'AES-GCM', iv: fromBase64(envelope.iv) },
    key,
    fromBase64(envelope.ct),
  );
  return JSON.parse(new TextDecoder().decode(plaintext));
}

// ===== GitHub 儲存 =====

const REPO = 'micolelin/biweekly-report';
const DATA_BRANCH = 'data';
// slot 直接參與檔名，所以用白名單而不是過濾字元 —— 白名單不會有漏網之魚
const SLOT_FILES = {
  main: 'table.enc.json',
  test: 'table.test.enc.json',
};

function slotName(url) {
  return url.searchParams.get('slot') || 'main';
}

function githubHeaders(env) {
  return {
    Authorization: `Bearer ${env.GH_TOKEN}`,
    Accept: 'application/vnd.github+json',
    // GitHub API 沒有 User-Agent 會直接拒絕
    'User-Agent': 'biweekly-report-worker',
    'Content-Type': 'application/json',
  };
}

/** readFile／writeFile／deleteFile 共用的 GitHub Contents API 端點組法。 */
function contentsUrl(path) {
  return `https://api.github.com/repos/${REPO}/contents/${path}`;
}

async function readFile(env, path) {
  const response = await fetch(`${contentsUrl(path)}?ref=${DATA_BRANCH}`, {
    headers: githubHeaders(env),
  });

  // 404 代表還沒有這個檔案，是第一次使用的正常狀況，不是錯誤
  if (response.status === 404) return { text: null, sha: null };
  if (!response.ok) {
    throw new Error(`讀取 GitHub 失敗（HTTP ${response.status}）：${await response.text()}`);
  }

  const body = await response.json();
  // GitHub 回的 base64 含換行，atob 不接受，要先清掉
  const raw = fromBase64(body.content.replace(/\n/g, ''));
  return { text: new TextDecoder().decode(raw), sha: body.sha };
}

async function writeFile(env, path, text, sha, message) {
  const payload = {
    message,
    content: toBase64(new TextEncoder().encode(text)),
    branch: DATA_BRANCH,
  };
  // 沒有 sha 代表建立新檔。帶著 null 送出去 GitHub 會拒絕，所以只在有值時放進去。
  if (sha) payload.sha = sha;

  const response = await fetch(contentsUrl(path), {
    method: 'PUT',
    headers: githubHeaders(env),
    body: JSON.stringify(payload),
  });

  // 409 是 sha 對不上，422 是「檔案已存在但沒給 sha」。兩者都代表同一件事：
  // 這份資料在別的地方被改過了。
  if (response.status === 409 || response.status === 422) {
    // 順序很重要：使用者這時候螢幕上還留著剛打的字，訊息要先講「存起來」
    // 再講「重新整理」——顛倒過來的話，使用者照著做就等於自己把還沒送出去
    // 的內容洗掉，跟這支檢查原本要保護的東西正好相反。
    const error = new Error(
      '這份資料在別的地方被改過了。請先把你剛改的內容複製起來，再重新整理頁面，貼回去後再存一次。',
    );
    error.conflict = true;
    throw error;
  }
  if (!response.ok) {
    throw new Error(`寫入 GitHub 失敗（HTTP ${response.status}）：${await response.text()}`);
  }

  const body = await response.json();
  return { sha: body.content.sha };
}

async function deleteFile(env, path) {
  const file = await readFile(env, path);
  if (file.sha === null) return; // 本來就沒有，視為已達成目標

  const response = await fetch(contentsUrl(path), {
    method: 'DELETE',
    headers: githubHeaders(env),
    body: JSON.stringify({
      message: 'chore(table): 清除測試資料',
      sha: file.sha,
      branch: DATA_BRANCH,
    }),
  });
  if (!response.ok) {
    throw new Error(`刪除 GitHub 檔案失敗（HTTP ${response.status}）：${await response.text()}`);
  }
}

/**
 * 讀出所有可用的帳號密碼。
 *
 * 兩種來源，可以並存：
 *   REPORT_USER / REPORT_PASSWORD  單一組（最早的設定方式，繼續支援）
 *   REPORT_ACCOUNTS               多組，一行一組，格式 帳號:密碼
 *
 * 分開發帳號的好處是可以單獨停用某一組 —— 例如同事離職，
 * 直接把那一行刪掉即可，主管那組不受影響、也不用通知他改密碼。
 */
function readAccounts(env) {
  const accounts = [];

  if (env.REPORT_USER && env.REPORT_PASSWORD) {
    accounts.push([env.REPORT_USER, env.REPORT_PASSWORD]);
  }

  for (const line of (env.REPORT_ACCOUNTS || '').split('\n')) {
    const trimmed = line.trim();
    if (!trimmed || trimmed.startsWith('#')) continue;
    const separator = trimmed.indexOf(':');
    if (separator < 1) continue;
    const user = trimmed.slice(0, separator).trim();
    const password = trimmed.slice(separator + 1).trim();
    if (user && password) accounts.push([user, password]);
  }

  return accounts;
}

function isAuthorized(request, env) {
  const accounts = readAccounts(env);

  // 一組帳號都沒設就一律拒絕。寧可打不開，也不要在「以為有保護」的狀態下
  // 把公司內部報告公開在網路上。
  if (accounts.length === 0) return false;

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

  const user = decoded.slice(0, separator);
  const password = decoded.slice(separator + 1);

  // 不提早跳出，全部比對完才回傳，避免從回應時間看出哪個帳號存在
  let matched = false;
  for (const [validUser, validPassword] of accounts) {
    if (safeEqual(user, validUser) && safeEqual(password, validPassword)) {
      matched = true;
    }
  }
  return matched;
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

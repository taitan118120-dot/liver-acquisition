/* ==========================================================================
   TAITAN PRO LP 共通計測タグ（GA4 / Google広告 / GTM）
   beginner・agency・liver・sidejob の全LPがこの1ファイルを読み込む。

   ■ GA4を有効にする手順
     下の GA4_ID に測定ID（G-から始まる文字列）を入れて push するだけ。
     GA4管理画面 > 管理 > データストリーム > 該当ストリーム で確認できる。
     空のままでも Google広告のコンバージョン計測は従来どおり動く。

   ■ このファイルがやること
     1. gtag.js の読み込みと config（GA4 + Google広告）
     2. 流入元（utm / gclid / リファラ）の初回接触を sessionStorage に保存
     3. LINEボタンのクリックを
        - GA4     : line_cta_click イベント（どのボタンか + 流入元つき）
        - Google広告 : conversion イベント（遷移前に送信完了を待つ）
        - GTM     : dataLayer への push
        の3系統に送る

   ■ 触るときの注意
     Google広告のCVは「クリック」計測なので、LINEへ遷移する前に送信が
     完了している必要がある。同一タブでそのまま lin.ee へ飛ぶと送信が
     中断されて計上されないため、Google公式のクリック用スニペットと同じく
     「遷移を一旦止める → 送信完了(event_callback)で遷移」方式にしている。
     送信が詰まっても必ず遷移するよう1秒のフォールバックを入れている。
     ここを外すとCVが取れなくなるので、変更したら必ず実クリックで検証すること。
   ========================================================================== */

(function () {
  'use strict';

  /* ================== ここだけ書き換える ================== */
  var GA4_ID = '';                            // 例: 'G-XXXXXXXXXX'（未発行なので空）
  var ADS_ID = 'AW-429748464';                // Google広告のコンバージョンID
  var ADS_CV_LABEL = '-KwzCJvzmNQcEPDh9cwB';  // 同「LINE_ボタンクリック」のラベル
  /* ======================================================== */

  var ADS_NAV_FALLBACK_MS = 1000;
  var SOURCE_STORAGE_KEY = 'taitan_traffic_src';

  // 他スクリプトや検証から参照できるよう公開しておく（従来の互換維持）
  var cfg = window.TAITAN_TRACKING = {
    GA4_ID: GA4_ID,
    ADS_ID: ADS_ID,
    ADS_CV_LABEL: ADS_CV_LABEL
  };

  /* ---------------- gtag.js の読み込み ----------------
     IDが1つも無いときは読み込まない（誤ったIDでの計測事故を防ぐため）。 */
  var ids = [cfg.GA4_ID, cfg.ADS_ID].filter(Boolean);

  if (ids.length) {
    window.dataLayer = window.dataLayer || [];
    window.gtag = function () { window.dataLayer.push(arguments); };
    window.gtag('js', new Date());
    ids.forEach(function (id) { window.gtag('config', id); });

    var s = document.createElement('script');
    s.async = true;
    s.src = 'https://www.googletagmanager.com/gtag/js?id=' + encodeURIComponent(ids[0]);
    document.head.appendChild(s);
  }

  /* ---------------- 流入元の判定 ----------------
     utm があればそれを正とする。無い場合は gclid とリファラから推定する。
     セッション内で最初に着地したときの値を保持し、ページ内回遊や
     ハッシュ遷移で 'direct' に上書きされないようにする。 */

  function queryParams() {
    var out = {};
    var q = window.location.search.replace(/^\?/, '');

    // アンカー付きURL（サイトリンクの /beginner/#faq など）に広告側で
    // パラメータが足されると `#faq?utm_source=...` の形で来ることがある。
    // その場合クエリは location.search に入らないのでハッシュ側からも拾う。
    var hashQuery = window.location.hash.indexOf('?');
    if (hashQuery > -1) {
      q = q ? q + '&' + window.location.hash.slice(hashQuery + 1)
            : window.location.hash.slice(hashQuery + 1);
    }

    if (!q) return out;
    q.split('&').forEach(function (pair) {
      if (!pair) return;
      var i = pair.indexOf('=');
      var k = i < 0 ? pair : pair.slice(0, i);
      var v = i < 0 ? '' : pair.slice(i + 1);
      try {
        out[decodeURIComponent(k.replace(/\+/g, ' '))] =
          decodeURIComponent(v.replace(/\+/g, ' '));
      } catch (err) { /* 壊れたエンコードは無視 */ }
    });
    return out;
  }

  // utm が無い流入をリファラのホスト名から推定する。
  // 媒体側にutmを付けられない導線（IGプロフィール等）の取りこぼしを減らすための保険で、
  // 正確な媒体別集計はあくまで utm 付きURLで行う（設計は ads/utm設計.md）。
  var REFERRER_MAP = [
    { test: /(^|\.)note\.com$/,               source: 'note',      medium: 'referral' },
    { test: /(^|\.)threads\.(net|com)$/,      source: 'threads',   medium: 'social' },
    { test: /(^|\.)instagram\.com$/,          source: 'instagram', medium: 'social' },
    { test: /^l\.instagram\.com$/,            source: 'instagram', medium: 'social' },
    { test: /(^|\.)(twitter\.com|x\.com)$/,   source: 'x',         medium: 'social' },
    { test: /^t\.co$/,                        source: 'x',         medium: 'social' },
    { test: /(^|\.)(line\.me|lin\.ee)$/,      source: 'line',      medium: 'social' },
    { test: /(^|\.)youtube\.com$/,            source: 'youtube',   medium: 'social' },
    { test: /(^|\.)tiktok\.com$/,             source: 'tiktok',    medium: 'social' },
    { test: /(^|\.)google\.[a-z.]+$/,         source: 'google',    medium: 'organic' },
    { test: /(^|\.)(bing\.com|yahoo\.co\.jp|search\.yahoo\.co\.jp)$/,
                                              source: 'yahoo_bing', medium: 'organic' },
    { test: /(^|\.)(chatgpt\.com|openai\.com|perplexity\.ai|claude\.ai|gemini\.google\.com)$/,
                                              source: 'ai_chat',   medium: 'referral' }
  ];

  function detectSource() {
    var p = queryParams();
    var src = {
      source: p.utm_source || '',
      medium: p.utm_medium || '',
      campaign: p.utm_campaign || '',
      content: p.utm_content || '',
      gclid: p.gclid || p.wbraid || p.gbraid || ''
    };

    if (!src.source && src.gclid) {
      src.source = 'google';
      src.medium = 'cpc';
    }

    if (!src.source) {
      var ref = document.referrer || '';
      var host = '';
      try { host = ref ? new URL(ref).hostname : ''; } catch (err) { host = ''; }

      if (host && host !== window.location.hostname) {
        for (var i = 0; i < REFERRER_MAP.length; i++) {
          if (REFERRER_MAP[i].test.test(host)) {
            src.source = REFERRER_MAP[i].source;
            src.medium = REFERRER_MAP[i].medium;
            break;
          }
        }
        if (!src.source) { src.source = host; src.medium = 'referral'; }
      }
    }

    if (!src.source) { src.source = 'direct'; src.medium = 'none'; }
    return src;
  }

  // セッション初回接触を保持（プライベートモード等で例外が出ても落ちないようにする）
  function firstTouch() {
    var stored = null;
    try {
      var raw = window.sessionStorage.getItem(SOURCE_STORAGE_KEY);
      if (raw) stored = JSON.parse(raw);
    } catch (err) { /* sessionStorage が使えない環境 */ }

    var current = detectSource();
    var hasExplicit = !!(queryParams().utm_source || current.gclid);

    // 保存済みがあり、今回のURLに明示的な流入元が無いなら保存済みを使う
    if (stored && stored.source && !hasExplicit) return stored;

    try {
      window.sessionStorage.setItem(SOURCE_STORAGE_KEY, JSON.stringify(current));
    } catch (err) { /* 保存できなくても計測自体は続ける */ }
    return current;
  }

  var traffic = firstTouch();

  // どのLPかをパスから拾う（/beginner/ → beginner）
  function lpPage() {
    var m = window.location.pathname.match(/^\/([^/]+)\//);
    return m ? m[1] : 'root';
  }

  /* ---------------- LINEボタンのクリック計測 ----------------
     document へのイベント委譲にしているので、ボタンが何個あっても
     読み込み順がどうでも拾える。
     対象は class="js-line-cta" が付いたリンク。付け忘れの保険として
     lin.ee 宛のリンクも拾う。 */

  function ctaFromEvent(e) {
    var el = e.target;
    if (!el || typeof el.closest !== 'function') return null;
    return el.closest('a.js-line-cta, a[href*="lin.ee"]');
  }

  document.addEventListener('click', function (e) {
    var btn = ctaFromEvent(e);
    if (!btn) return;

    var position = btn.getAttribute('data-cta-position') || 'unknown';
    var label = btn.getAttribute('data-cta-label') ||
      (btn.textContent || '').trim().slice(0, 100);
    var hasGtag = typeof window.gtag === 'function';

    // Google タグマネージャー
    window.dataLayer = window.dataLayer || [];
    window.dataLayer.push({
      event: 'line_cta_click',
      ctaPosition: position,
      ctaLabel: label,
      trafficSource: traffic.source,
      trafficMedium: traffic.medium,
      trafficCampaign: traffic.campaign
    });

    if (!hasGtag) return;

    // Google タグ（GA4）
    // source / medium / campaign は GA4 の予約語と衝突するので traffic_ 接頭辞を付ける
    window.gtag('event', 'line_cta_click', {
      cta_position: position,
      cta_label: label,
      lp_page: lpPage(),
      page_path: window.location.pathname,
      traffic_source: traffic.source,
      traffic_medium: traffic.medium,
      traffic_campaign: traffic.campaign || '(not set)',
      traffic_content: traffic.content || '(not set)',
      has_gclid: traffic.gclid ? 'yes' : 'no'
    });

    // Google 広告のコンバージョン
    if (!cfg.ADS_ID || !cfg.ADS_CV_LABEL) return;

    var url = btn.getAttribute('href');
    // 別タブ・新規ウィンドウで開くクリック、href が無いボタン、
    // すでに他の処理でキャンセル済みのクリックは遷移制御しない
    var opensInNewContext =
      e.defaultPrevented ||
      e.button !== 0 ||
      e.metaKey || e.ctrlKey || e.shiftKey || e.altKey ||
      btn.getAttribute('target') === '_blank' ||
      !url;

    var params = { send_to: cfg.ADS_ID + '/' + cfg.ADS_CV_LABEL };

    if (opensInNewContext) {
      window.gtag('event', 'conversion', params);
      return;
    }

    // ここから先はこのタブで LINE に遷移するケース
    e.preventDefault();

    var navigated = false;
    var go = function () {
      if (navigated) return;
      navigated = true;
      window.location.href = url;
    };

    params.event_callback = go;
    window.gtag('event', 'conversion', params);
    window.setTimeout(go, ADS_NAV_FALLBACK_MS);
  });
})();

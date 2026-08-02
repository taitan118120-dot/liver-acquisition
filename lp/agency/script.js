/* ========================================================================
   TAITAN PRO / beginner LP 専用スクリプト
   ・スクロール出現アニメーション
   ・FAQアコーディオンの排他制御（1つ開くと他を閉じる）
   ・LINEボタンのクリック計測（GA4 / GTM 両対応）
   ======================================================================== */

document.addEventListener('DOMContentLoaded', function () {

  /* ---------- アンカー付きURLで着地したときは即時ジャンプ ----------
     html { scroll-behavior: smooth } はページ内リンク用。
     広告サイトリンク等で「/beginner/#faq」のように着地した場合まで
     スムーススクロールになると、ページ全体を延々と流れてから
     目的地に着く悪い体験になるため、初回だけ即時で飛ばす。
     さらにWebフォント適用でページ高さが変わって着地位置がズレるため、
     フォント読込後にもう一度位置を合わせ直す（ユーザーが自分で
     スクロールを始めていたら補正しない）。 */
  if (location.hash) {
    var userScrolled = false;
    ['wheel', 'touchstart', 'keydown'].forEach(function (ev) {
      window.addEventListener(ev, function () { userScrolled = true; },
        { once: true, passive: true });
    });

    var jumpToHash = function () {
      if (userScrolled) return;
      // ビューポート幅が取れていない（バックグラウンドタブ等で
      // レイアウト未確定の）状態で飛ぶと位置がズレるため、
      // 実寸が出てから改めて飛ぶ
      if (!window.innerWidth) {
        window.addEventListener('resize', jumpToHash, { once: true });
        return;
      }
      var landing = document.getElementById(location.hash.slice(1));
      if (!landing) return;
      document.documentElement.style.scrollBehavior = 'auto';
      landing.scrollIntoView({ block: 'start' });
      setTimeout(function () {
        document.documentElement.style.scrollBehavior = '';
      }, 0);
    };

    jumpToHash();
    window.addEventListener('load', jumpToHash);
    if (document.fonts && document.fonts.ready) {
      document.fonts.ready.then(jumpToHash);
    }
  }

  /* ---------- スクロール出現 ---------- */
  var revealTargets = document.querySelectorAll('.reveal');

  if ('IntersectionObserver' in window) {
    var observer = new IntersectionObserver(function (entries) {
      entries.forEach(function (entry) {
        if (entry.isIntersecting) {
          entry.target.classList.add('is-visible');
          observer.unobserve(entry.target);
        }
      });
    }, { threshold: 0.12 });

    revealTargets.forEach(function (el) { observer.observe(el); });
  } else {
    // 非対応ブラウザでは最初から表示する
    revealTargets.forEach(function (el) { el.classList.add('is-visible'); });
  }

  /* ---------- FAQアコーディオン（同時に開くのは1つだけ） ---------- */
  var faqItems = document.querySelectorAll('.faq details');

  faqItems.forEach(function (item) {
    item.addEventListener('toggle', function () {
      if (!item.open) return;
      faqItems.forEach(function (other) {
        if (other !== item) other.open = false;
      });
    });
  });

  /* ---------- LINEボタンのクリック計測（Google広告コンバージョン） ----------
     各ボタンには data-cta-position（設置場所）が付いています。
     GA4 なら gtag、GTM なら dataLayer にイベントを送ります。

     Google広告のCVは「クリック」計測なので、LINEへ遷移する前に
     コンバージョンの送信が完了している必要があります。
     同一タブでそのまま lin.ee へ飛ぶと送信が中断されて計上されないため、
     Google公式のクリック用スニペットと同じく
     「遷移を一旦止める → 送信完了(event_callback)で遷移」方式にしています。
     送信が詰まっても必ず遷移するよう、1秒のフォールバックを入れています。
     ------------------------------------------------------------------- */
  var ctaButtons = document.querySelectorAll('.js-line-cta');
  var ADS_NAV_FALLBACK_MS = 1000;

  ctaButtons.forEach(function (btn) {
    btn.addEventListener('click', function (e) {
      var position = btn.getAttribute('data-cta-position') || 'unknown';
      var label = btn.getAttribute('data-cta-label') || btn.textContent.trim();
      var cfg = window.TAITAN_TRACKING || {};
      var hasGtag = typeof window.gtag === 'function';

      // Google タグマネージャー
      window.dataLayer = window.dataLayer || [];
      window.dataLayer.push({
        event: 'line_cta_click',
        ctaPosition: position,
        ctaLabel: label
      });

      if (!hasGtag) return;

      // Google タグ（GA4）
      window.gtag('event', 'line_cta_click', {
        cta_position: position,
        cta_label: label,
        page_path: window.location.pathname
      });

      // Google 広告のコンバージョン（index.html の TAITAN_TRACKING に
      // ADS_ID と ADS_CV_LABEL を入れると送信されます）
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
  });

});

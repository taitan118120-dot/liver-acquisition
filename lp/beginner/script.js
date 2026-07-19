/* ========================================================================
   TAITAN PRO / beginner LP 専用スクリプト
   ・スクロール出現アニメーション
   ・FAQアコーディオンの排他制御（1つ開くと他を閉じる）
   ・LINEボタンのクリック計測（GA4 / GTM 両対応）
   ======================================================================== */

document.addEventListener('DOMContentLoaded', function () {

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

  /* ---------- LINEボタンのクリック計測 ----------
     各ボタンには data-cta-position（設置場所）が付いています。
     GA4 なら gtag、GTM なら dataLayer に自動でイベントを送ります。
     計測タグ自体は index.html の <!-- ここにGoogleタグ --> に貼ってください。
     ------------------------------------------------------------------- */
  var ctaButtons = document.querySelectorAll('.js-line-cta');

  ctaButtons.forEach(function (btn) {
    btn.addEventListener('click', function () {
      var position = btn.getAttribute('data-cta-position') || 'unknown';
      var label = btn.getAttribute('data-cta-label') || btn.textContent.trim();

      // Google タグ（GA4）
      if (typeof window.gtag === 'function') {
        window.gtag('event', 'line_cta_click', {
          cta_position: position,
          cta_label: label,
          page_path: window.location.pathname
        });
      }

      // Google タグマネージャー
      window.dataLayer = window.dataLayer || [];
      window.dataLayer.push({
        event: 'line_cta_click',
        ctaPosition: position,
        ctaLabel: label
      });
    });
  });

});

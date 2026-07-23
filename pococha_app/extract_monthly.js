/* /monthly_liver_report?user_id=... の月次レポートをJSON抽出してダウンロード.
   organizer-ope のレポート画面で DevTools コンソールに貼って実行。
   data/monthly/monthly_{user_id}_{YYYY-MM}.json として保存される。 */
(() => {
  const lines = document.body.innerText.split('\n').map(s => s.trim()).filter(Boolean);
  const after = (label) => {
    const i = lines.indexOf(label);
    return i >= 0 && i + 1 < lines.length ? lines[i + 1] : null;
  };
  const num = (v) => {
    if (v == null) return null;
    const n = parseInt(String(v).replace(/[,\s]/g, ''), 10);
    return Number.isFinite(n) ? n : null;
  };
  const hmsToMin = (s) => {
    if (!s) return null;
    const m = s.match(/^(\d+):(\d+)(?::(\d+))?$/);
    if (!m) return null;
    return (+m[1]) * 60 + (+m[2]) + (m[3] ? Math.round(+m[3] / 60) : 0);
  };

  const monthLabel = lines.find(s => /^\d{4}年\d+月$/.test(s));
  let month = null;
  if (monthLabel) {
    const m = monthLabel.match(/^(\d{4})年(\d+)月$/);
    month = `${m[1]}-${String(+m[2]).padStart(2, '0')}`;
  }

  const userId = (location.search.match(/user_id=(\d+)/) || [])[1] || null;

  const out = {
    user_id: userId,
    month,
    month_label: monthLabel,
    range: lines.find(s => /^\d+月\d+日.+~/.test(s)),
    final_rank: after('最終ランク'),
    max_rank: after('最高ランク'),
    support_points: num(after('応援ポイント（累計）')),
    stream_time_str: after('配信時間（累計）'),
    stream_min: hmsToMin(after('配信時間（累計）')),
    stream_days: num(after('配信日数')),
    total_dia: num(after('月間獲得ダイヤ')),
    time_dia: num(after('時間ダイヤ（累計）')),
    hype_dia: num(after('盛り上がりダイヤ（累計）')),
    followers: num(after('フォロワー数')),
    comments: num(after('コメント数（累計）')),
    comment_people: num(after('コメント人数（累計）')),
    likes: num(after('いいね数（累計）')),
    like_people: num(after('いいね人数（累計）')),
    viewed_time_str: after('視聴された時間（累計）'),
    viewed_min: hmsToMin(after('視聴された時間（累計）')),
    listeners: num(after('リスナー数（累計）')),
    daily_best: num(after('デイリー最高順位')),
    monthly_rank: num(after('マンスリー順位')),
    captured_at: new Date().toISOString(),
  };

  const blob = new Blob([JSON.stringify(out, null, 2)], { type: 'application/json' });
  const a = document.createElement('a');
  a.href = URL.createObjectURL(blob);
  a.download = `monthly_${userId || 'unknown'}_${month || 'unknown'}.json`;
  document.body.appendChild(a);
  a.click();
  a.remove();
  return out;
})();

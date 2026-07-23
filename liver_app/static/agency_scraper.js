/**
 * Instagram hashtag scraper - Chrome DevTools用
 *
 * 使い方:
 *  1. Chromeで instagram.com を開く（ログイン済みであること）
 *  2. F12 → Console タブ
 *  3. 下のコード全体をコピペして Enter
 *  4. 51タグ全部スクレイプして taitan-pro-dm.fly.dev/api/ingest に流し込む
 *
 * 所要時間: 約15分（タグ間1秒・プロフ間500ms・rate limit対策）
 */

(async () => {
  const FLY_BASE = "https://taitan-pro-dm.fly.dev";
  const FLY_PW = prompt("Fly DM appのパスワードを入力 (.app_password の中身)");
  if (!FLY_PW) { console.error("パスワード未入力"); return; }

  // 51 agency tags
  const TAGS = [
    "ネイルサロン経営","美容室経営","コンカフェオーナー","エステサロン経営","カフェ経営","治療院経営",
    "SNS運用代行","コンテンツ販売初心者","無在庫転売","物販","ネット副業","インスタ運用代行",
    "ラウンジ嬢","キャバクラ嬢","銀座ホステス","六本木ラウンジ",
    "ライバーになりたい","配信者好きと繋がりたい","推し活",
    "副業ママ","副業女子","主婦副業","副業初心者","在宅ワーママ","在宅ワーク","フリーランスママ",
    "個人事業主","自営業女子","起業準備中","起業ママ","一人社長","個人サロン経営","ひとり社長",
    "ナイトワーク","夜職女子","歌舞伎町","キャバ嬢日記","ラウンジ嬢日記","銀座ラウンジ","六本木キャバクラ",
    "ライバーデビュー","配信デビュー","配信したい","ライブ配信したい","ライバーやってみたい",
    "インスタコンサル","インスタ集客","SNSコンサル","コンテンツ販売","SNS集客",
  ];

  const sleep = (ms) => new Promise(r => setTimeout(r, ms));

  // 1. Fly login → cookie取得
  const lr = await fetch(`${FLY_BASE}/login`, {
    method: "POST",
    headers: {"Content-Type": "application/x-www-form-urlencoded"},
    body: new URLSearchParams({password: FLY_PW}),
    credentials: "include",
  });
  if (!lr.ok) { console.error("Fly login失敗", lr.status); return; }
  console.log("✓ Fly login OK");

  // 2. Instagram hashtag scrape
  const csrftoken = document.cookie.match(/csrftoken=([^;]+)/)?.[1] || "";
  const igHeaders = {
    "x-ig-app-id": "936619743392459",
    "x-csrftoken": csrftoken,
    "x-asbd-id": "129477",
    "x-requested-with": "XMLHttpRequest",
    "Accept": "*/*",
  };

  const allUsers = new Map();
  for (let i = 0; i < TAGS.length; i++) {
    const tag = TAGS[i];
    try {
      const r = await fetch(`/api/v1/tags/web_info/?tag_name=${encodeURIComponent(tag)}`, {
        headers: igHeaders,
        credentials: "include",
      });
      if (!r.ok) {
        console.warn(`[${i+1}/${TAGS.length}] #${tag} HTTP ${r.status}`);
        await sleep(1500);
        continue;
      }
      const data = await r.json();
      const recent = data.data?.recent?.sections || [];
      const top = data.data?.top?.sections || [];
      const secs = [...recent, ...top];
      let count = 0;
      for (const s of secs) {
        const medias = s.layout_content?.medias || [];
        for (const m of medias) {
          const u = m.media?.user || {};
          if (u.username && !allUsers.has(u.username) && !u.is_private) {
            allUsers.set(u.username, {username: u.username, full_name: u.full_name||"", from_tag: tag});
            count++;
          }
        }
      }
      console.log(`[${i+1}/${TAGS.length}] #${tag}: +${count} (累計 ${allUsers.size})`);
    } catch (e) {
      console.warn(`[${i+1}/${TAGS.length}] #${tag} err:`, e.message);
    }
    await sleep(1000);
  }
  console.log(`\n=== ${allUsers.size} unique candidates ===\n`);

  // 3. プロフィール取得 (bio含)
  const profiles = [];
  const arr = [...allUsers.values()];
  for (let j = 0; j < arr.length; j++) {
    const c = arr[j];
    try {
      const r = await fetch(`/api/v1/users/web_profile_info/?username=${encodeURIComponent(c.username)}`, {
        headers: igHeaders,
        credentials: "include",
      });
      if (!r.ok) { await sleep(1500); continue; }
      const d = await r.json();
      const u = d.data?.user;
      if (!u) { await sleep(500); continue; }
      profiles.push({
        u: c.username,
        n: u.full_name || "",
        b: (u.biography || "").slice(0, 500),
        fl: u.edge_followed_by?.count,
        fw: u.edge_follow?.count,
        pv: u.is_private,
        vf: u.is_verified,
        bz: u.is_business_account,
        c: u.category_name,
        tag: c.from_tag,
        target_type_hint: "agency",
      });
      if ((j+1) % 20 === 0) console.log(`  プロフ ${j+1}/${arr.length}, fetched=${profiles.length}`);
    } catch (e) {
      console.warn(`  ${c.username} err:`, e.message);
    }
    await sleep(500);
  }
  console.log(`\n=== ${profiles.length} profiles fetched, push to Fly ===\n`);

  // 4. /api/ingest にバッチでpush
  const BATCH = 50;
  let added=0, updated=0;
  for (let k = 0; k < profiles.length; k += BATCH) {
    const batch = profiles.slice(k, k+BATCH);
    try {
      const r = await fetch(`${FLY_BASE}/api/ingest`, {
        method: "POST",
        headers: {"Content-Type": "application/json"},
        credentials: "include",
        body: JSON.stringify({profiles: batch}),
      });
      const d = await r.json();
      added += d.added || 0;
      updated += d.updated || 0;
      console.log(`  batch ${Math.floor(k/BATCH)+1}: +added=${d.added} updated=${d.updated}`);
    } catch (e) {
      console.warn(`  batch ${Math.floor(k/BATCH)+1} err:`, e.message);
    }
  }
  console.log(`\n✅ DONE: added=${added} updated=${updated}`);
})();

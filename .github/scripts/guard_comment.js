// 番犬Issueの「再検知」コメントを、内容が変わったときだけ積むための共通処理。
//
// 背景（2026-08-09）: プロフィール番犬が2026-08-08から毎ランで赤になり、
// そのたびに同じ内容の「再検知」コメントをIssueに積んでいた。
// Issueは1本にまとめられていてもコメント1件ごとにメール通知が飛ぶため、
// 「同じ違反がまだ直っていない」という1つの事実で毎日メールが増え続けていた。
// 検知漏れではなく通知の重複なので、赤（ラン失敗）とIssueのオープンは維持したまま、
// 前回とまったく同じ内容の再検知コメントだけを黙らせる。
//
// 使い方（各ワークフローの github-script ステップから）:
//   const guard = require('./.github/scripts/guard_comment.js');
//   await guard.notify({ github, context, title, body, recomment: '...', key: '自動投稿' });
//
//   title     … 番犬Issueのタイトル（既存Issue探索のキー）
//   body      … Issueが無いとき新規作成する本文
//   recomment … 既にIssueがあるとき積む再検知コメント本文（先頭の時刻行は比較時に無視）
//   key       … 1本のIssueを複数のワークフローで共有するときの発信元名（省略可）
//
// 戻り値: 'created' | 'commented' | 'unchanged'
//
// key を付ける理由（2026-09-16）: X APIのクレジット枯渇(402)は投稿・リプ候補・リスト追加の
// 3本を同時に止めるので、集約先のIssueを3本のワークフローで共有する形になった。
// 「直近の再検知コメント」だけを見て比較すると、発信元が A→B→A→B… と交互に積むたびに
// 「前回と違う」と判定され、黙らせたかったコメントが毎日増え続ける（ピンポン）。
// そこで**発信元ごとに、その発信元の最後のコメントと比べる**。
// key を省略した従来の呼び出しは「再検知:」で始まるコメントだけを自分のものとして見るので、
// key 付きの発信元とは混ざらない。

// 発信元ごとの再検知コメントの目印。これで始まるコメントだけを「自分の前回」として扱う。
function marker(key) {
  return key ? `再検知（${key}）:` : '再検知:';
}

// 先頭の「再検知: <ISO時刻>」行と前後の空白を落として内容だけを取り出す。
// 時刻はランごとに必ず変わるので、これを含めたまま比較すると永久に一致しない。
function fingerprint(text) {
  return String(text || '')
    .replace(/^(再検知|再検知（[^）]*）):.*$/m, '')
    .trim();
}

async function findOpenIssue({ github, context, title }) {
  const issues = await github.paginate(github.rest.issues.listForRepo, {
    owner: context.repo.owner,
    repo: context.repo.repo,
    state: 'open',
    per_page: 100,
  });
  return issues.find((i) => i.title === title);
}

async function notify({ github, context, title, body, recomment, key }) {
  const owner = context.repo.owner;
  const repo = context.repo.repo;
  const mark = marker(key);

  // recomment の先頭が目印と一致していないと、自分で積んだコメントを次回
  // 「自分のもの」として拾えず、永久に重複し続ける。静かに壊れるので早期に落とす。
  if (recomment && !String(recomment).trim().startsWith(mark)) {
    throw new Error(
      `[guard_comment] recomment は "${mark}" で始めてください（key=${key || 'なし'}）`,
    );
  }

  const match = await findOpenIssue({ github, context, title });

  if (!match) {
    await github.rest.issues.create({ owner, repo, title, body });
    return 'created';
  }

  // 同じ発信元の直近コメントと内容が同じなら黙る（ランの色もIssueの開閉も変えない）。
  const comments = await github.paginate(github.rest.issues.listComments, {
    owner,
    repo,
    issue_number: match.number,
    per_page: 100,
  });
  const previous = comments
    .filter((c) => String(c.body || '').trim().startsWith(mark))
    .pop();

  if (previous && fingerprint(previous.body) === fingerprint(recomment)) {
    console.log(
      `[guard_comment] 内容が前回と同一のため再検知コメントを省略: #${match.number} (${mark})`,
    );
    return 'unchanged';
  }

  await github.rest.issues.createComment({
    owner,
    repo,
    issue_number: match.number,
    body: recomment,
  });
  return 'commented';
}

module.exports = { notify, fingerprint, findOpenIssue, marker };

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
//   await guard.notify({ github, context, title, body, recomment: '...' });
//
//   title     … 番犬Issueのタイトル（既存Issue探索のキー）
//   body      … Issueが無いとき新規作成する本文
//   recomment … 既にIssueがあるとき積む再検知コメント本文（先頭の時刻行は比較時に無視）
//
// 戻り値: 'created' | 'commented' | 'unchanged'

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

async function notify({ github, context, title, body, recomment }) {
  const owner = context.repo.owner;
  const repo = context.repo.repo;
  const match = await findOpenIssue({ github, context, title });

  if (!match) {
    await github.rest.issues.create({ owner, repo, title, body });
    return 'created';
  }

  // 直近の「再検知」コメントと内容が同じなら黙る（ランは赤のまま／Issueもオープンのまま）。
  const comments = await github.paginate(github.rest.issues.listComments, {
    owner,
    repo,
    issue_number: match.number,
    per_page: 100,
  });
  const previous = comments
    .filter((c) => /^(再検知|再検知（)/.test(String(c.body || '').trim()))
    .pop();

  if (previous && fingerprint(previous.body) === fingerprint(recomment)) {
    console.log(
      `[guard_comment] 内容が前回と同一のため再検知コメントを省略: #${match.number}`,
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

module.exports = { notify, fingerprint, findOpenIssue };

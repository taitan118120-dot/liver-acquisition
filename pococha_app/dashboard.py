"""所属ライバーの状況ダッシュボードを自己完結HTMLで生成.

運営ページの公式数字（ランク・週/月ダイヤ・ダイヤ発生時間・配信時間・オフ日・
イベント）だけを、専門用語なしで1画面にまとめる。コメント系の指標は扱わない。

使い方:
    python3 dashboard.py            # data/dashboard.html を生成
    python3 dashboard.py --open     # 生成してブラウザで開く
    （Finder で「ダッシュボードを開く.command」をダブルクリックでも可）
"""
import json
import os
import subprocess
import sys
from datetime import datetime, timezone, timedelta

sys.path.insert(0, os.path.dirname(__file__))
from db import connect
from coach import load_liver, analyze
from alerts import build_alerts, liver_score

JST = timezone(timedelta(hours=9))
NOW = datetime.now(JST)
THIS_MONTH = NOW.strftime("%Y-%m")
OUT = os.path.join(os.path.dirname(__file__), "data", "dashboard.html")

RANK_TIER = "ESDCBA"


def _tier(r):
    return RANK_TIER.find((r or "")[0]) if r else -1


def _days_since(s):
    if not s:
        return None
    try:
        return (NOW.date() - datetime.strptime(s.strip()[:10], "%Y-%m-%d").date()).days
    except ValueError:
        return None


def build_advice(data, alerts, snap, monthly, rank_hist, stream_daily, active_events):
    """データから具体アドバイスを生成。捏造禁止・観測事実ベースのみ。

    各要素 {kind: good|keep|improve|tip, text: str}
    """
    tips = []
    lv = data["liver"]
    st = analyze(data)["st"]

    # 月ペース：時間ダイヤ vs 盛り上がりダイヤの比率
    if monthly and monthly["total_dia"]:
        t = monthly["time_dia"] or 0
        h = monthly["hype_dia"] or 0
        total = monthly["total_dia"]
        if total > 0 and h > 0 and t > 0:
            hype_ratio = h / total
            if hype_ratio >= 0.4:
                tips.append({"kind": "good",
                             "text": f"今月の盛り上がりダイヤ比率 {hype_ratio*100:.0f}%。コアファンが盛り上げてくれている強いタイプ"})
            elif hype_ratio <= 0.15 and total >= 5000:
                tips.append({"kind": "improve",
                             "text": f"盛り上がりダイヤが少ない（全体の {hype_ratio*100:.0f}%）。投げる動機づくり・お礼・参加型企画を増やす"})

    # 月ペース：日数あたり配信時間
    if monthly and monthly["stream_days"] and monthly["stream_min"]:
        avg_min = monthly["stream_min"] / monthly["stream_days"]
        if avg_min < 90:
            tips.append({"kind": "improve",
                         "text": f"1日あたり配信時間が平均 {avg_min:.0f} 分と短め。1枠あたりの長さを伸ばすとダイヤが伸びやすい"})
        elif avg_min >= 180:
            tips.append({"kind": "good",
                         "text": f"1日 {avg_min/60:.1f}時間の配信。時間ダイヤが安定して稼げる土台あり"})

    # 配信日数の積み上げ
    if monthly and monthly["stream_days"] is not None:
        # 月の経過日数に対して、配信日数の割合
        from datetime import date
        today = NOW.date()
        passed = today.day
        ratio = monthly["stream_days"] / max(passed, 1)
        if ratio >= 0.8 and passed >= 7:
            tips.append({"kind": "keep",
                         "text": f"今月 {passed}日中 {monthly['stream_days']}日配信。継続力◎ このペースを維持"})
        elif ratio < 0.5 and passed >= 10:
            tips.append({"kind": "improve",
                         "text": f"今月の配信日数 {monthly['stream_days']}日 / 経過 {passed}日。配信頻度を上げる余地あり"})

    # ランクメーターの動き
    if rank_hist and len(rank_hist) >= 3:
        recent = rank_hist[-7:]
        plus = sum(r["meter_delta"] or 0 for r in recent if (r["meter_delta"] or 0) > 0)
        minus = sum(r["meter_delta"] or 0 for r in recent if (r["meter_delta"] or 0) < 0)
        if plus + minus > 0 and plus > abs(minus) * 2:
            tips.append({"kind": "good",
                         "text": f"直近{len(recent)}件のランクメーターは +{plus}/{minus}。上り調子"})
        elif minus < 0 and abs(minus) > plus * 2:
            tips.append({"kind": "improve",
                         "text": f"直近{len(recent)}件のメーターが -{abs(minus)} に偏る。コア来場が落ちていないか確認"})

    # 上位入りの頻度
    if rank_hist:
        top_in = sum(1 for r in rank_hist if "上位" in (r["reason"] or ""))
        if top_in >= 3:
            tips.append({"kind": "good",
                         "text": f"上位入り {top_in}日／集計期間中。コアファンが集まる時間帯が固まっている"})

    # イベント参加状況
    if active_events:
        tips.append({"kind": "tip",
                     "text": f"「{active_events[0]}」参加中。期間中は配信回数とコア来場の最大化を一緒に作戦立てる"})

    # 新規歓迎枠
    if st and st["n"] >= 5 and st["shinki_n"] == 0:
        tips.append({"kind": "tip",
                     "text": "直近の配信に新規歓迎枠なし。新規流入の入口枠を意識的に作るよう提案"})

    # NG配信
    if st and st["ng_n"] >= 1:
        tips.append({"kind": "improve",
                     "text": f"5分未満終了の支払対象外配信が {st['ng_n']}件。開始前に枠タイトル・回線・電池を確認"})

    # フォロワー基盤と現ランク
    if lv["followers"] is not None and lv["followers"] >= 500 and rank_hist:
        cur = rank_hist[-1]["after_rank"] or ""
        if cur.startswith(("D", "E")):
            tips.append({"kind": "tip",
                         "text": f"フォロワー {lv['followers']:,} のわりにランクが低め。来場呼びかけ・配信告知を見直す余地あり"})

    # 健全：何も問題なし
    if not tips and not alerts:
        tips.append({"kind": "good",
                     "text": "観測データに大きな課題は見当たらず。現状の運用を維持で十分"})

    return tips


def collect(conn):
    livers = conn.execute("SELECT * FROM livers ORDER BY user_id").fetchall()
    out = []
    for lv in livers:
        uid, name = lv["user_id"], lv["name"]

        snap = conn.execute(
            "SELECT * FROM snapshots WHERE user_id=? ORDER BY captured_on DESC LIMIT 1", (uid,),
        ).fetchone()
        # 今月の月次レポート（/monthly_liver_report）— 月間ダイヤの正本
        monthly = conn.execute(
            "SELECT * FROM monthly_reports WHERE user_id=? AND month=?", (uid, THIS_MONTH),
        ).fetchone()
        rank_hist = conn.execute(
            "SELECT change_date, before_rank, after_rank, reason, meter_delta "
            "FROM rank_history WHERE user_id=? ORDER BY change_date", (uid,),
        ).fetchall()
        stream_daily = conn.execute(
            "SELECT substr(started_at,1,10) d, sum(duration_min) m FROM streams "
            "WHERE user_id=? GROUP BY d ORDER BY d", (uid,),
        ).fetchall()
        results = conn.execute(
            "SELECT event_name, place, status, period FROM event_history "
            "WHERE user_id=? AND kind='result' ORDER BY period DESC", (uid,),
        ).fetchall()
        active = conn.execute(
            "SELECT event_name FROM event_history WHERE user_id=? AND kind='entry' "
            "AND status LIKE '%参加中%'", (uid,),
        ).fetchall()
        dia = conn.execute(
            "SELECT diamonds FROM dia_balance WHERE user_id=? ORDER BY captured_on DESC LIMIT 1", (uid,),
        ).fetchone()
        off_month = conn.execute(
            "SELECT count(*) c FROM off_days WHERE user_id=? AND off_date LIKE ?",
            (uid, THIS_MONTH + "%"),
        ).fetchone()["c"]

        # ランクの動き（履歴の最初の before → 最新の after）
        move = None
        if rank_hist:
            fr, to = rank_hist[0]["before_rank"], rank_hist[-1]["after_rank"]
            if _tier(to) > _tier(fr):
                move = {"text": f"{fr} から昇格", "dir": "up"}
            elif _tier(to) < _tier(fr):
                move = {"text": f"{fr} から降格", "dir": "down"}
            else:
                move = {"text": "ランク維持", "dir": "keep"}

        last_stream = stream_daily[-1]["d"] if stream_daily else None
        cur_rank = rank_hist[-1]["after_rank"] if rank_hist else (
            f"{snap['rank']} ({snap['rank_meter']})" if snap else "-")

        liver_data = load_liver(conn, uid)
        alerts = build_alerts(liver_data)
        alerts.sort(key=lambda a: {"high": 0, "mid": 1, "low": 2}[a["sev"]])
        advice = build_advice(liver_data, alerts, snap, monthly, rank_hist,
                              stream_daily, [r["event_name"] for r in active])

        # 月次レポートがあれば月間ダイヤ等はそちらを正本にする
        month_total_dia = monthly["total_dia"] if monthly else (snap["diamonds_month"] if snap else None)
        month_time_dia  = monthly["time_dia"]  if monthly else (snap["diamonds_month"] if snap else None)
        month_hype_dia  = monthly["hype_dia"]  if monthly else None
        month_stream_days = monthly["stream_days"] if monthly else None
        month_stream_min  = monthly["stream_min"]  if monthly else None
        monthly_rank    = monthly["monthly_rank"] if monthly else None

        out.append({
            "user_id": uid, "name": name,
            "kpi": {
                "rank": cur_rank, "move": move,
                "week_dia": snap["diamonds_week"] if snap else None,
                "month_dia": month_total_dia,
                "month_time_dia": month_time_dia,
                "month_hype_dia": month_hype_dia,
                "month_stream_days": month_stream_days,
                "month_stream_min": month_stream_min,
                "monthly_rank": monthly_rank,
                "dia_week_min": snap["dia_min_week"] if snap else None,
                "dia_month_min": snap["dia_min_month"] if snap else None,
                "stream_cur_h": snap["stream_cur_h"] if snap else None,
                "followers": lv["followers"], "balance": dia["diamonds"] if dia else None,
                "tenure": _days_since(lv["agency_since"]) or _days_since(lv["member_since"]),
                "off_month": off_month, "region": lv["region"], "level": lv["level"],
                "last_stream": last_stream, "gap": _days_since(last_stream),
            },
            "rank_daily": [[r["change_date"], r["after_rank"], r["meter_delta"] or 0, r["reason"]] for r in rank_hist],
            "stream_daily": [[r["d"], r["m"] or 0] for r in stream_daily],
            "events_active": [r["event_name"] for r in active],
            "results": [[r["event_name"], r["place"], r["status"], r["period"]] for r in results],
            "alerts": alerts,
            "advice": advice,
            "score": liver_score(alerts),
        })
    return out


HTML = """<!doctype html><html lang="ja"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>所属ライバー ダッシュボード</title>
<script src="https://cdn.jsdelivr.net/npm/chart.js@4"></script>
<style>
 :root{--bg:#0f1115;--card:#1a1d24;--ink:#e8eaed;--sub:#9aa0a8;--ac:#ff5e8a;--ok:#46d39a;--warn:#ffb454}
 *{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--ink);font-family:-apple-system,"Hiragino Sans",sans-serif;font-size:14px}
 header{padding:16px 20px;border-bottom:1px solid #262a33;position:sticky;top:0;background:var(--bg);z-index:5}
 .brandrow{display:flex;align-items:center;gap:12px}
 .brandlogo{width:40px;height:auto;border-radius:10px;flex-shrink:0;box-shadow:0 2px 8px rgba(0,0,0,.45);border:1px solid rgba(255,255,255,.07)}
 h1{font-size:18px;margin:0}.meta{color:var(--sub);font-size:12px;margin-top:4px}
 .tabs{display:flex;gap:8px;margin-top:12px;flex-wrap:wrap}
 .tab{padding:7px 16px;border-radius:999px;background:var(--card);color:var(--sub);cursor:pointer;border:1px solid #262a33}
 .tab.on{background:var(--ac);color:#fff;border-color:var(--ac)}
 main{padding:20px;max-width:1000px;margin:0 auto}
 .kpis{display:grid;grid-template-columns:repeat(auto-fill,minmax(160px,1fr));gap:12px;margin-bottom:20px}
 .kpi{background:var(--card);border-radius:12px;padding:14px}
 .kpi .l{color:var(--sub);font-size:12px}.kpi .v{font-size:22px;font-weight:700;margin-top:6px}
 .kpi .s{color:var(--sub);font-size:12px;margin-top:3px}
 .up{color:var(--ok)}.down{color:var(--ac)}.warn{color:var(--warn)}
 .grid{display:grid;grid-template-columns:1fr 1fr;gap:16px}
 @media(max-width:780px){.grid{grid-template-columns:1fr}}
 .panel{background:var(--card);border-radius:12px;padding:16px;margin-bottom:16px}
 .panel h2{font-size:14px;margin:0 0 12px;color:var(--ink);font-weight:700}
 table{width:100%;border-collapse:collapse}
 th,td{text-align:left;padding:7px 8px;border-bottom:1px solid #262a33}th{color:var(--sub);font-weight:600;font-size:12px}
 .badge{display:inline-block;padding:1px 8px;border-radius:6px;background:#262a33}
 .alert{padding:11px 13px;border-radius:8px;margin:8px 0;line-height:1.6}
 .alert.high{background:#3a1820;border-left:3px solid #ff5e8a}
 .alert.mid{background:#332a14;border-left:3px solid #ffb454}
 .alert.low{background:#23262e;border-left:3px solid #5a626e}
 .alert .act{color:var(--sub);font-size:13px;margin-top:4px}
 .adv{padding:10px 13px;border-radius:8px;margin:6px 0;line-height:1.55;display:flex;gap:10px;align-items:flex-start}
 .adv.good{background:#15291f;border-left:3px solid #46d39a}
 .adv.keep{background:#1d2530;border-left:3px solid #6aa9ff}
 .adv.improve{background:#2c2516;border-left:3px solid #ffb454}
 .adv.tip{background:#23262e;border-left:3px solid #9aa0a8}
 .adv .ic{font-size:16px;line-height:1.4}
 .summary{background:var(--card);border-radius:12px;padding:16px;margin-bottom:20px}
 .summary h2{font-size:14px;margin:0 0 8px}
 .srow{display:flex;align-items:center;gap:12px;padding:10px 6px;border-bottom:1px solid #262a33;cursor:pointer;border-radius:6px}
 .srow:hover{background:#23262e}.srow:last-child{border-bottom:0}
 .srow .nm{font-weight:700;min-width:140px}.srow .rs{flex:1}.srow .go{color:var(--sub);font-size:12px}
 .ok{color:var(--ok)}
</style></head><body>
<header><div class="brandrow"><img class="brandlogo" src="logo.jpg" alt="TAITAN PRO" width="40" height="41"><div><h1>所属ライバー ダッシュボード</h1>
<div class="meta">__GEN__ 時点 ／ __N__ 名 ・ 名前をクリックで詳細</div></div></div>
<div class="tabs" id="tabs"></div></header>
<main><section class="summary" id="summary"></section><div id="app"></div></main>
<script>
const DATA = __DATA__;
const SEVMK={high:'🔴',mid:'🟡',low:'⚪'};
const ADVMK={good:'✅',keep:'📌',improve:'🛠',tip:'💡'};
function hm(min){if(min==null)return '-';const h=min/60|0,m=min%60;return h?`${h}時間${m?m+'分':''}`:`${m}分`}
function kpi(l,v,s,cls){return `<div class="kpi"><div class="l">${l}</div><div class="v ${cls||''}">${v??'-'}</div><div class="s">${s||''}</div></div>`}
let charts=[];
function render(i){
  charts.forEach(c=>c.destroy());charts=[];
  const d=DATA[i],k=d.kpi,app=document.getElementById('app');
  const mv=k.move?`<span class="${k.move.dir==='up'?'up':k.move.dir==='down'?'down':''}">${k.move.dir==='up'?'⤴ ':k.move.dir==='down'?'⤵ ':''}${k.move.text}</span>`:'';
  const gapCls=k.gap!=null&&k.gap>=3?'down':'';
  app.innerHTML=`
  <div class="kpis">
    ${kpi('今のランク',k.rank,k.move?k.move.text:'')}
    ${kpi('今月のダイヤ',k.month_dia?.toLocaleString(),
      '時間 '+(k.month_time_dia?.toLocaleString()??'-')+' ／ 盛り上がり '+(k.month_hype_dia?.toLocaleString()??'-'))}
    ${kpi('今月の配信',(k.month_stream_days??'-')+'日',hm(k.month_stream_min))}
    ${kpi('今週のダイヤ',k.week_dia?.toLocaleString(),'時間 '+hm(k.dia_week_min))}
    ${kpi('マンスリー順位',k.monthly_rank?.toLocaleString())}
    ${kpi('フォロワー',k.followers?.toLocaleString(),'Lv'+(k.level??'-')+' ・ '+(k.region||'-'))}
    ${kpi('今月のお休み',k.off_month!=null?k.off_month+'日':'-')}
    ${kpi('最終配信',k.gap!=null?(k.gap===0?'今日':k.gap+'日前'):'-',k.last_stream||'',gapCls)}
    ${kpi('ダイヤ残高',k.balance?.toLocaleString(),'事務所歴 '+(k.tenure!=null?k.tenure+'日':'-'))}
  </div>
  ${d.alerts.length?`<div class="panel"><h2>気にすること・声かけ</h2>${
    d.alerts.map(a=>`<div class="alert ${a.sev}"><div><b>${a.cat}</b>：${a.why}</div><div class="act">→ ${a.action}</div></div>`).join('')}</div>`
    :'<div class="panel"><h2>気にすること・声かけ</h2><div class="ok">特に問題なし。健全に回っています。</div></div>'}
  ${d.advice&&d.advice.length?`<div class="panel"><h2>自動アドバイス</h2>${
    d.advice.map(a=>`<div class="adv ${a.kind}"><div class="ic">${ADVMK[a.kind]||'·'}</div><div>${a.text}</div></div>`).join('')}</div>`:''}
  <div class="grid">
    <div class="panel"><h2>ランクの動き（直近）</h2><canvas id="c_rank" height="170"></canvas>
      <div class="s" style="color:var(--sub);margin-top:8px">棒が上＝メーター増（上位入り）、下＝減</div></div>
    <div class="panel"><h2>1日ごとの配信時間</h2><canvas id="c_stream" height="170"></canvas></div>
  </div>
  <div class="panel"><h2>イベント</h2>
    ${d.events_active.length?`<div style="margin-bottom:10px">参加中：${d.events_active.map(e=>`<span class="badge">${e}</span>`).join(' ')}</div>`:''}
    ${d.results.length?'<table><tr><th>イベント</th><th>順位</th><th>結果</th><th>期間</th></tr>'+
      d.results.map(r=>`<tr><td>${r[0]}</td><td><span class="badge">${r[1]||'-'}</span></td><td>${r[2]||''}</td><td class="s" style="color:var(--sub)">${(r[3]||'').replace(/ JST/g,'').slice(0,10)}〜</td></tr>`).join('')+'</table>'
      :(d.events_active.length?'':'<div class="ok" style="color:var(--sub)">入賞履歴なし</div>')}
  </div>`;

  const grid={color:'#262a33'},tick={color:'#9aa0a8',font:{size:11}};
  charts.push(new Chart(c_rank,{type:'bar',data:{labels:d.rank_daily.map(r=>r[0].slice(5)),
    datasets:[{data:d.rank_daily.map(r=>r[2]),backgroundColor:d.rank_daily.map(r=>r[2]<0?'#ff5e8a':r[2]>0?'#46d39a':'#5a626e')}]},
    options:{plugins:{legend:{display:false},tooltip:{callbacks:{afterLabel:c=>'ランク: '+d.rank_daily[c.dataIndex][1]+' / '+(d.rank_daily[c.dataIndex][3]||'')}}},
    scales:{x:{grid,ticks:tick},y:{grid,ticks:tick}}}}));
  charts.push(new Chart(c_stream,{type:'bar',data:{labels:d.stream_daily.map(r=>r[0].slice(5)),
    datasets:[{data:d.stream_daily.map(r=>r[1]),backgroundColor:'#46d39a'}]},
    options:{plugins:{legend:{display:false},tooltip:{callbacks:{label:c=>hm(c.raw)}}},scales:{x:{grid,ticks:tick},y:{grid,ticks:tick}}}}));

  document.querySelectorAll('.tab').forEach((t,j)=>t.classList.toggle('on',j===i));
}
function renderSummary(){
  const order=DATA.map((d,i)=>({i,d})).sort((a,b)=>b.d.score-a.d.score);
  const nHigh=DATA.reduce((s,d)=>s+d.alerts.filter(a=>a.sev==='high').length,0);
  document.getElementById('summary').innerHTML=`<h2>今、声をかけるべき子${nHigh?`（🔴重要 ${nHigh}件）`:''}</h2>`+
    order.map(({i,d})=>{const t=d.alerts[0];
      return `<div class="srow" data-i="${i}"><span class="nm">${d.name}</span>`+
        (t?`<span class="rs">${SEVMK[t.sev]} ${t.cat}：${t.why}</span>`:`<span class="rs ok">✅ 問題なし</span>`)+
        `<span class="go">詳細 ›</span></div>`;
    }).join('');
  document.querySelectorAll('.srow').forEach(r=>r.onclick=()=>{render(+r.dataset.i);window.scrollTo({top:0,behavior:'smooth'})});
}
const tabs=document.getElementById('tabs');
DATA.forEach((d,i)=>{const t=document.createElement('div');t.className='tab';t.textContent=d.name;t.onclick=()=>render(i);tabs.appendChild(t)});
renderSummary();render(0);
</script></body></html>"""


def main():
    conn = connect()
    data = collect(conn)
    conn.close()
    html = (HTML
            .replace("__DATA__", json.dumps(data, ensure_ascii=False))
            .replace("__GEN__", NOW.strftime("%Y-%m-%d %H:%M"))
            .replace("__N__", str(len(data))))
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    with open(OUT, "w", encoding="utf-8") as f:
        f.write(html)
    print(f"生成: {OUT}（{len(data)}名）")
    if "--open" in sys.argv[1:]:
        subprocess.run(["open", OUT])


if __name__ == "__main__":
    main()

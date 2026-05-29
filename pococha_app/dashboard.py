"""所属ライバーの成績推移ダッシュボードを自己完結HTMLで生成.

蓄積データから KPI と推移グラフ（日次コメント/配信時間/ランクメーター）を
1枚のHTMLにまとめる。Chart.js は CDN 読み込み（ネット必要、無料）。

使い方:
    python3 dashboard.py            # data/dashboard.html を生成
    python3 dashboard.py --open     # 生成してブラウザで開く

データの粒度メモ:
  - comments  : 50日規模の長期系列（日次コメント数・ユニーク数＝エンゲージメント）
  - streams   : 直近20枠（≒1週間）の日次配信時間
  - rank_history: 直近5日のランク/メーター
  - dia_balance: 取得日ごと1点
スナップショット日数が増えれば週/月ダイヤの推移も足せる（拡張余地）。
"""
import json
import os
import sys
import webbrowser
from datetime import datetime, timezone, timedelta

sys.path.insert(0, os.path.dirname(__file__))
from db import connect
from coach import load_liver, analyze
from alerts import build_alerts, liver_score

JST = timezone(timedelta(hours=9))
NOW = datetime.now(JST)
OUT = os.path.join(os.path.dirname(__file__), "data", "dashboard.html")


def _days_since(s):
    if not s:
        return None
    try:
        return (NOW.date() - datetime.strptime(s.strip()[:10], "%Y-%m-%d").date()).days
    except ValueError:
        return None


def collect(conn):
    livers = conn.execute("SELECT * FROM livers ORDER BY user_id").fetchall()
    out = []
    for lv in livers:
        uid, name = lv["user_id"], lv["name"]

        comment_daily = conn.execute(
            "SELECT substr(posted_at,1,10) d, count(*) n, count(DISTINCT commenter) p "
            "FROM comments WHERE liver=? AND posted_at IS NOT NULL GROUP BY d ORDER BY d",
            (name,),
        ).fetchall()
        stream_daily = conn.execute(
            "SELECT substr(started_at,1,10) d, sum(duration_min) m, count(*) n "
            "FROM streams WHERE user_id=? GROUP BY d ORDER BY d", (uid,),
        ).fetchall()
        rank_daily = conn.execute(
            "SELECT change_date d, after_rank, meter_delta FROM rank_history "
            "WHERE user_id=? ORDER BY change_date", (uid,),
        ).fetchall()
        results = conn.execute(
            "SELECT event_name, place, status, period FROM event_history "
            "WHERE user_id=? AND kind='result' ORDER BY period DESC", (uid,),
        ).fetchall()
        dia = conn.execute(
            "SELECT diamonds FROM dia_balance WHERE user_id=? ORDER BY captured_on DESC LIMIT 1",
            (uid,),
        ).fetchone()
        snap = conn.execute(
            "SELECT * FROM snapshots WHERE user_id=? ORDER BY captured_on DESC LIMIT 1", (uid,),
        ).fetchone()
        fans = conn.execute(
            "SELECT count(DISTINCT commenter) p FROM comments WHERE liver=?", (name,),
        ).fetchone()["p"]
        last_stream = stream_daily[-1]["d"] if stream_daily else None

        cur_rank = rank_daily[-1]["after_rank"] if rank_daily else (
            f"{snap['rank']} ({snap['rank_meter']})" if snap else "-")
        tenure = _days_since(lv["agency_since"]) or _days_since(lv["member_since"])

        # コーチング要約 + 声かけアラート（coach.py / alerts.py 再利用）
        cdata = load_liver(conn, uid)
        cres = analyze(cdata)
        alerts = build_alerts(cdata)
        alerts.sort(key=lambda a: {"high": 0, "mid": 1, "low": 2}[a["sev"]])

        out.append({
            "user_id": uid, "name": name, "display_name": lv["display_name"],
            "coach": {"flags": cres["flags"], "trend": cres["trend"], "goals": cres["goals"]},
            "alerts": alerts,
            "score": liver_score(alerts),
            "kpi": {
                "rank": cur_rank,
                "diamonds": dia["diamonds"] if dia else None,
                "followers": lv["followers"], "fans": fans, "level": lv["level"],
                "tenure": tenure, "region": lv["region"],
                "week_dia": snap["diamonds_week"] if snap else None,
                "month_dia": snap["diamonds_month"] if snap else None,
                "last_stream": last_stream,
                "gap": _days_since(last_stream) if last_stream else None,
            },
            "comment_daily": [[r["d"], r["n"], r["p"]] for r in comment_daily],
            "stream_daily": [[r["d"], r["m"] or 0, r["n"]] for r in stream_daily],
            "rank_daily": [[r["d"], r["after_rank"], r["meter_delta"] or 0] for r in rank_daily],
            "results": [[r["event_name"], r["place"], r["status"], r["period"]] for r in results],
        })
    return out


HTML = """<!doctype html><html lang="ja"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Pococha 成績推移ダッシュボード</title>
<script src="https://cdn.jsdelivr.net/npm/chart.js@4"></script>
<style>
 :root{--bg:#0f1115;--card:#1a1d24;--ink:#e8eaed;--sub:#9aa0a8;--ac:#ff5e8a;--ac2:#5ec8ff;--ok:#46d39a;--warn:#ffb454}
 *{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--ink);font-family:-apple-system,"Hiragino Sans",sans-serif}
 header{padding:16px 20px;border-bottom:1px solid #262a33;position:sticky;top:0;background:var(--bg);z-index:5}
 h1{font-size:18px;margin:0}.meta{color:var(--sub);font-size:12px;margin-top:4px}
 .tabs{display:flex;gap:8px;margin-top:12px;flex-wrap:wrap}
 .tab{padding:7px 14px;border-radius:999px;background:var(--card);color:var(--sub);cursor:pointer;border:1px solid #262a33;font-size:13px}
 .tab.on{background:var(--ac);color:#fff;border-color:var(--ac)}
 main{padding:20px;max-width:1100px;margin:0 auto}
 .kpis{display:grid;grid-template-columns:repeat(auto-fill,minmax(150px,1fr));gap:12px;margin-bottom:20px}
 .kpi{background:var(--card);border-radius:12px;padding:14px}
 .kpi .l{color:var(--sub);font-size:11px}.kpi .v{font-size:22px;font-weight:700;margin-top:4px}
 .kpi .s{color:var(--sub);font-size:11px;margin-top:2px}
 .grid{display:grid;grid-template-columns:1fr 1fr;gap:16px}
 @media(max-width:780px){.grid{grid-template-columns:1fr}}
 .panel{background:var(--card);border-radius:12px;padding:14px}
 .panel h2{font-size:13px;margin:0 0 10px;color:var(--sub);font-weight:600}
 .full{grid-column:1/-1}
 table{width:100%;border-collapse:collapse;font-size:13px}
 th,td{text-align:left;padding:6px 8px;border-bottom:1px solid #262a33}th{color:var(--sub);font-weight:600}
 .badge{display:inline-block;padding:1px 8px;border-radius:6px;background:#262a33;font-size:12px}
 .warn{color:var(--warn)}
 .coach{display:grid;grid-template-columns:1.3fr 1fr;gap:16px;margin-bottom:20px}
 @media(max-width:780px){.coach{grid-template-columns:1fr}}
 .coach ul{margin:0;padding-left:18px}.coach li{margin:6px 0;font-size:13px;line-height:1.55}
 .alert{padding:10px 12px;border-radius:8px;margin:8px 0;font-size:13px;line-height:1.5}
 .alert.high{background:#3a1820;border-left:3px solid #ff5e8a}
 .alert.mid{background:#332a14;border-left:3px solid #ffb454}
 .alert.low{background:#23262e;border-left:3px solid #5a626e}
 .alert .act{color:var(--sub);font-size:12px;margin-top:4px}
 .summary{background:var(--card);border-radius:12px;padding:14px;margin-bottom:20px}
 .summary h2{font-size:13px;margin:0 0 6px;color:var(--sub)}
 .srow{display:flex;align-items:center;gap:10px;padding:9px 4px;border-bottom:1px solid #262a33;cursor:pointer;border-radius:6px}
 .srow:hover{background:#23262e}.srow:last-child{border-bottom:0}
 .srow .nm{font-weight:600;min-width:120px}.srow .rs{font-size:13px;color:var(--ink)}.srow .ct{font-size:11px;color:var(--sub);margin-left:auto}
 .ok{color:var(--ok)}
</style></head><body>
<header><h1>Pococha コーチング・ダッシュボード</h1>
<div class="meta">生成: __GEN__ ／ 所属 __N__ 名 ・ ライバー名をクリックで詳細</div>
<div class="tabs" id="tabs"></div></header>
<main><section class="summary" id="summary"></section><div id="app"></div></main>
<script>
const DATA = __DATA__;
const $ = (h)=>{const t=document.createElement('template');t.innerHTML=h.trim();return t.content.firstChild};
let charts=[];
function fmtMin(m){return (m/60|0)+'h'+String(m%60).padStart(2,'0')+'m'}
function kpi(l,v,s){return `<div class="kpi"><div class="l">${l}</div><div class="v">${v??'-'}</div><div class="s">${s||''}</div></div>`}
function render(i){
  charts.forEach(c=>c.destroy());charts=[];
  const d=DATA[i],k=d.kpi,app=document.getElementById('app');
  const gapWarn = k.gap!=null && k.gap>=3 ? ' warn':'';
  app.innerHTML=`
  <div class="kpis">
    ${kpi('ランク',k.rank)}
    ${kpi('ダイヤ残高',k.diamonds?.toLocaleString())}
    ${kpi('週ダイヤ',k.week_dia?.toLocaleString(),'月 '+(k.month_dia?.toLocaleString()??'-'))}
    ${kpi('フォロワー',k.followers?.toLocaleString(),'Lv'+(k.level??'-')+' / '+(k.region||'-'))}
    ${kpi('コア来場者',k.fans?.toLocaleString(),'コメント収集ベース')}
    ${kpi('事務所歴',k.tenure!=null?k.tenure+'日':'-')}
    `+`<div class="kpi"><div class="l">最終配信</div><div class="v${gapWarn}">${k.gap!=null?k.gap+'日前':'-'}</div><div class="s">${k.last_stream||''}</div></div>`+`
  </div>
  <div class="coach">
    <div class="panel"><h2>いま気にすること・声かけ</h2>${d.alerts.length?
      d.alerts.map(a=>`<div class="alert ${a.sev}"><div><b>[${a.cat}]</b> ${a.why}</div><div class="act">→ ${a.action}</div></div>`).join('')
      :'<div class="ok">特に問題なし（健全に回っています）</div>'}</div>
    <div class="panel"><h2>次にやること</h2><ul>${d.coach.goals.map(g=>`<li>${g}</li>`).join('')||'<li>—</li>'}</ul>
      <h2 style="margin-top:14px">調子・伸び</h2><ul>${d.coach.trend.map(t=>`<li>${t}</li>`).join('')||'<li>データ蓄積中</li>'}</ul></div>
  </div>
  <div class="grid">
    <div class="panel full"><h2>日次コメント数 / ユニーク来場者（エンゲージメント推移）</h2><canvas id="c_comment" height="110"></canvas></div>
    <div class="panel"><h2>日次配信時間（分）</h2><canvas id="c_stream" height="170"></canvas></div>
    <div class="panel"><h2>ランクメーター増減（直近）</h2><canvas id="c_rank" height="170"></canvas></div>
    <div class="panel full"><h2>イベント入賞履歴</h2>${d.results.length?
      '<table><tr><th>イベント</th><th>順位</th><th>賞</th><th>期間</th></tr>'+
      d.results.map(r=>`<tr><td>${r[0]}</td><td><span class="badge">${r[1]||'-'}</span></td><td>${r[2]||''}</td><td class="s">${(r[3]||'').replace(' JST','')}</td></tr>`).join('')+'</table>'
      :'<div class="s" style="color:var(--sub)">入賞履歴なし</div>'}</div>
  </div>`;

  const grid={color:'#262a33'},tick={color:'#9aa0a8',font:{size:10}};
  charts.push(new Chart(c_comment,{data:{labels:d.comment_daily.map(r=>r[0]),
    datasets:[
      {type:'bar',label:'コメント数',data:d.comment_daily.map(r=>r[1]),backgroundColor:'#ff5e8a55',borderColor:'#ff5e8a',yAxisID:'y'},
      {type:'line',label:'ユニーク来場者',data:d.comment_daily.map(r=>r[2]),borderColor:'#5ec8ff',backgroundColor:'#5ec8ff',yAxisID:'y1',tension:.3,pointRadius:2}
    ]},options:{responsive:true,interaction:{mode:'index',intersect:false},
    plugins:{legend:{labels:{color:'#e8eaed',font:{size:11}}}},
    scales:{x:{grid,ticks:tick},y:{position:'left',grid,ticks:tick},y1:{position:'right',grid:{drawOnChartArea:false},ticks:tick}}}}));

  charts.push(new Chart(c_stream,{type:'bar',data:{labels:d.stream_daily.map(r=>r[0].slice(5)),
    datasets:[{label:'配信(分)',data:d.stream_daily.map(r=>r[1]),backgroundColor:'#46d39a'}]},
    options:{plugins:{legend:{display:false},tooltip:{callbacks:{label:c=>fmtMin(c.raw)}}},scales:{x:{grid,ticks:tick},y:{grid,ticks:tick}}}}));

  charts.push(new Chart(c_rank,{type:'bar',data:{labels:d.rank_daily.map(r=>r[0].slice(5)),
    datasets:[{label:'メーター増減',data:d.rank_daily.map(r=>r[2]),
      backgroundColor:d.rank_daily.map(r=>r[2]<0?'#ff5e8a':'#ffb454')}]},
    options:{plugins:{legend:{display:false},tooltip:{callbacks:{afterLabel:c=>'ランク: '+d.rank_daily[c.dataIndex][1]}}},
    scales:{x:{grid,ticks:tick},y:{grid,ticks:tick}}}}));

  document.querySelectorAll('.tab').forEach((t,j)=>t.classList.toggle('on',j===i));
}
const SEVMK={high:'🔴',mid:'🟡',low:'⚪'};
function renderSummary(){
  const order=DATA.map((d,i)=>({i,d})).sort((a,b)=>b.d.score-a.d.score);
  const el=document.getElementById('summary');
  const nHigh=DATA.reduce((s,d)=>s+d.alerts.filter(a=>a.sev==='high').length,0);
  el.innerHTML=`<h2>声かけリスト（要対応の多い順 ・ 🔴重要 ${nHigh}件）</h2>`+
    order.map(({i,d})=>{
      const top=d.alerts[0];
      const body=top?`<span class="rs">${SEVMK[top.sev]} ${top.why}</span>`:`<span class="rs ok">✅ 健全</span>`;
      return `<div class="srow" data-i="${i}"><span class="nm">${d.name}</span>${body}<span class="ct">${d.alerts.length?d.alerts.length+'件':''}</span></div>`;
    }).join('');
  el.querySelectorAll('.srow').forEach(r=>r.onclick=()=>{render(+r.dataset.i);window.scrollTo({top:0,behavior:'smooth'})});
}
const tabs=document.getElementById('tabs');
DATA.forEach((d,i)=>{const t=$(`<div class="tab">${d.name}</div>`);t.onclick=()=>render(i);tabs.appendChild(t)});
renderSummary();
render(0);
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
        webbrowser.open("file://" + OUT)


if __name__ == "__main__":
    main()

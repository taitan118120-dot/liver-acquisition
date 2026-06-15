"""
Note記事85（フォロワー増えない）をX/Threads/IGの自動投稿キューに一括投入する一回限りスクリプト。
- Threads: threads/threads_posts.json に追記（text only, link=None で拡散優先）
- X:       x_content/x_posts.json に追記
- IG:      instagram/ig_posts.json に追記 + 画像はPILフォールバックで生成（Google API予算を使わない）
"""
import json
import os
import sys
from datetime import datetime

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "instagram"))

NOW = datetime.now().isoformat(timespec="seconds")

# ---------------------------------------------------------------------------
# Threads（10本）— バズ鉄則: フック1行→1メッセージ→会話で締める。linkは貼らない。
# ---------------------------------------------------------------------------
THREADS = [
    "配信に来てくれてるのにフォローされない人へ。\n\n理由、シンプルで「一回もフォローしてって言ってない」だけだったりする。\n\nリスナーは“言われないと押さない”。\n「いつもありがとう」で終わってる枠、めちゃくちゃ多い。\n\n恥ずかしくて言えない人、いる？",
    "フォロー率って、配信のうまさより“プロフ”で決まってること多い。\n\nリスナーは枠を覗く前にプロフを見て、\n・いつ来れば会える？\n・何が聞ける？\nこれが無いと、フォローまで進まない。\n\n「よろしくお願いします」だけの自己紹介、今すぐ直していい。",
    "枠タイトル、これ変えるだけでフォロー増える。\n\n❌「夜更かし配信〜♡」→ 何の枠か不明\n⭕️「【映画好き集まれ】今日は〇〇の感想会」→ 興味ある人がフォロー\n\n“次もこのテーマ続きそう”って思わせた瞬間にフォローされる。\n\n自分の今日のタイトル、内容伝わってる？",
    "見落としがちだけど、アイコンって一覧画面で“指の爪くらい”の大きさでしか映らない。\n\nその状態で目を引かないと、そもそも枠を覗かれない＝フォローもされない。\n\n・顔が小さすぎる\n・暗い\n・文字が潰れてる\n\nこのどれか当てはまったら、今日変えるだけで変わるかも。",
    "「今日はゲーム、明日は歌、明後日は雑談」\nこれ、本人は飽きさせない工夫のつもりでも、リスナーには“次に何があるか分からない人”に見える。\n\nフォローは「次も同じものが来る期待」で押される。\n\n核を1つに絞った人から伸びていく。これマジ。",
    "フォローしてもらえない原因、もう1つ。\n\n配信中リスナーはあなたの話に集中してる。\nわざわざボタンを押す“間”が無いと、行動に移さない。\n\n「ここで一回フォローしてくれたら嬉しい」\nこれを配信に2〜3回、意識的に挟む。\nそれだけでいい。",
    "フォロワーは“増やす”だけ考えがちだけど、本当は“減らさない”方が大事。\n\nタイムラインを動かしてないと「いてもいなくても同じ人」になって、静かに解除されてく。\n\n配信前「今日〇時から」\n配信後「ありがとう、次は〇日」\nこれだけで“いるな”って思ってもらえる。",
    "新規リスナーが一番来るのは、配信開始から5〜10分。\n\nここで一回だけ\n「気に入ったらフォローだけでも嬉しいです、次の配信に通知届くので」\nってサラッと言う。\n\n“フォローすると何が得か”を一言添えるのがコツ。\n\nこれ知ってるだけで初月の伸び変わる。",
    "これ言うと一部に刺さると思うけど——\n\n「フォローしたらフォロバします」系、Pocochaでやらない方がいい。\n\n数字は増えるけど、配信に来ない人ばっかり集まって視聴率が上がらない。\nフォロワー数だけ増えてもコアファンにならないと意味ない。\n\n数より“来てくれる人”。",
    "4年見てきて思うのは、フォロワーが増えないのは配信回数でも容姿でもない。\n\n“増える導線”を体系で教わってないだけ。\n\n逆に言うと、型を知って毎日繰り返せば確実に伸びる。\nフォロワーが増えれば、コアファンも自然に増える。\n\nフォロワー、今いちばん何で詰まってる？",
]

# ---------------------------------------------------------------------------
# X（10本）— 280字以内・1ツイート完結・リンクなし（プロフで回収）
# ---------------------------------------------------------------------------
X_POSTS = [
    ("follower-01", "Pocochaでフォロワーが増えない一番の原因、\n「一度もフォローしてって言ってない」だったりする。\n\nリスナーは“明示的に言われないと”押さない。\n「いつもありがとう」で終わってる枠は伸びない。\n\n恥ずかしくても言う。これだけで変わる。"),
    ("follower-02", "フォロー率はプロフで決まる。\n\nリスナーは枠を覗く前にプロフを見る。\n・配信スケジュール（いつ来れば会える）\n・配信テーマ（何が聞ける）\n・人となりの一言\n\n「よろしくお願いします」だけの自己紹介は、フォロー率を下げてる。"),
    ("follower-03", "枠タイトル、これだけで変わる👇\n\n❌ 夜更かし配信〜♡\n⭕️【映画好き集まれ】今日は〇〇の感想会\n\n“誰のための・何の配信か”が一目で分かると、興味マッチした人がフォローする。\n内容不明タイトルは損してる。"),
    ("follower-04", "アイコンは一覧で「指の爪サイズ」でしか映らない。\n\n・顔が小さい\n・暗い\n・文字が潰れてる\n\nこのどれかだと、そもそも枠を覗かれない＝フォローされない。\n迷ったら“顔大きめ×自然光×笑顔”が鉄板。"),
    ("follower-05", "フォローは「次も同じものが来る期待」で押される。\n\n今日ゲーム、明日歌、明後日雑談…だと\n“次に何があるか分からない人”になってフォローされにくい。\n\n配信の核を1つに絞った人から伸びる。"),
    ("follower-06", "配信中、リスナーはあなたの話に集中してる。\nだから“フォローボタンを押す間”を作らないと押されない。\n\n「ここで一回フォローしてくれたら嬉しい」\n配信に2〜3回、意識的に挟むだけでいい。"),
    ("follower-07", "フォロワーは“増やす”より“減らさない”方が地味に大事。\n\nタイムラインを動かさないと「いてもいなくても同じ人」と思われて静かに解除される。\n\n配信前「今日〇時から」／配信後「ありがとう、次は〇日」\nこれだけで解除は減る。"),
    ("follower-08", "新規が一番来るのは配信開始から5〜10分。\n\nここで一回だけ\n「気に入ったらフォローだけでも嬉しいです。次の配信に通知届くので」\nと“メリット”を添えて言う。\n\n初月の伸びがここで変わる。"),
    ("follower-09", "⚠️Pocochaでやらない方がいいフォロワー集め\n\n❌「フォローしたらフォロバします」\n→ 来ない人ばかり増えて視聴率が上がらない\n\n❌ 他ライバーの枠で「私の配信も来て」営業\n→ マナー違反、評判を落とすだけ\n\n数より“来てくれる人”。"),
    ("follower-10", "フォロワーが増えないのは、配信回数でも容姿でもない。\n“増える導線”を体系で教わってないだけ。\n\n型を知って毎日繰り返せば確実に伸びる。\nそしてフォロワーが増えれば、コアファンも自然に増える構造。\n\n元S帯が4年見てきた結論です。"),
]

# ---------------------------------------------------------------------------
# Instagram（4本）— 単一画像＋キャプション。DM誘導なし。タグは記事ごとに変える。
# ---------------------------------------------------------------------------
IG_POSTS = [
    {
        "id": "ig_follower_01",
        "title": "フォロワーが増えない7つの原因",
        "catchcopy": "来てるのに、なぜ押されない？",
        "caption": "配信に来てくれてるのにフォローされない——\nそれ、才能じゃなくて“導線”の問題です。\n\n元Pococha S帯として4年見てきて、増えない人にはだいたい共通の原因があります。\n\n①「フォローしてね」を一度も言ってない\n②プロフが弱い（スケジュール・テーマ・人となりが無い）\n③枠タイトルが“次も見たい”に見えない\n④アイコンが爪サイズで埋もれてる\n⑤配信に一貫性がない（次に何があるか不明）\n⑥フォローを押す“間”を作ってない\n⑦タイムラインを使ってない\n\nぜんぶ直さなくていい。今日の配信で「1個だけ」試すのが続けるコツ。\n\nどれが一番ドキッとした？コメントで番号教えて👇\n（プロフィールにもう少し詳しい解説あります）\n\n#Pococha #ポコチャ #ライブ配信 #ライバー #ポコチャ初心者 #配信のコツ",
    },
    {
        "id": "ig_follower_02",
        "title": "フォロー率が上がるプロフ3行テンプレ",
        "catchcopy": "覗いた人が、フォローする理由を作る",
        "caption": "フォロー率って、配信のうまさより“プロフ”で決まることが多いです。\n\n「よろしくお願いします」だけの自己紹介、もったいない。この3行を埋めるだけで、覗いた人がフォローする理由ができます。\n\n1行目＝配信時間（例：毎週月水金 22時〜24時）\n2行目＝配信テーマ（例：映画レビューと雑談）\n3行目＝一言（例：仕事終わりの息抜きにどうぞ）\n\nプロフは2ヶ月に1回見直すのがおすすめ。スケジュールやテーマがズレたまま放置されてると、逆にフォロー率を下げます。\n\nあなたのプロフ、3行入ってた？\n\n#Pococha #ポコチャ #ライバー #ライブ配信 #プロフィール #ポコチャ初心者",
    },
    {
        "id": "ig_follower_03",
        "title": "そのアイコン、フォロワー逃してるかも",
        "catchcopy": "一覧では“爪サイズ”でしか映らない",
        "caption": "スマホの一覧画面、アイコンって本当に小さく映ります。だから“パッと目を引くか”が全て。\n\nこのどれか当てはまってたら要注意↓\n・顔が小さすぎる\n・暗くて何が映ってるか分からない\n・文字が入って潰れてる\n→ そもそも枠を覗かれない＝フォローされない\n\n迷ったら顔が画面の6割を占める明るい笑顔写真に変えてみて。これだけでフォロー率が変わった子、何人も見てきました。プロに撮ってもらわなくてOK。\n\n今のアイコン、爪サイズでも目立ってる？\n\n#Pococha #ポコチャ #ライバー #ライブ配信 #アイコン #ポコチャ初心者",
    },
    {
        "id": "ig_follower_04",
        "title": "やってはいけないフォロワー集め NG3",
        "catchcopy": "数より“来てくれる人”",
        "caption": "フォロワー数だけ追いかけると、だいたいこの3つにハマります。\n\nNG①「フォローしたらフォロバします」連呼\n→ 来ない人ばかり増えて視聴率が上がらない\n\nNG②他ライバーの枠で「私の配信も来て」営業\n→ マナー違反、評判を落とすだけ\n\nNG③プロフを変えっぱなしで放置\n→ 古い情報はフォロー率を下げる。2ヶ月に1回見直し\n\n大事なのは“数”じゃなくて“配信に来てくれる人”。質の低いフォロワーをいくら集めても、コアファンには変わりません。\n\nやっちゃってたもの、正直に1つ選ぶなら？\n\n#Pococha #ポコチャ #ライバー #ライブ配信 #ポコチャ攻略 #ポコチャ初心者",
    },
]

SOURCE_FILE = "85_Pocochaフォロワー増えない.md"


def enqueue_threads():
    path = os.path.join(ROOT, "threads", "threads_posts.json")
    data = json.load(open(path, encoding="utf-8"))
    existing = {p.get("text", "").strip() for p in data}
    added = 0
    for text in THREADS:
        if text.strip() in existing:
            continue
        data.append({
            "text": text,
            "angle": "liver",
            "tags": [],
            "link": None,
            "reply_control": "everyone",
            "posted": False,
            "created_at": NOW,
        })
        added += 1
    json.dump(data, open(path, "w", encoding="utf-8"), ensure_ascii=False, indent=2)
    print(f"[Threads] +{added}本 → 合計{len(data)}（未投稿{sum(1 for p in data if not p.get('posted'))}）")


def enqueue_x():
    # 本番X自動投稿ソースは posts/twitter_posts.json（cloud_post.py が phase==growth を巡回投稿）。
    # x_content/x_posts.json は x_app(DM PWA)専用でcronでは使われないので使わない。
    path = os.path.join(ROOT, "posts", "twitter_posts.json")
    data = json.load(open(path, encoding="utf-8"))
    existing_ids = {p.get("id") for p in data}
    existing_text = {p.get("text", "").strip() for p in data}
    added = 0
    for i, (_pid, text) in enumerate(X_POSTS, 1):
        gid = f"g_follow{i:02d}"
        if gid in existing_ids or text.strip() in existing_text:
            continue
        data.append({"id": gid, "phase": "growth", "text": text})
        added += 1
    json.dump(data, open(path, "w", encoding="utf-8"), ensure_ascii=False, indent=2)
    growth = sum(1 for p in data if p.get("phase") == "growth")
    print(f"[X] +{added}本 → 合計{len(data)}（growth={growth}）")


def enqueue_ig():
    from ig_content_generator import (
        _create_pastel_background,
        _overlay_text_on_image,
        _detect_category,
    )
    images_dir = os.path.join(ROOT, "instagram", "images")
    os.makedirs(images_dir, exist_ok=True)
    path = os.path.join(ROOT, "instagram", "ig_posts.json")
    data = json.load(open(path, encoding="utf-8"))
    existing = {p.get("id") for p in data}
    added = 0
    for post in IG_POSTS:
        if post["id"] in existing:
            continue
        img_name = f"{post['id']}.png"
        img_abs = os.path.join(images_dir, img_name)
        category = _detect_category(post["title"])
        bg = _create_pastel_background(size=1080, seed=hash(post["id"]) & 0xFFFFFFFF, category=category)
        bg.save(img_abs)
        _overlay_text_on_image(img_abs, post["title"], post["catchcopy"], category=category)
        rel = os.path.relpath(img_abs, ROOT)
        data.append({
            "id": post["id"],
            "source_file": SOURCE_FILE,
            "source_type": "blog",
            "title": post["title"],
            "caption": post["caption"],
            "image_path": rel,
            "posted": False,
        })
        added += 1
        print(f"  画像生成: {rel} [{category}]")
    json.dump(data, open(path, "w", encoding="utf-8"), ensure_ascii=False, indent=2)
    print(f"[IG] +{added}本 → 合計{len(data)}（未投稿{sum(1 for p in data if not p.get('posted'))}）")


if __name__ == "__main__":
    enqueue_threads()
    enqueue_x()
    enqueue_ig()
    print("完了。")

"""リスト名を変更するワンショットスクリプト"""
import os
import tweepy

client = tweepy.Client(
    consumer_key=os.environ["TWITTER_API_KEY"],
    consumer_secret=os.environ["TWITTER_API_SECRET"],
    access_token=os.environ["TWITTER_ACCESS_TOKEN"],
    access_token_secret=os.environ["TWITTER_ACCESS_TOKEN_SECRET"],
)

LIST_ID = os.environ["X_LIST_ID"]

response = client.update_list(
    id=LIST_ID,
    name="応援したいライバーさん",
    description="頑張っているライバーさんをまとめています",
)

print(f"リスト名変更完了: {response}")

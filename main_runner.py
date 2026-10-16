from datetime import datetime, timedelta
import os
from bs4 import BeautifulSoup
import requests

# アップロードしたエンジンモジュールをインポート
from jackal_engine_github import run_jackal_engine


def send_discord_notification(message: str):
  """DiscordのWebhookに通知を送る"""
  webhook_url = os.environ.get('DISCORD_WEBHOOK_URL')
  if not webhook_url:
    print('⚠️ DISCORD_WEBHOOK_URL が設定されていません。')
    return

  payload = {'content': message}
  try:
    response = requests.post(webhook_url, json=payload)
    if response.status_code != 204:
      print(f'❌ Discord通知失敗: {response.status_code}')
  except Exception as e:
    print(f'⚠️ Discord通知エラー: {e}')


def main():
  print('🧪 【テスト実行】URL直接指定モードで起動します')

  # ==========================================
  # 🎯 ここにテストしたい正確なJRA出馬表のURLを直接貼り付けてね！
  # ==========================================
  test_race_urls =　[ "https://www.jra.go.jp/JRADB/accessD.html?CNAME=pw01dde0108202604071120261018/30"
  ]
  # もしURLが空欄のままだとエラーになるので、ダミーチェック
  if not test_race_urls or test_race_urls[0] == '':
    print(
        '⚠️ テスト用のURLが `test_race_urls` に設定されていません。コード内のURLを書き換えてね！'
    )
    send_discord_notification(
        '⚠️ JRA自動テスト: テスト用URLが設定されていません。'
    )
    return

  # 指定されたURLごとに JACKALエンジンを回して予測結果をDiscordに通知！
  for url in test_race_urls:
    print(f'🚀 処理中: {url}')
    try:
      # JACKALエンジンで分析＆推論を実行
      jackal_result_text = run_jackal_engine(url)
      # 結果をDiscordへ送信
      send_discord_notification(jackal_result_text)
    except Exception as e:
      error_msg = f'❌ エラー発生: {str(e)}'
      print(error_msg)
      send_discord_notification(error_msg)


if __name__ == '__main__':
  main()

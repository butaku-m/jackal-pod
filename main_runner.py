from datetime import datetime, timedelta
import os
from bs4 import BeautifulSoup
import requests

# アップロード済みのJACKALエンジンをインポート
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
    if response.status_code == 204:
      print('📤 Discordへの通知に成功しました！')
    else:
      print(f'❌ Discord通知失敗: ステータスコード {response.status_code}')
  except Exception as e:
    print(f'⚠️ Discord通知エラー: {e}')


def main():
  print('🧪 【テスト実行】URL直接指定モードでJACKALエンジンを起動します...')

  # ==========================================
  # 🎯 テストしたい正確なJRA出馬表のURLをここに直接入れる！
  # ==========================================
  test_race_urls = [
      # 例: 'https://www.jra.go.jp/JRADB/accessD.html?CNAME=pw01dde0105...'
      # 動かしたいJRAの正確な出馬表URLをここにダブルクォーテーションで囲んで入れてね
  ]

  if not test_race_urls or test_race_urls[0] == '':
    print('⚠️ テスト用のURLが `test_race_urls` に設定されていません。')
    send_discord_notification('⚠️ JACKALテスト: テスト用URLが設定されていません。')
    return

  # 指定されたURLごとに JACKALエンジンを回して予測結果をDiscordに通知
  for url in test_race_urls:
    print(f'🚀 分析中URL: {url}')
    try:
      # 1. JACKALエンジンで分析・予測を実行
      jackal_result_text = run_jackal_engine(url)

      # 2. 結果をDiscordへ送信（長い場合は分割 or そのまま飛ばす）
      send_discord_notification(jackal_result_text)

    except Exception as e:
      error_msg = f'❌ JACKALエンジン実行時エラー: {str(e)}'
      print(error_msg)
      send_discord_notification(error_msg)


if __name__ == '__main__':
  main()

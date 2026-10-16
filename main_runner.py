from datetime import datetime, timedelta
import os
from bs4 import BeautifulSoup
import requests

# アップロードしたエンジンモジュールをインポート
from jackal_engine_github import run_jackal_engine


def get_this_weekend_target_date(day_type: str):
  """今週末の土曜日または日曜日の日付を自動取得"""
  today = datetime.now()
  weekday = today.weekday()  # 月曜=5, 土曜=5, 日曜=6

  days_to_sat = (5 - weekday) % 7
  saturday = today + timedelta(days=days_to_sat)
  sunday = saturday + timedelta(days=1)

  if day_type == 'sat':
    return saturday.strftime('%Y%m%d')
  else:
    return sunday.strftime('%Y%m%d')


def screening_races_for_date(target_date: str):
  """指定日の全開催レースURLをスクリーニング"""
  headers = {
      'User-Agent': (
          'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML,'
          ' like Gecko) Chrome/120.0.0.0 Safari/537.36'
      )
  }

  venue_dict = {
      '05': {'name': '東京', 'suffix': '/D0', 'base_code': '20260406'},
      '08': {'name': '京都', 'suffix': '/AE', 'base_code': '20260406'},
      '04': {'name': '新潟', 'suffix': '/47', 'base_code': '20260401'},
  }

  valid_races = []
  print(f'📅 ------------------ 対象日: {target_date} のスキャン開始 ------------------')

  for venue_code, info in venue_dict.items():
    venue_name = info['name']
    suffix = info['suffix']
    base_code = info['base_code']

    for race_no in range(1, 13):
      race_no_str = f'{race_no:02d}'
      cname = f'pw01dde01{venue_code}{base_code}{race_no_str}{target_date}{suffix}'
      url = f'https://www.jra.go.jp/JRADB/accessD.html?CNAME={cname}'

      try:
        response = requests.get(url, headers=headers, timeout=3)
        if response.status_code == 200:
          if (
              'レース番組が見つかりません' not in response.text
              and len(response.text) > 2000
          ):
            valid_races.append({
                'date': target_date,
                'venue': venue_name,
                'race_no': race_no,
                'url': url,
            })
      except Exception:
        pass

  return valid_races


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
  today_weekday = datetime.now().weekday()

  if today_weekday == 5:
    target_date = get_this_weekend_target_date('sat')
    print('✨ 土曜日の朝9時タスクを実行します')
  elif today_weekday == 6:
    target_date = get_this_weekend_target_date('sun')
    print('✨ 日曜日の朝9時タスクを実行します')
  else:
    target_date = get_this_weekend_target_date('sat')
    print(
        '🧪 テスト実行: 今週末の土曜日をターゲットにします (日付:'
        f' {target_date})'
    )

  # 1. レースURLを一括スクリーニング
  valid_race_list = screening_races_for_date(target_date)
  print(f'🎯 発見された有効なレース数: {len(valid_race_list)}件')

  if not valid_race_list:
    send_discord_notification(
        f'⚠️ {target_date} の有効なJRAレースURLが見つかりませんでした。'
    )
    return

  # 2. 見つかったレースごとに JACKALエンジンを回して予測結果をDiscordに通知！
  for race in valid_race_list:
    print(
        f"🚀 処理中: {race['venue']} {race['race_no']}R ({race['url']})"
    )
    try:
      # JACKALエンジンで分析＆推論を実行
      jackal_result_text = run_jackal_engine(race['url'])
      # 結果をDiscordへ送信
      send_discord_notification(jackal_result_text)
    except Exception as e:
      error_msg = (
          f"❌ エラー発生 ({race['venue']} {race['race_no']}R): {str(e)}"
      )
      print(error_msg)
      send_discord_notification(error_msg)


if __name__ == '__main__':
  main()

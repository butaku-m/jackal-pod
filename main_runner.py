from datetime import datetime, timedelta
import os
import re
import time
from bs4 import BeautifulSoup
import requests

# AIエンジン（表なし軽量化・買い目＆根拠抽出版）をインポート
from jackal_engine_github import run_jackal_engine


def send_discord_notification(message: str):
  """DiscordのWebhookに通知を送る（強制文字数ガード付き）"""
  webhook_url = os.environ.get('DISCORD_WEBHOOK_URL')
  if not webhook_url:
    print('⚠️ DISCORD_WEBHOOK_URL が設定されていません。')
    return

  if not isinstance(message, str):
    message = str(message)

  if len(message) > 1900:
    message = message[:1850] + '\n\n...(※文字数制限超過のため省略)'

  payload = {'content': message}
  try:
    response = requests.post(webhook_url, json=payload)
    if response.status_code == 204:
      print('📤 Discordへの通知に成功しました！')
    else:
      print(f'❌ Discord通知失敗: ステータスコード {response.status_code}')
  except Exception as e:
    print(f'⚠️ Discord通知エラー: {e}')


def parse_race_time_from_html(html_content):
  """JRAのページHTMLから発走時刻（例: 15:40）を抽出する"""
  soup = BeautifulSoup(html_content, 'html.parser')
  page_text = soup.get_text()

  # 「15時40分」のような形式を探す
  time_match = re.search(r'(\d{1,2})時(\d{2})分', page_text)
  if time_match:
    h, m = time_match.groups()
    return f'{int(h):02d}:{int(m):02d}'

  # 「15:40」のような形式を探す
  time_match_alt = re.search(r'([0-2]\d:[0-5]\d)', page_text)
  if time_match_alt:
    return time_match_alt.group(1)

  return '15:00'  # 万が一見つからない場合のデフォルト


def screening_jra_races(target_date: str, venue_code: str = '05'):
  """指定した開催日（YYYYMMDD）と競馬場コードをもとに、

  1R〜12RのURLを自動生成し、発走時刻も含めてスクリーニングする関数
  """
  headers = {
      'User-Agent': (
          'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML,'
          ' like Gecko) Chrome/120.0.0.0 Safari/537.36'
      )
  }

  venue_map = {
      '01': '札幌',
      '02': '函館',
      '03': '福島',
      '04': '新潟',
      '05': '東京',
      '06': '中山',
      '07': '中京',
      '08': '京都',
      '09': '阪神',
      '10': '小倉',
  }
  venue_name = venue_map.get(venue_code, '中央競馬')
  formatted_date = f'{target_date[:4]}-{target_date[4:6]}-{target_date[6:]}'

  print(
      f'🔍 開催日: {formatted_date} / 競馬場: {venue_name} (コード:{venue_code})'
      ' のレースをスクリーニング中...\n'
  )

  valid_races = []

  for race_no in range(1, 13):
    race_no_str = f'{race_no:02d}'

    # あなたが検証して12Rしっかり拾えた確実なURL組み立てロジック！
    base_prefix = 'pw01dde01'
    cname = f'{base_prefix}{venue_code}20260406{race_no_str}{target_date}/D0'
    url = f'https://www.jra.go.jp/JRADB/accessD.html?CNAME={cname}'

    try:
      response = requests.get(url, headers=headers, timeout=5)

      if response.status_code == 200:
        if (
            'レース番組が見つかりません' not in response.text
            and len(response.text) > 2000
        ):
          # 発走時刻をHTMLから取得
          race_time = parse_race_time_from_html(response.text)
          race_title = f'{venue_name}{race_no}R'
          target_dt_str = f'{formatted_date} {race_time}'
          target_datetime = datetime.strptime(target_dt_str, '%Y-%m-%d %H:%M')

          valid_races.append({
              'date': formatted_date,
              'venue': venue_name,
              'race_no': race_no,
              'title': race_title,
              'url': url,
              'race_time': race_time,
              'target_datetime': target_datetime,
              'executed': False,
          })
          print(
              f'✅ 【有効】 {race_no}R (発走: {race_time}):'
              f' https://www.jra.go.jp/JRADB/accessD.html?CNAME={cname}'
          )
        else:
          print(f'⏩ 【無効・存在せず】 {race_no}R')
      else:
        print(f'❌ 【HTTPエラー {response.status_code}】 {race_no}R')

    except Exception as e:
      print(f'⚠️ 【通信エラー】 {race_no}R: {e}')

  return valid_races


def main():
  print('🚀 JRA全自動レーシング・タイマーシステム起動！')

  # 対象の日付と競馬場コード（必要に応じて変更可能）
  target_date = '20261017'
  venue_code = '05'  # 東京

  # 1. 確実なロジックで全レースをスクリーニング
  races = screening_jra_races(target_date, venue_code)
  print(f'\n🎯 有効なレースURL発見数: {len(races)}件\n')

  if not races:
    print('⚠️ 有効なレースが見つかりませんでした。')
    return

  print(
      '⏳ 各レースの「発走30分前」に向けた監視ループに入ります……（GitHub'
      ' Actions上ではタイムアウトに注意）\n'
  )

  # 2. タイマー監視ループ
  while True:
    now = datetime.now()
    all_done = True

    for race in races:
      if race['executed']:
        continue

      all_done = False
      # 発走の30分前を計算
      trigger_time = race['target_datetime'] - timedelta(minutes=30)

      if now >= trigger_time and now < race['target_datetime']:
        print(
            f"\n🚨 【発走30分前到達】 {race['title']} のJACKALエンジンを起動します！"
        )

        try:
          result_text = run_jackal_engine(race['url'])
          send_discord_notification(result_text)
        except Exception as e:
          err_msg = f"❌ {race['title']} 処理エラー: {str(e)}"
          print(err_msg)
          send_discord_notification(err_msg)

        race['executed'] = True

    if all_done:
      print('🎉 本日の監視レースの処理がすべて完了しました！システムを終了します。')
      break

    time.sleep(30)


if __name__ == '__main__':
  main()

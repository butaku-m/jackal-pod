from datetime import datetime, timedelta, timezone
import os
import re
import time
import pytz
import requests
from bs4 import BeautifulSoup

from jackal_engine_github import run_jackal_engine

jst = pytz.timezone('Asia/Tokyo')


def get_race_schedule(base_url):
  print('🕷️ 本日の全レースの発走時刻とスケジュールをスキャン中...')

  session = requests.Session()
  headers = {
      'User-Agent': (
          'Mozilla/5.0 (Windows NT 10.0; Win64; x64) '
          'AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36'
      ),
  }

  try:
    response = session.get(base_url, headers=headers, timeout=15)
    response.encoding = response.apparent_encoding
  except Exception as e:
    print(f'⚠️ スケジュール取得時の接続エラー: {e}')
    return []

  soup = BeautifulSoup(response.text, 'html.parser')
  page_text = soup.get_text()
  race_schedule = []

  date_match = re.search(r'k_raceDate=(\d{4}%2F\d{2}%2F\d{2}|\d{4}/\d{2}/\d{2})', base_url)
  date_str = (
      date_match.group(1).replace('%2F', '/') if date_match else '2026/10/20'
  )
  y, m, d = map(int, date_str.split('/'))

  time_candidates = re.findall(r'(\d{1,2}時\d{2}分|\d{1,2}:\d{2})', page_text)

  for r_no in range(1, 13):
    if 'k_raceNo=' in base_url:
      r_url = re.sub(r'k_raceNo=\d+', f'k_raceNo={r_no}', base_url)
    else:
      separator = '&' if '?' in base_url else '?'
      r_url = f'{base_url}{separator}k_raceNo={r_no}'

    start_time = None
    if r_no - 1 < len(time_candidates):
      t_str = time_candidates[r_no - 1]
      t_match = re.search(r'(\d{1,2}):(\d{2})', t_str)
      if t_match:
        th, tm = map(int, t_match.groups())
        start_time = datetime(y, m, d, th, tm, 0, tzinfo=jst)

    if not start_time:
      start_time = datetime(y, m, d, 10, 0, 0, tzinfo=jst) + timedelta(
          minutes=40 * (r_no - 1)
      )

    race_schedule.append(
        {'race_no': r_no, 'url': r_url, 'start_time': start_time}
    )

  print(f'✅ スケジュールスキャン完了: 全 {len(race_schedule)} レーズの時間を取得しました。')
  return race_schedule


def trigger_next_workflow(next_race_url, minutes_before):
  github_token = os.environ.get('GH_PAT') or os.environ.get('GITHUB_TOKEN')
  repository = os.environ.get('GITHUB_REPOSITORY')

  if not github_token or not repository:
    print('⚠️ GH_PAT または GITHUB_REPOSITORY が設定されていません。')
    return

  api_url = f'https://api.github.com/repos/{repository}/actions/workflows/timed_runner.yml/dispatches'
  headers = {
      'Authorization': f'Bearer {github_token}',
      'Accept': 'application/vnd.github.v3+json',
  }
  payload = {
      'ref': 'main',
      'inputs': {
          'race_url': next_race_url,
          'minutes_before': str(minutes_before),
      },
  }

  response = requests.post(api_url, json=payload, headers=headers)
  if response.status_code == 204:
    print('🚀 次のレースへのセルフ・トリガー（バトンタッチ）に成功しました！')
  else:
    print(f'❌ セルフ・トリガー失敗: {response.status_code} {response.text}')


def send_to_discord(message):
  webhook_url = os.environ.get('DISCORD_WEBHOOK_URL')
  if not webhook_url:
    print('⚠️ DISCORD_WEBHOOK_URL が設定されていません。')
    print(message)
    return

  payload = {'content': message}
  response = requests.post(webhook_url, json=payload)
  if response.status_code in [200, 204]:
    print('📤 Discordへの通知に成功しました！')
  else:
    print(f'❌ Discord通知失敗: {response.status_code} {response.text}')


def main():
  print('⏱️ JACKAL セルフ・トリガー連鎖システム起動！')

  current_race_url = os.environ.get(
      'RACE_URL',
      'https://www.keiba.go.jp/KeibaWeb/TodayRaceInfo/DebaTable?k_raceDate=2026%2F10%2F20&k_babaCode=18&k_raceNo=1',
  )
  minutes_before = int(os.environ.get('MINUTES_BEFORE', 10))

  now = datetime.now(jst)
  print(f'🕒 現在時刻: {now.strftime("%Y-%m-%d %H:%M:%S")}')

  # 1. 全レースのスケジュールを取得
  race_schedule = get_race_schedule(current_race_url)
  if not race_schedule:
    print('⚠️ 有効なレーススケジュールが取得できませんでした。終了します。')
    return

  # 2. 今回実行するターゲットと、その次のレースを特定
  target_race = None
  next_race = None

  for i, race in enumerate(race_schedule):
    target_time = race['start_time'] - timedelta(minutes=minutes_before)
    if now < target_time:
      target_race = race
      target_race['target_time'] = target_time
      if i + 1 < len(race_schedule):
        next_race = race_schedule[i + 1]
      break

  # 過去レースしか残っていない場合のフォールバック（直近のレースを即時実行）
  if not target_race:
    print('⚠️ 未来のターゲットが見つからないため、本日の最終レースを対象とします。')
    target_race = race_schedule[-1]
    target_race['target_time'] = now

  print(
      f'🎯 今回の実行ターゲット: 【{target_race["race_no"]}R】'
      f' (通知目標時刻: {target_race["target_time"].strftime("%H:%M")})'
  )

  # 3. 目標時刻まで待機
  now = datetime.now(jst)
  if now < target_race['target_time']:
    wait_seconds = (target_race['target_time'] - now).total_seconds()
    print(f'⏳ 目標時刻まで {int(wait_seconds)} 秒待機します...')
    time.sleep(wait_seconds)

  # 4. JACKALエンジン実行 ＆ Discord通知
  try:
    print(f'🚀 【JACKAL】 {target_race["race_no"]}R のエンジンを起動します...')
    result_text = run_jackal_engine(target_race['url'])
    send_to_discord(result_text)
  except Exception as e:
    print(f'❌ エラー発生: {e}')
    send_to_discord(f'⚠️ 【JACKAL】 {target_race["race_no"]}R の予測生成に失敗しました: {e}')

  # 5. 次のレースがあれば、セルフ・トリガーを発動してバトンタッチ！
  if next_race:
    print(f'📦 次のレース 【{next_race["race_no"]}R】 へバトンタッチ（セルフ・トリガー）します...')
    trigger_next_workflow(next_race['url'], minutes_before)
  else:
    print('🏁 本日の全レースが終了しました！お疲れ様でした！')


if __name__ == '__main__':
  main()

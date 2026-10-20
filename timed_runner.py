from datetime import datetime
import os
import time
import pytz
import requests
from bs4 import BeautifulSoup

# JST (日本時間) の設定
jst = pytz.timezone('Asia/Tokyo')


def get_race_schedule(base_url):
  """指定された日付・場の全レースのURLと発走時刻をスクレイピングして取得する"""
  print(f'🕷️ 各レースの発走時刻をスキャン＆過去レース判定中...')

  # ここにスクレイピング処理を記述（例としての構造）
  # 実際にはURLから各レースのページにアクセスするか、一覧ページから取得します
  # 今回の構成に合わせてレースリスト（dictのリスト）を構築します
  # 例: [{'race_no': 1, 'url': '...', 'start_time': datetime(...)}, ...]
  # 既存のスクレイピングロジックをそのままここに当てはめてください。
  pass


def trigger_next_workflow(next_race_url, minutes_before):
  """GitHub APIを使って次のレースのワークフローを自分自身でトリガーする（セルフ・トリガー）"""
  github_token = os.environ.get('GITHUB_TOKEN')
  repository = os.environ.get('GITHUB_REPOSITORY')  # 例: "owner/repo"

  if not github_token or not repository:
    print('⚠️ GITHUB_TOKEN または GITHUB_REPOSITORY が設定されていません。')
    return

  api_url = f'https://api.github.com/repos/{repository}/actions/workflows/timed_runner.yml/dispatches'

  headers = {
      'Authorization': f'Bearer {github_token}',
      'Accept': 'application/vnd.github.v3+json',
  }

  payload = {
      'ref': 'main',  # または master
      'inputs': {
          'race_url': next_race_url,
          'minutes_before': str(minutes_before),
      },
  }

  response = requests.post(api_url, json=payload, headers=headers)
  if response.status_code == 204:
    print('🚀 次のレースのセルフ・トリガー（予約）に成功しました！')
  else:
    print(
        f'❌ セルフ・トリガーに失敗しました: {response.status_code}'
        f' {response.text}'
    )


def run_jackal_engine(race_url):
  """JACKALエンジンを起動して予測＆Discord通知を行う"""
  print(f'🚀 【JACKAL】エンジンを起動します...')
  # ここにJACKALエンジンのメイン処理を記述
  # （Discord Webhook URLは os.environ.get('DISCORD_WEBHOOK_URL') から読み込む）
  print('📤 Discordへの通知に成功しました！')


def main():
  print('⏱️ JACKAL セルフ・トリガー型 タイムライン・スタンバイシステム起動！')

  # 環境変数やワークフローのinputsから起点URLを取得
  # 初回は手動、2回目以降はセルフ・トリガーの inputs.race_url から受け取る
  current_race_url = os.environ.get('RACE_URL')
  minutes_before = int(os.environ.get('MINUTES_BEFORE', 10))

  now = datetime.now(jst)
  print(f'🕒 現在時刻: {now.strftime("%Y-%m-%d %H:%M:%S")}')

  # 1. 全レースのスケジュールと発走時刻を取得
  race_schedule = get_race_schedule(current_race_url)

  # 2. 今回実行するターゲットのレースを特定
  target_race = None
  next_race = None

  for i, race in enumerate(race_schedule):
    # 発走の「minutes_before」分前を通知目標時刻とする
    target_time = race['start_time'] - timedelta(minutes=minutes_before)

    if now < target_time:
      target_race = race
      # さらに次のレースが存在すれば取得
      if i + 1 < len(race_schedule):
        next_race = race_schedule[i + 1]
      break

  if not target_race:
    print('🏁 本日の全レースの処理が完了しました。')
    return

  print(
      f'🎯 今回の実行ターゲット: 【{target_race["race_no"]}R】'
      f' (通知目標時刻: {target_race["target_time"].strftime("%H:%M")})'
  )

  # 3. 目標時刻まで time.sleep でじっくり待機（パブリックリポジトリなので時間制限ナシ！）
  now = datetime.now(jst)
  if now < target_race['target_time']:
    wait_seconds = (target_race['target_time'] - now).total_seconds()
    print(
        f'⏳ 目標時刻まで {int(wait_seconds)} 秒（約'
        f' {int(wait_seconds / 60)} 分）あります。待機します...'
    )
    time.sleep(wait_seconds)
  else:
    print('⚠️ すでに目標時刻を過ぎているため、すぐに実行します！')

  # 4. JACKALエンジン実行
  run_jackal_engine(target_race['url'])

  # 5. 次のレースがあればセルフ・トリガーを発動
  if next_race:
    print(f'📦 次のレース 【{next_race["race_no"]}R】 があります。セルフ・トリガーを実行します...')
    trigger_next_workflow(next_race['url'], minutes_before)
  else:
    print('🏁 今回の最後のレースが完了しました！')


if __name__ == '__main__':
  main()

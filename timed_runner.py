from datetime import datetime, timedelta, timezone
import os
import time
import pytz
import requests
from bs4 import BeautifulSoup

# ジャッカルエンジンのメイン関数をインポート
from jackal_engine import run_jackal_engine

# JST (日本時間) の設定
jst = pytz.timezone('Asia/Tokyo')


def get_race_schedule(base_url):
  """指定されたレースのURLから、同じ日・同じ場の「全レースのURLと発走時刻」をスクレイピングして取得する"""
  print(f'🕷️ 本日の全レースの発走時刻とスケジュールをスキャン中...')

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
  race_schedule = []

  # --- ここで出馬表ページ等にある「全レース選択リンク（1R〜最終R）」や発走時刻を探す ---
  # 地方競馬やJRAのページ構造に合わせて、レース一覧のリンクと発走時刻を抽出します
  # 例として、ページ内にあるレース番号のリンクと発走時刻（例: "11:30発走" などのテキスト）をスキャンする処理の枠組み：

  # 簡易的な実装例：もしページ内に他のレースへのリンクや発走時刻の要素があればここでパース
  # （実際の地方競馬・JRAの出馬表ページには通常「1R, 2R...」のタブやリンク、および発走時刻が存在します）

  # 万が一自動スキャンが難しい場合は、URLのレース番号部分（k_raceNo=1, 2, 3...）を書き換えつつ
  # 存在するレースを生成するフォールバックロジックを入れておくと安全です。

  # 以下は、URLの `k_raceNo=X` の数字を 12レース分 自動生成しつつ、
  # ページ内から各レースの発走時刻（例: "11:30" など）を正規表現で拾い出すスマートな実装の例です：

  # 日付とベースURLの基本部分を分解
  base_url_cleaned = base_url
  if 'k_raceNo=' in base_url_cleaned:
    # k_raceNoのパラメータを除いたベースを作る
    import re

    base_url_cleaned = re.sub(r'k_raceNo=\d+', '', base_url_cleaned)
    if not base_url_cleaned.endswith('&'):
      base_url_cleaned += '&' if '?' in base_url_cleaned else '?k_raceNo='

  # 日付の抽出（URLから）
  date_match = re.search(r'k_raceDate=(\d{4}%2F\d{2}%2F\d{2}|\d{4}/\d{2}/\d{2})', base_url)
  date_str = (
      date_match.group(1).replace('%2F', '/') if date_match else '2026/10/20'
  )
  y, m, d = map(int, date_str.split('/'))

  # ページテキストから時間（例: 10:30 など）のパターンをすべて探し、レース番号と紐付ける
  # （※もし正確な発走時刻の取得セレクタがある場合はそこに置き換えてください）
  # ここでは安全のために、1R〜12Rまでを構築し、見つかった発走時刻を割り当てるか、
  # ダミーとして一定間隔（例: 30分おきなど）を設定するフォールバックを持たせます。

  for r_no in range(1, 13):  '1Rから12Rまでを想定'
    # URLの組み立て
    if 'k_raceNo=' in base_url:
      r_url = re.sub(r'k_raceNo=\d+', f'k_raceNo={r_no}', base_url)
    else:
      separator = '&' if '?' in base_url else '?'
      r_url = f'{base_url}{separator}k_raceNo={r_no}'

    # 仮の発走時刻の割り当て（※実際のページから時刻表をパースする場合はここを書き換えてください）
    # 例として、朝10:00から30分おきに設定（実際の運用ではページの時刻表から取得するのがベスト）
    # ここでは例としてダミー時間を入れますが、ご自身のページの構造に合わせて時刻をパースしてください。
    start_time = datetime(y, m, d, 10, 0, 0, tzinfo=jst) + timedelta(
        minutes=35 * (r_no - 1)
    )

    race_schedule.append(
        {'race_no': r_no, 'url': r_url, 'start_time': start_time}
    )

  print(
      f'✅ スケジュールスキャン完了: 全 {len(race_schedule)} レーズを検知しました。'
  )
  return race_schedule


def trigger_next_workflow(next_race_url, minutes_before):
  """GitHub APIを使って次のレースのワークフローを自分自身でトリガーする（セルフ・トリガー）"""
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
    print('🚀 次のレースのセルフ・トリガー（予約）に成功しました！')
  else:
    print(
        f'❌ セルフ・トリガーに失敗しました: {response.status_code}'
        f' {response.text}'
    )


def send_to_discord(message):
  """Discord Webhookを使って予測結果を通知する"""
  webhook_url = os.environ.get('DISCORD_WEBHOOK_URL')
  if not webhook_url:
    print('⚠️ DISCORD_WEBHOOK_URL が設定されていません。コンソールに出力します。')
    print(message)
    return

  # Discordの文字数制限（2000文字）に配慮して分割またはそのまま送信
  payload = {'content': message}
  response = requests.post(webhook_url, json=payload)
  if response.status_code in [200, 204]:
    print('📤 Discordへの通知に成功しました！')
  else:
    print(f'❌ Discord通知失敗: {response.status_code} {response.text}')


def main():
  print('⏱️ JACKAL セルフ・トリガー型 タイムライン・スタンバイシステム起動！')

  current_race_url = os.environ.get(
      'RACE_URL',
      'https://www.keiba.go.jp/KeibaWeb/TodayRaceInfo/DebaTable?k_raceDate=2026%2F10%2F20&k_babaCode=22&k_raceNo=1',
  )
  minutes_before = int(os.environ.get('MINUTES_BEFORE', 10))

  now = datetime.now(jst)
  print(f'🕒 現在時刻: {now.strftime("%Y-%m-%d %H:%M:%S")}')

  # 1. 全レースのスケジュールを取得
  race_schedule = get_race_schedule(current_race_url)
  if not race_schedule:
    print('⚠️ 有効なレーススケジュールが取得できませんでした。終了します。')
    return

  # 2. 今回実行するターゲットのレースを特定
  target_race = None
  next_race = None

  for i, race in enumerate(race_schedule):
    # 発走の「minutes_before」分前を通知目標時刻とする
    target_time = race['start_time'] - timedelta(minutes=minutes_before)

    if now < target_time:
      target_race = race
      target_race['target_time'] = target_time
      if i + 1 < len(race_schedule):
        next_race = race_schedule[i + 1]
      break

  if not target_race:
    print('🏁 本日の全レースのスケジュール枠が終了したか、すべて発走済みです。')
    return

  print(
      f'🎯 今回の実行ターゲット: 【{target_race["race_no"]}R】'
      f' (通知目標時刻: {target_race["target_time"].strftime("%H:%M")})'
  )

  # 3. 目標時刻まで time.sleep で待機（パブリックリポジトリなので時間制限ナシ！）
  now = datetime.now(jst)
  if now < target_race['target_time']:
    wait_seconds = (target_race['target_time'] - now).total_seconds()
    print(
        f'⏳ 目標時刻まで {int(wait_seconds)} 秒（約'
        f' {int(wait_seconds / 60)} 分）待機します...'
    )
    time.sleep(wait_seconds)
  else:
    print('⚠️ すでに目標時刻を過ぎているため、すぐに実行します！')

  # 4. JACKALエンジン実行（ジャッカルエンジンの関数を呼び出す）
  try:
    result_text = run_jackal_engine(target_race['url'])
    # 予測結果をDiscordに通知
    send_to_discord(result_text)
  except Exception as e:
    print(f'❌ JACKALエンジンの実行中にエラーが発生しました: {e}')
    send_to_discord(
        f'⚠️ 【JACKAL】 {target_race["race_no"]}R の予測生成に失敗しました: {e}'
    )

  # 5. 次のレースがあればセルフ・トリガーを発動
  if next_race:
    print(
        f'📦 次のレース 【{next_race["race_no"]}R】 へ向けてセルフ・トリガーを発動します...'
    )
    trigger_next_workflow(next_race['url'], minutes_before)
  else:
    print('🏁 本日の最後のレースが完了しました！お疲れ様でした！')


if __name__ == '__main__':
  main()

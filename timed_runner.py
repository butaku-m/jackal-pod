from datetime import datetime, timedelta, timezone
import os
import re
import time
from bs4 import BeautifulSoup
import requests

# 既存のJACKALエンジンをインポート
from jackal_engine_github import run_jackal_engine


def send_discord_notification(message: str):
  """DiscordのWebhookに通知を送る（1900文字強制ガード付き）"""
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


def auto_detect_race_info_from_url(url: str):
  """URLから開催日・競馬場・レース番号をパースする（JRA/NAR完全分離版）"""
  jra_baba_map = {
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
  nar_baba_map = {
      '36': '門別',
      '3': '帯広',
      '10': '盛岡',
      '11': '水沢',
      '18': '浦和',
      '19': '船橋',
      '20': '大井',
      '21': '川崎',
      '22': '金沢',
      '23': '笠松',
      '24': '名古屋',
      '27': '園田',
      '28': '姫路',
      '31': '高知',
      '32': '佐賀',
  }

  r_date = '不明'
  r_place = '競馬'
  r_race_no = '1'

  # 1. JRA公式ドメインの処理
  if 'jra.go.jp' in url and 'CNAME=' in url:
    cname_match = re.search(r'CNAME=([a-zA-Z0-9]+)', url)
    if cname_match:
      cname_str = cname_match.group(1)
      if len(cname_str) >= 21:
        baba_cand = cname_str[9:11]
        r_place = jra_baba_map.get(baba_cand, 'JRA')
        race_cand = cname_str[19:21]
        if race_cand.isdigit():
          r_race_no = str(int(race_cand))
        if len(cname_str) >= 29:
          date_str = cname_str[21:29]
          if date_str.isdigit():
            r_date = f'{date_str[:4]}-{date_str[4:6]}-{date_str[6:]}'
    return r_date, f'{r_place}{r_race_no}R'

  # 2. 地方競馬(NAR)等の処理
  baba_code_match = re.search(r'(?:k_babaCode|babaCode|ba)=(\d+)', url)
  if baba_code_match:
    raw_code = baba_code_match.group(1)
    r_place = (
        nar_baba_map.get(raw_code)
        or nar_baba_map.get(raw_code.zfill(2))
        or '地方競馬'
    )

  race_no_match = re.search(r'(?:k_raceNo|race_no|r_no|raceNo|R_no)=(\d+)', url)
  if race_no_match:
    r_race_no = race_no_match.group(1)

  date_match = re.search(r'k_raceDate=(\d{4})/(\d{2})/(\d{2})', url)
  if date_match:
    y, m, d = date_match.groups()
    r_date = f'{y}-{m}-{d}'

  return r_date, f'{r_place}{r_race_no}R'


def derive_12_race_urls(base_1r_url: str):
  """1RのURLを起点に1R〜12RのURL群を自動生成（JRA・地方両対応）"""
  if 'jra.go.jp' in base_1r_url and 'CNAME=' in base_1r_url:
    cname_match = re.search(r'CNAME=([a-zA-Z0-9]+)', base_1r_url)
    if not cname_match:
      raise ValueError('URLにCNAMEが含まれていません。')

    cname_str = cname_match.group(1)
    if len(cname_str) < 21:
      raise ValueError('CNAME文字列の長さが足りません。')

    urls = []
    prefix = cname_str[:19]
    suffix = cname_str[21:]

    for race_no in range(1, 13):
      race_str = f'{race_no:02d}'
      new_cname = f'{prefix}{race_str}{suffix}'
      new_url = base_1r_url.replace(cname_str, new_cname)
      urls.append((race_no, new_url))
    return urls

  urls = []
  for race_no in range(1, 13):
    new_url = re.sub(
        r'(k_raceNo|raceNo|r_no|race_no|R_no)=\d+',
        f'k_raceNo={race_no}',
        base_1r_url,
    )
    if new_url == base_1r_url:
      urls.append((race_no, base_1r_url))
    else:
      urls.append((race_no, new_url))
  return urls


def extract_race_time_from_html(html_content: str):
  """ページ内のHTMLから発走時刻（例: '14:35'）を抽出する"""
  soup = BeautifulSoup(html_content, 'html.parser')
  text = soup.get_text()

  # JRAや地方競馬のページから時間パターン（HH:MM）を幅広くキャッチ
  time_match = re.search(r'(?:発走|予定)?[^\d]*(\d{1,2})[:：](\d{2})', text)
  if time_match:
    hour, minute = time_match.groups()
    h, m = int(hour), int(minute)
    if 9 <= h <= 21 and 0 <= m <= 59:
      return h, m

  return None, None


def trigger_next_workflow(next_race_url, minutes_before):
  """GitHub REST APIを使って、次のレースのURLを渡して自分自身のワークフローを再トリガーする"""
  github_token = os.environ.get('GITHUB_TOKEN') or os.environ.get('GH_PAT')
  repository = os.environ.get('GITHUB_REPOSITORY')

  if not github_token or not repository:
    print(
        '⚠️ GITHUB_TOKEN または GITHUB_REPOSITORY が設定されていないため、セルフ・トリガーをスキップします。'
    )
    return False

  workflow_file = 'timed_runner.yml'
  api_url = f'https://api.github.com/repos/{repository}/actions/workflows/{workflow_file}/dispatches'

  headers = {
      'Authorization': f'Bearer {github_token}',
      'Accept': 'application/vnd.github+json',
      'X-GitHub-Api-Version': '2022-11-28',
  }

  payload = {
      'ref': 'main',
      'inputs': {
          'race_url': next_race_url,
          'minutes_before': str(minutes_before),
      },
  }

  try:
    response = requests.post(api_url, headers=headers, json=payload)
    if response.status_code == 204:
      print('🚀 次のレースのセルフ・トリガー（予約）に成功しました！')
      return True
    else:
      print(
          f'❌ セルフ・トリガー失敗: ステータスコード {response.status_code} -'
          f' {response.text}'
      )
      return False
  except Exception as e:
    print(f'⚠️ セルフ・トリガー通信エラー: {e}')
    return False


def main():
  print('⏱️ JACKAL セルフ・トリガー型 タイムライン・スタンバイシステム起動！')

  base_1r_url = os.environ.get('RACE_URL')
  minutes_before_str = os.environ.get('MINUTES_BEFORE', '10')

  if not base_1r_url:
    print('⚠️ RACE_URL が設定されていないため終了します。')
    return

  minutes_before = int(minutes_before_str)
  
  # 💡 持ち込みの auto_detect_race_info_from_url で情報をきれいにログ出力！
  r_date, r_title = auto_detect_race_info_from_url(base_1r_url)
  print(f'🎯 【対象開催検知】 日付: {r_date} / 基準レース: {r_title}')
  print(f'🔗 起点URL: {base_1r_url}')
  print(f'⏳ 設定: 各レースの {minutes_before} 分前に通知します\n')

  headers = {
      'User-Agent': (
          'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
          ' (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36'
      ),
      'Accept': (
          'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8'
      ),
      'Accept-Language': 'ja,en-US;q=0.9,en;q=0.8',
      'Connection': 'keep-alive',
  }

  try:
    race_urls = derive_12_race_urls(base_1r_url)
    print(f'🔗 1R〜12RのURL生成完了（全{len(race_urls)}レース）')

    jst = timezone(timedelta(hours=9))
    now = datetime.now(jst)
    race_schedule = []

    print('🕷️ 各レースの発走時刻をスキャン＆過去レース判定中...')
    for race_no, url in race_urls:
      try:
        resp = requests.get(url, headers=headers, timeout=10)
        if resp.status_code == 200 and 'レース番組が見つかりません' not in resp.text:
          r_hour, r_minute = extract_race_time_from_html(resp.text)
          if r_hour is not None and r_minute is not None:
            r_datetime = now.replace(
                hour=r_hour, minute=r_minute, second=0, microsecond=0
            )
            target_time = r_datetime - timedelta(minutes=minutes_before)

            if now > target_time:
              print(
                  f'  - 【{race_no}R】 発走 {r_hour:02d}:{r_minute:02d}'
                  ' （既に時刻を過ぎているためスキップ ⏭️）'
              )
            else:
              race_schedule.append({
                  'race_no': race_no,
                  'url': url,
                  'race_time': f'{r_hour:02d}:{r_minute:02d}',
                  'target_time': target_time,
              })
              print(
                  f'  - 【{race_no}R】 発走 {r_hour:02d}:{r_minute:02d}'
                  f' (通知目標: {target_time.strftime("%H:%M")}) ✅ 対象'
              )
          else:
            print(
                f'  - 【{race_no}R】 発走時刻が検出できませんでした（スキップ）'
            )
        else:
          print(f'  - 【{race_no}R】 開催なし（スキップ）')
      except Exception as e:
        print(f'  - 【{race_no}R】 取得エラー: {e}')

      time.sleep(1)

    if not race_schedule:
      print(
          '❌ 本日これから実行すべき有効なレーススケジュールがありません。終了します。'
      )
      return

    current_task = race_schedule.pop(0)
    race_no = current_task['race_no']
    url = current_task['url']
    target_time = current_task['target_time']

    print(
        f'\n🎯 今回の実行ターゲット: 【{race_no}R】 (通知目標時刻:'
        f' {target_time.strftime("%H:%M")})'
    )

    now = datetime.now(jst)
    if now < target_time:
      wait_seconds = (target_time - now).total_seconds()
      print(
          f'⏳ 目標時刻まで {int(wait_seconds)} 秒（約'
          f' {int(wait_seconds / 60)} 分）待機します...'
      )
      time.sleep(wait_seconds)
    else:
      print('⚠️ すでに目標時刻を過ぎているため、すぐに実行します！')

    print(f'\n🚀 【{race_no}R】 JACKALエンジンを起動します...')
    try:
      result_text = run_jackal_engine(url)
      send_discord_notification(result_text)
      print(f'✅ 【{race_no}R】 予測＆Discord通知完了！')
    except Exception as e:
      print(f'❌ 【{race_no}R】 処理エラー: {e}')

    if race_schedule:
      next_task = race_schedule[0]
      print(
          f'\n📦 次のレース 【{next_task["race_no"]}R】'
          ' があります。セルフ・トリガーを実行します...'
      )
      trigger_next_workflow(next_task['url'], minutes_before)
    else:
      print('\n🎉 本日の全レースのスケジュールが完遂しました！お疲れ様です！')

  except Exception as e:
    print(f'⚠️ システムエラー: {e}')


if __name__ == '__main__':
  main()

from datetime import datetime, timedelta, timezone
import os
import re
import time
from bs4 import BeautifulSoup
import requests
from urllib.parse import urljoin

# 既存のJACKALエンジンをインポート
from jackal_engine_github import run_jackal_engine


def send_discord_notification(message: str):
  """DiscordのWebhookに通知を送る（1900文字強制ガード付き）"""
  webhook_url = os.environ.get('DISCORD_WEBHOOK_URL')
  if not webhook_url:
    print('⚠️ DISCORD_WEBHOOK_URL が設定されていないためスキップします。')
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


def save_prediction_log_to_file(race_title: str, message: str):
  """Discordに通知する内容をそのままローカルのlogs/フォルダにテキストとして蓄積する"""
  try:
    os.makedirs('logs', exist_ok=True)
    jst = timezone(timedelta(hours=9))
    today_str = datetime.now(jst).strftime('%Y-%m-%d')
    file_path = f'logs/{today_str}_jackal_predictions.txt'

    timestamp = datetime.now(jst).strftime('%Y-%m-%d %H:%M:%S')

    with open(file_path, 'a', encoding='utf-8') as f:
      f.write(f'========================================\n')
      f.write(f' 🎯 対象レース: {race_title} (保存時刻: {timestamp})\n')
      f.write(f'========================================\n\n')
      f.write(str(message))
      f.write('\n\n\n')

    print(f'📝 予測結果をローカルログに保存しました: {file_path}')
  except Exception as e:
    print(f'⚠️ ログファイル保存エラー: {e}')


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
      c_str = cname_match.group(1)
      if len(c_str) >= 11:
        baba_cand = c_str[9:11]
        r_place = jra_baba_map.get(baba_cand, 'JRA')
      if len(c_str) >= 10:
        race_cand = c_str[-10:-8]
        if race_cand.isdigit():
          r_race_no = str(int(race_cand))
      link_date = c_str[-8:]
      if len(link_date) == 8 and link_date.isdigit():
        r_date = f'{link_date[:4]}-{link_date[4:6]}-{link_date[6:]}'
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


def fetch_jra_race_links_from_base(base_url: str):
  headers = {
      'User-Agent': (
          'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
          ' (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36'
      ),
      'Accept': (
          'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8'
      ),
      'Accept-Language': 'ja,en-US;q=0.9,en;q=0.8',
  }

  print(f'🕷️ 起点URLを解析・スキャン中...')
  print(f'   ↳ {base_url}\n')

  base_cname_match = re.search(r'CNAME=([a-zA-Z0-9]+)', base_url)
  if not base_cname_match:
    print('⚠️ 起点URLにCNAMEが含まれていません。')
    return []

  base_cname = base_cname_match.group(1)
  target_date = base_cname[-8:]
  target_baba = base_cname[9:11] if len(base_cname) >= 11 else ''

  print(
      f'🎯 【解析されたターゲット】 日付: {target_date} / 競馬場コード部分:'
      f' {target_baba}'
  )

  try:
    response = requests.get(base_url, headers=headers, timeout=20)
    response.raise_for_status()
    response.encoding = response.apparent_encoding

    soup = BeautifulSoup(response.text, 'html.parser')
    collected_links = set()

    for a in soup.find_all('a', href=True):
      href = a['href'].strip()
      if 'accessD.html' in href and 'CNAME=' in href:
        full_url = urljoin(response.url, href)

        c_match = re.search(r'CNAME=([a-zA-Z0-9]+)', full_url)
        if c_match:
          c_str = c_match.group(1)
          link_date = c_str[-8:]
          link_baba = c_str[9:11] if len(c_str) >= 11 else ''

          if link_date == target_date and link_baba == target_baba:
            collected_links.add(full_url)

    unique_links = sorted(list(collected_links))
    print(
        f'🎉 フィルタリング成功！ 収穫された同日・同場のレースリンク:'
        f' {len(unique_links)}件\n'
    )
    return unique_links

  except Exception as e:
    print(f'⚠️ スクレイピングエラー: {e}')
    return []


def fetch_jra_full_timeline(base_url: str):
  headers = {
      'User-Agent': (
          'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
          ' (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36'
      ),
      'Accept': (
          'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8'
      ),
      'Accept-Language': 'ja,en-US;q=0.9,en;q=0.8',
  }

  race_urls = fetch_jra_race_links_from_base(base_url)
  if not race_urls:
    print('⚠️ レースリンクが取得できなかったため、処理を中断します。')
    return []

  print('⏱️ [Step 2] 各レースページを巡回して発走時刻をスキャン中...')
  timeline_data = []

  for link in race_urls:
    c_match = re.search(r'CNAME=([a-zA-Z0-9]+)', link)
    race_no_str = '??'
    if c_match:
      c_str = c_match.group(1)
      if len(c_str) >= 10:
        race_no_str = c_str[-10:-8]

    try:
      r_resp = requests.get(link, headers=headers, timeout=10)
      r_resp.encoding = r_resp.apparent_encoding
      r_soup = BeautifulSoup(r_resp.text, 'html.parser')
      r_text = r_soup.get_text(' ', strip=True)

      time_match = re.search(r'発走時刻[：:]\s*(\d{1,2})時(\d{1,2})分', r_text)
      if time_match:
        hour, minute = time_match.groups()
        time_str = f'{int(hour):02d}:{int(minute):02d}'
      else:
        time_str = '時刻不明'

      timeline_data.append(
          {
              'race_no': int(race_no_str) if race_no_str.isdigit() else 99,
              'time': time_str,
              'url': link,
          }
      )
      print(f'  [R{race_no_str}] 発走 {time_str} → 取得OK')

    except Exception as sub_e:
      print(f'  [R{race_no_str}] ⚠️ 時刻取得失敗: {sub_e}')
      timeline_data.append(
          {
              'race_no': int(race_no_str) if race_no_str.isdigit() else 99,
              'time': '取得エラー',
              'url': link,
          }
      )

  timeline_data = sorted(timeline_data, key=lambda x: x['race_no'])
  return timeline_data


def trigger_next_workflow(next_race_url, minutes_before):
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

  r_date, r_title = auto_detect_race_info_from_url(base_1r_url)
  print(f'🎯 【対象開催検知】 日付: {r_date} / 基準レース: {r_title}')
  print(f'🔗 起点URL: {base_1r_url}')
  print(f'⏳ 設定: 各レースの {minutes_before} 分前に通知します\n')

  jst = timezone(timedelta(hours=9))
  now = datetime.now(jst)
  race_schedule = []

  try:
    if 'jra.go.jp' in base_1r_url and 'CNAME=' in base_1r_url:
      print('🐎 JRA公式ドメインを検知：検証済みタイムラインビルダーを実行します...')
      timeline_data = fetch_jra_full_timeline(base_1r_url)

      for item in timeline_data:
        race_no = item['race_no']
        url = item['url']
        time_str = item['time']

        if time_str not in ('時刻不明', '取得エラー'):
          try:
            r_hour, r_minute = map(int, time_str.split(':'))
            r_datetime = now.replace(
                hour=r_hour, minute=r_minute, second=0, microsecond=0
            )
            target_time = r_datetime - timedelta(minutes=minutes_before)

            if now > target_time:
              print(
                  f'  - 【{race_no}R】 発走 {time_str}'
                  ' （既に時刻を過ぎているためスキップ ⏭️）'
              )
            else:
              race_schedule.append({
                  'race_no': race_no,
                  'url': url,
                  'race_time': time_str,
                  'target_time': target_time,
              })
              print(
                  f'  - 【{race_no}R】 発走 {time_str}'
                  f' (通知目標: {target_time.strftime("%H:%M")}) ✅ 対象'
              )
          except Exception as parse_e:
            print(f'  - 【{race_no}R】 時刻パースエラー: {parse_e}')
        else:
          print(f'  - 【{race_no}R】 時刻が有効ではないためスキップ')

    else:
      print(
          '🐴 地方競馬ドメインを検知：従来のURL置換ロジックを実行します...'
      )
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

      headers = {
          'User-Agent': (
              'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
              ' (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36'
          ),
          'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
          'Accept-Language': 'ja,en-US;q=0.9,en;q=0.8',
      }

      for race_no, url in urls:
        try:
          resp = requests.get(url, headers=headers, timeout=10)
          resp.encoding = resp.apparent_encoding
          if (
              resp.status_code == 200
              and 'レース番組が見つかりません' not in resp.text
          ):
            soup = BeautifulSoup(resp.text, 'html.parser')
            text = soup.get_text(' ', strip=True)
            time_match = re.search(
                r'(?:発走|予定)?[^\d]*(\d{1,2})[:：](\d{2})', text
            )
            if time_match:
              r_hour, r_minute = map(int, time_match.groups()[:2])
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
          time.sleep(1)
        except Exception as e:
          print(f'  - 【{race_no}R】 取得エラー: {e}')

    if not race_schedule:
      print(
          '❌ 本日これから実行すべき有効なレーススケジュールがありません。終了します。'
      )
      return

    current_task = race_schedule.pop(0)
    race_no = current_task['race_no']
    url = current_task['url']
    target_time = current_task['target_time']

    # 現在のレースの正式なタイトルを再検出しておく
    _, current_race_title = auto_detect_race_info_from_url(url)

    print(
        f'\n🎯 今回の実行ターゲット: 【{current_race_title}】 (通知目標時刻:'
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

    print(f'\n🚀 【{current_race_title}】 JACKALエンジンを起動します...')
    try:
      result_text = run_jackal_engine(url)

      # 1. Discordに通知
      send_discord_notification(result_text)

      # 2. 🌟 ローカルのテキストファイルに結果を自動蓄積！
      save_prediction_log_to_file(current_race_title, result_text)

      print(f'✅ 【{current_race_title}】 予測・Discord通知・ローカル保存完了！')
    except Exception as e:
      print(f'❌ 【{current_race_title}】 処理エラー: {e}')

    if race_schedule:
      next_task = race_schedule[0]
      _, next_race_title = auto_detect_race_info_from_url(next_task['url'])
      print(
          f'\n📦 次のレース 【{next_race_title}】'
          ' があります。セルフ・トリガーを実行します...'
      )
      trigger_next_workflow(next_task['url'], minutes_before)
    else:
      print('\n🎉 本日の全レースのスケジュールが完遂しました！お疲れ様です！')

  except Exception as e:
    print(f'⚠️ システムエラー: {e}')


if __name__ == '__main__':
  main()

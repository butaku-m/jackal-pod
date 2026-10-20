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
      if len(cname_str) >= 11:
        baba_cand = cname_str[9:11]
        r_place = jra_baba_map.get(baba_cand, 'JRA')
      # Cname構造からレース番号を安全に抽出（末尾日付の直前2桁、または19〜21文字目付近）
      digits_8 = re.findall(r'\d{8}', cname_str)
      if digits_8:
        d_idx = cname_str.rfind(digits_8[-1])
        if d_idx >= 2:
          race_cand = cname_str[d_idx - 2 : d_idx]
          if race_cand.isdigit():
            r_race_no = str(int(race_cand))
        r_date = digits_8[-1]
        r_date = f'{r_date[:4]}-{r_date[4:6]}-{r_date[6:]}'
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
  """【JRA絶対ベース】任意のJRAレースURLを起点に、同日・同場の1R〜12R直リンクを完璧に収穫する"""
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

  base_cname_match = re.search(r'CNAME=([a-zA-Z0-9]+)', base_url)
  if not base_cname_match:
    return []

  base_cname = base_cname_match.group(1)
  target_date = base_cname[-8:]
  target_baba = base_cname[9:11] if len(base_cname) >= 11 else ''

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

    return sorted(list(collected_links))
  except Exception as e:
    print(f'⚠️ JRAリンク収穫エラー: {e}')
    return []


def derive_12_race_urls(base_url: str):
  """JRAなら絶対インデクサー、地方(NAR)なら従来の置換ロジックを使って1R〜12RのURL群を返す"""
  if 'jra.go.jp' in base_url and 'CNAME=' in base_url:
    print('🐎 JRA公式ドメインを検知：絶対インデクサーで全レースリンクを収穫します...')
    race_urls = fetch_jra_race_links_from_base(base_url)
    formatted_urls = []
    for link in race_urls:
      c_match = re.search(r'CNAME=([a-zA-Z0-9]+)', link)
      race_no = 99
      if c_match:
        c_str = c_match.group(1)
        digits_8 = re.findall(r'\d{8}', c_str)
        if digits_8:
          d_idx = c_str.rfind(digits_8[-1])
          if d_idx >= 2 and c_str[d_idx - 2 : d_idx].isdigit():
            race_no = int(c_str[d_idx - 2 : d_idx])
      formatted_urls.append((race_no, link))
    # レース番号順にソート
    return sorted(formatted_urls, key=lambda x: x[0])

  # 地方競馬(NAR)等の処理
  urls = []
  for race_no in range(1, 13):
    new_url = re.sub(
        r'(k_raceNo|raceNo|r_no|race_no|R_no)=\d+',
        f'k_raceNo={race_no}',
        base_url,
    )
    if new_url == base_url:
      urls.append((race_no, base_url))
    else:
      urls.append((race_no, new_url))
  return urls


def extract_race_time_from_html(html_content: str):
  """ページ内のHTMLから発走時刻（例: '14:35'）を抽出する（JRAの「発走時刻：XX時XX分」にも完全対応）"""
  soup = BeautifulSoup(html_content, 'html.parser')
  text = soup.get_text(' ', strip=True)

  # JRA特有の「発走時刻：XX時XX分」パターンを最優先でキャッチ
  time_match_jra = re.search(r'発走時刻[：:]\s*(\d{1,2})時(\d{1,2})分', text)
  if time_match_jra:
    hour, minute = time_match_jra.groups()
    h, m = int(hour), int(minute)
    if 0 <= h <= 23 and 0 <= m <= 59:
      return h, m

  # 一般的な時刻パターン (HH:MM)
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
        resp.encoding = resp.apparent_encoding

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
                  f'  - 【{race_no}R】 発走 {r_hour:02d}:{r_minute:02

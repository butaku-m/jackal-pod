from datetime import datetime
import os
import re
import time
from bs4 import BeautifulSoup
import requests

# AIエンジン（軽量化・買い目＆根拠抽出型）をインポート
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


def auto_detect_race_info_from_url(url: str):
  """URLから開催日・競馬場・レース番号をパースする（中央＆地方完全対応版）"""
  jra_baba_map = {
      '01': '札幌', '02': '函館', '03': '福島', '04': '新潟', '05': '東京',
      '06': '中山', '07': '中京', '08': '京都', '09': '阪神', '10': '小倉',
  }
  nar_baba_map = {
      '36': '門別', '3': '帯広', '10': '盛岡', '11': '水沢', '18': '浦和',
      '19': '船橋', '20': '大井', '21': '川崎', '22': '金沢', '23': '笠松',
      '24': '名古屋', '27': '園田', '28': '姫路', '31': '高知', '32': '佐賀',
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
    r_place = nar_baba_map.get(raw_code) or nar_baba_map.get(raw_code.zfill(2)) or '地方競馬'

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
  # JRAの場合
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

  # 地方競馬（NAR）などの場合（k_raceNo=1 などを置き換え）
  urls = []
  for race_no in range(1, 13):
    # URL内のレース番号パラメータを 1〜12 に置換する
    new_url = re.sub(r'(k_raceNo|raceNo|r_no|race_no|R_no)=\d+', f'k_raceNo={race_no}', base_1r_url)
    if new_url == base_1r_url:
      # 万が一パラメータが見つからない場合はそのまま追加
      urls.append((race_no, base_1r_url))
    else:
      urls.append((race_no, new_url))
  return urls


def main():
  print('🚀 JACKAL 中央＆地方対応 一括バッチシステム起動！')

  # ★ここに検証したい開催日の「1RのURL」をペタッと貼る！
  base_1r_url = 'https://www.keiba.go.jp/KeibaWeb/TodayRaceInfo/DebaTable?k_raceDate=2026/10/19&k_raceNo=1&k_babaCode=10'

  # URLの形式チェック（HTTPで始まっているか）
  if not base_1r_url or not base_1r_url.startswith('http'):
    print('⚠️ 有効な1RのURLを入力してください。')
    return

  try:
    r_date, r_title = auto_detect_race_info_from_url(base_1r_url)
    print(f'🎯 【起点URL検知】 日付: {r_date} / 基準レース: {r_title}')
    
    race_list = derive_12_race_urls(base_1r_url)
    print(f'🔗 1R〜12RのURL生成完了！（全{len(race_list)}レース）\n')

    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36',
        'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
        'Accept-Language': 'ja,en-US;q=0.9,en;q=0.8',
        'Connection': 'keep-alive',
    }

    for race_no, url in race_list:
      print(f'🏁 【{race_no}R】 スクレイピング＆JACKAL推論中...')
      
      try:
        resp = requests.get(url, headers=headers, timeout=10)
        if resp.status_code == 200 and 'レース番組が見つかりません' not in resp.text:
          # JACKALエンジンで解析＆推論実行
          result_text = run_jackal_engine(url)
          
          # Discordへ連投
          send_discord_notification(result_text)
          print(f'✅ 【{race_no}R】 送信完了！')
        else:
          print(f'⏩ 【{race_no}R】 番組なし・または開催なし（スキップ）')
      except Exception as e:
        print(f'❌ 【{race_no}R】 処理エラー: {e}')

      time.sleep(3)

    print('\n🎉 全レースのJACKAL予測＆Discord通知が完了しました！')

  except Exception as e:
    print(f'⚠️ システムエラー: {e}')


if __name__ == '__main__':
  main()

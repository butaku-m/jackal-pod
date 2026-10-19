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
    new_url = re.sub(r'(k_raceNo|raceNo|r_no|race_no|R_no)=\d+', f'k_raceNo={race_no}', base_1r_url)
    if new_url == base_1r_url:
      urls.append((race_no, base_1r_url))
    else:
      urls.append((race_no, new_url))
  return urls


def extract_race_time_from_html(html_content: str):
  """ページ内のHTMLから発走時刻（例: '14:35'）を抽出する"""
  soup = BeautifulSoup(html_content, 'html.parser')
  text = soup.get_text()

  time_match = re.search(r'(?:発走|予定)?[^\d]*(\d{1,2})[:：](\d{2})', text)
  if time_match:
    hour, minute = time_match.groups()
    h, m = int(hour), int(minute)
    if 9 <= h <= 21 and 0 <= m <= 59:
      return h, m
  
  return None, None


def main():
  print('⏱️ JACKAL 全レース対応タイムライン・スタンバイシステム起動（終了レーススキップ版）！')

  base_1r_url = os.environ.get('RACE_URL')
  minutes_before_str = os.environ.get('MINUTES_BEFORE', '10')

  if not base_1r_url:
    print('⚠️ RACE_URL が設定されていません。')
    return

  minutes_before = int(minutes_before_str)
  print(f'🔗 起点URL: {base_1r_url}')
  print(f'⏳ 設定: 各レースの {minutes_before} 分前に通知します\n')

  headers = {
      'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36',
      'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
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
            r_datetime = now.replace(hour=r_hour, minute=r_minute, second=0, microsecond=0)
            target_time = r_datetime - timedelta(minutes=minutes_before)
            
            # 【パッチ追加】すでに通知目標時刻を過ぎているレースはスキップ対象にする
            if now > target_time:
              print(f'  - 【{race_no}R】 発走 {r_hour:02d}:{r_minute:02d} （既に時刻を過ぎているためスキップします ⏭️）')
            else:
              race_schedule.append({
                  'race_no': race_no,
                  'url': url,
                  'race_time': f'{r_hour:02d}:{r_minute:02d}',
                  'target_time': target_time
              })
              print(f'  - 【{race_no}R】 発走 {r_hour:02d}:{r_minute:02d} (通知目標: {target_time.strftime("%H:%M")}) ✅ 待機対象')
          else:
            print(f'  - 【{race_no}R】 発走時刻が検出できませんでした（スキップ）')
        else:
          print(f'  - 【{race_no}R】 開催なし（スキップ）')
      except Exception as e:
        print(f'  - 【{race_no}R】 取得エラー: {e}')
      
      time.sleep(1)

    if not race_schedule:
      print('❌ 本日これから実行すべき有効なレーススケジュールがありません（すべて終了済みの可能性があります）。終了します。')
      return

    print(f'\n🎯 合計 {len(race_schedule)} レースの監視スケジュールを設定しました。レース開催を待ちます...\n')

    # タイムラインに沿って監視・実行
    while race_schedule:
      now = datetime.now(jst)
      
      current_task = race_schedule[0]
      target_time = current_task['target_time']
      race_no = current_task['race_no']
      url = current_task['url']
      
      if now >= target_time:
        print(f'\n🚀 【{race_no}R】 発走{minutes_before}分前到達！JACKALエンジンを起動します...')
        try:
          result_text = run_jackal_engine(url)
          send_discord_notification(result_text)
          print(f'✅ 【{race_no}R】 予測＆Discord通知完了！')
        except Exception as e:
          print(f'❌ 【{race_no}R】 処理エラー: {e}')
        
        race_schedule.pop(0)
      else:
        time.sleep(30)

    print('\n🎉 本日の対象レースのJACKAL予測・通知スケジュールがすべて完了しました！')

  except Exception as e:
    print(f'⚠️ システムエラー: {e}')


If __name__ == '__main__':
  main()

from datetime import datetime, timedelta
import time
from bs4 import BeautifulSoup
import requests

# 以前作ったJACKALエンジン（表を削って買い目と根拠を返す安定版）をインポート
from jackal_engine_github import run_jackal_engine


def send_discord_notification(message: str):
  """DiscordのWebhookに通知を送る（強制文字数ガード付き）"""
  webhook_url = os.environ.get('DISCORD_WEBHOOK_URL') if 'os' in globals() else None
  # ※環境変数がない場合のフォールバック（直接入れるか環境変数で設定）
  if not webhook_url:
    import os
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


def parse_race_info_and_time(html_content, url):
  """HTMLからレース名（例: 東京11R 天皇賞(秋)）と「発走時刻」（例: 15:40）を抽出し、日付と結合する"""
  soup = BeautifulSoup(html_content, 'html.parser')
  
  # 発走時刻のパターンを検索（例: "15:40" のような文字列）
  # JRAの出馬表ページ内にある発走時刻要素を正規表現でキャッチ
  page_text = soup.get_text()
  time_match = re.search(r'(\d{1,2})時(\d{2})分', page_text)
  race_time_str = "15:00" # デフォルト値
  
  if time_match:
    h, m = time_match.groups()
    race_time_str = f"{int(h):02d}:{int(m):02d}"
  else:
    # 別の形式（15:40など）を探す
    time_match_alt = re.search(r'([0-2]\d:[0-5]\d)', page_text)
    if time_match_alt:
      race_time_str = time_match_alt.group(1)

  return race_time_str


def screening_weekend_races(target_dates):
  """指定された日付リスト（例: ['20261017', '20261018']）と全主要競馬場コードから

     有効なレースURL、レースタイトル、発走時刻を自動収集する
  """
  headers = {
      'User-Agent': (
          'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36'
      )
  }

  # JRAの主要競馬場コードマップ
  venue_map = {
      '01': '札幌', '02': '函館', '03': '福島', '04': '新潟', '05': '東京',
      '06': '中山', '07': '中京', '08': '京都', '09': '阪神', '10': '小倉'
  }

  active_races = []

  print('🔍 土日全場のレーススクリーニングを開始します...')

  for date_str in target_dates:
    # YYYYMMDD を YYYY-MM-DD に変換
    formatted_date = f"{date_str[:4]}-{date_str[4:6]}-{date_str[6:]}"

    for venue_code, venue_name in venue_map.items():
      for race_no in range(1, 13):
        race_no_str = f'{race_no:02d}'
        # JRAのCNAME構造に基づくURL生成
        base_prefix = 'pw01dde01'
        cname = f'{base_prefix}{venue_code}20260406{race_no_str}{date_str}/D0'
        url = f'https://www.jra.go.jp/JRADB/accessD.html?CNAME={cname}'

        try:
          response = requests.get(url, headers=headers, timeout=3)
          if response.status_code == 200:
            if 'レース番組が見つかりません' not in response.text and len(response.text) > 2000:
              # 発走時刻を抽出
              race_time = parse_race_info_and_time(response.text, url)
              race_title = f"{venue_name}{race_no}R"
              
              target_dt_str = f"{formatted_date} {race_time}"
              target_datetime = datetime.strptime(target_dt_str, '%Y-%m-%d %H:%M')

              active_races.append({
                  'date': formatted_date,
                  'venue': venue_name,
                  'race_no': race_no,
                  'title': race_title,
                  'url': url,
                  'race_time': race_time,
                  'target_datetime': target_datetime,
                  'executed': False  # 実行済みフラグ
              })
              print(f'✅ 【発見】 {formatted_date} {venue_name} {race_no}R (発走: {race_time})')
        except Exception:
          pass  # 存在しない競馬場や通信エラーはスキップ

  return active_races


def main():
  import re
  print('🚀 JRA全自動レーシング・タイマーシステム起動！')

  # 今週末（あるいはスキャンしたい土日）の日付を指定
  target_dates = ['20261017', '20261018'] # 必要に応じて変更

  # 1. まず全レースのURLと発走時刻をスクリーニング
  races = screening_weekend_races(target_dates)
  print(f'\n🎯 監視対象レース総数: {len(races)}件\n')

  if not races:
    print('⚠️ 有効なレースが見つかりませんでした。日付やURL構造を確認してください。')
    return

  print('⏳ 各レースの「発走30分前」に向けた監視ループに入ります……（Ctrl+Cで停止可能）\n')

  # 2. リアルタイム監視＆30分前トリガー一个ループ
  while True:
    now = datetime.now()
    all_done = True

    for race in races:
      if race['executed']:
        continue

      all_done = False
      # 発走の30分前を計算
      trigger_time = race['target_datetime'] - timedelta(minutes=30)

      # 現在時刻がトリガー時刻を過ぎていて、かつ発走時刻をまだ過ぎていない場合
      if now >= trigger_time and now < race['target_datetime']:
        print(f"\n🚨 【発走30分前到達】 {race['date']} {race['title']} のJACKALエンジンを起動します！")
        
        try:
          # JACKALエンジンで分析＆推論実行
          result_text = run_jackal_engine(race['url'])
          # Discordへ送信
          send_discord_notification(result_text)
        except Exception as e:
          err_msg = f"❌ {race['title']} 処理エラー: {str(e)}"
          print(err_msg)
          send_discord_notification(err_msg)

        # 実行済みフラグを立てる
        race['executed'] = True

    # すべてのレースが終了したらループを抜ける
    if all_done:
      print('🎉 今週末の全監視レースの処理が完了しました！システムを終了します。')
      break

    # 30秒ごとに時刻をチェック
    time.sleep(30)


if __name__ == '__main__':
  main()

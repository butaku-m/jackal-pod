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
  """URLから開催日・競馬場・レース番号をパースする（100点満点ロジック）"""
  jra_baba_map = {
      '01': '札幌', '02': '函館', '03': '福島', '04': '新潟', '05': '東京',
      '06': '中山', '07': '中京', '08': '京都', '09': '阪神', '10': '小倉',
  }
  
  if 'jra.go.jp' in url and 'CNAME=' in url:
    cname_match = re.search(r'CNAME=([a-zA-Z0-9]+)', url)
    if cname_match:
      cname_str = cname_match.group(1)
      if len(cname_str) >= 21:
        baba_cand = cname_str[9:11]
        r_place = jra_baba_map.get(baba_cand, 'JRA')
        
        race_cand = cname_str[19:21]
        r_race_no = str(int(race_cand)) if race_cand.isdigit() else '1'
        
        r_date = '不明'
        if len(cname_str) >= 29:
          date_str = cname_str[21:29]
          if date_str.isdigit():
            r_date = f'{date_str[:4]}-{date_str[4:6]}-{date_str[6:]}'
            
        return r_date, f'{r_place}{r_race_no}R'
  
  return '不明', 'JRAレース'


def derive_12_race_urls(base_1r_url: str):
  """1RのURLのCNAME(インデックス19:21)を書き換えて1R〜12RのURL群を自動生成"""
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


def main():
  print('🚀 JACKAL 1R起点一括バッチシステム起動！')

  # ★ここに開催日の「1RのURL」をペタッと貼るだけ！
  base_1r_url = 'https://www.jra.go.jp/JRADB/accessD.html?CNAME=pw01dde0105202604060120261017/D0'

  if not base_1r_url or 'CNAME=' not in base_1r_url:
    print('⚠️ 有効な1RのURLを入力してください。')
    return

  try:
    r_date, r_title = auto_detect_race_info_from_url(base_1r_url)
    print(f'🎯 【起点URL検知】 日付: {r_date} / 基準レース: {r_title}')
    
    # 1R〜12RのURLを一気に自動展開
    race_list = derive_12_race_urls(base_1r_url)
    print(f'🔗 1R〜12RのURL生成完了！（全{len(race_list)}レース）\n')

    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36'
    }

    # 1Rから12Rまで順番に推論＆Discord送信
    for race_no, url in race_list:
      print(f'🏁 【{race_no}R】 スレイピング＆JACKAL推論中...')
      
      # ページの存在チェック（無効なレースはスキップ）
      resp = requests.get(url, headers=headers, timeout=5)
      if resp.status_code == 200 and 'レース番組が見つかりません' not in resp.text:
        try:
          # JACKALエンジンで解析＆推論実行
          result_text = run_jackal_engine(url)
          
          # Discordへ連投
          send_discord_notification(result_text)
          print(f'✅ 【{race_no}R】 送信完了！')
        except Exception as e:
          err_msg = f'❌ 【{race_no}R】 推論・送信エラー: {e}'
          print(err_msg)
          send_discord_notification(err_msg)
      else:
        print(f'⏩ 【{race_no}R】 番組なし（スキップ）')

      # 連続アクセス対策のウェイト
      time.sleep(3)

    print('\n🎉 全レースのJACKAL予測＆Discord通知が完了しました！')

  except Exception as e:
    print(f'⚠️ システムエラー: {e}')


if __name__ == '__main__':
  main()

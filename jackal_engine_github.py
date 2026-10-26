from datetime import datetime, timezone
from io import StringIO
import os
import re
import time
from bs4 import BeautifulSoup
from google import genai
import pandas as pd
import requests


def run_jackal_engine(target_url):
  # API初期化（GitHubのSecretsから安全に取得）
  api_key = os.environ.get('GEMINI_API_KEY')
  if not api_key:
    raise ValueError('GEMINI_API_KEY が環境変数に設定されていません。')

  client = genai.Client(api_key=api_key)

  # 1. プロンプトはリポジトリ内から読み込む
  prompt_path = 'jackal_prompt.txt'
  try:
    with open(prompt_path, 'r', encoding='utf-8') as f:
      jackal_prompt_instruction = f.read()
    print('✅ リポジトリ内からJACKALプロンプトを正常に読み込みました！')
  except FileNotFoundError:
    print(f'⚠️ 指定されたパスにファイルが見つかりません: {prompt_path}')
    jackal_prompt_instruction = 'あなたは競馬構造化・確率算出エンジンJACKALである。'

  # 2. スクレイピング実行（ブラウザ完全なりすましセッション）
  print(f'🕷️ スクレイピング実行中: {target_url}')
  session = requests.Session()
  headers = {
      'User-Agent': (
          'Mozilla/5.0 (Windows NT 10.0; Win64; x64) '
          'AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36'
      ),
      'Accept': (
          'text/html,application/xhtml+xml,application/xml;q=0.9,'
          'image/avif,image/webp,image/apng,*/*;q=0.8'
      ),
      'Accept-Language': 'ja,en-US;q=0.9,en;q=0.8',
      'Referer': 'https://www.keiba.go.jp/',
      'Connection': 'keep-alive',
  }

  try:
    response = session.get(target_url, headers=headers, timeout=15)
    response.encoding = response.apparent_encoding
  except Exception as e:
    raise Exception(f'接続エラーが発生しました: {e}')

  if response.status_code != 200:
    raise Exception(
        f'HTTPエラー: {response.status_code}'
        ' (サイト側でアクセスが制限されているか、URLが無効です)'
    )

  html_content = response.text
  soup = BeautifulSoup(html_content, 'html.parser')
  page_text = soup.get_text()

  # 3. 日付・開催場・レース番号の自動抽出（JRA/NAR完全分離・誤判定ブロック版）
  def auto_detect_race_info(text, url):
    jra_baba_map = {
        '01': '札幌', '02': '函館', '03': '福島', '04': '新潟', '05': '東京',
        '06': '中山', '07': '中京', '08': '京都', '09': '阪神', '10': '小倉',
    }
    nar_baba_map = {
        '36': '門別', '3': '帯広', '10': '盛岡', '11': '水沢', '18': '浦和',
        '19': '船橋', '20': '大井', '21': '川崎', '22': '金沢', '23': '笠松',
        '24': '名古屋', '27': '園田', '28': '姫路', '31': '高知', '32': '佐賀',
    }

    r_date = datetime.now(timezone.utc).strftime('%Y-%m-%d')
    r_place = '競馬'
    r_race_no = '1'

    # 日付の抽出
    date_match = re.search(r'k_raceDate=(\d{4})/(\d{2})/(\d{2})', url)
    if date_match:
      y, m, d = date_match.groups()
      r_date = f'{y}-{m}-{d}'
    else:
      all_dates = re.findall(r'(20\d{2})(\d{2})(\d{2})', url)
      if all_dates:
        y, m, d = all_dates[-1]
        r_date = f'{y}-{m}-{d}'

    # JRAの判定
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
      return r_date, f'{r_place}{r_race_no}R'

    # 地方競馬(NAR)の判定（k_babaCodeを最優先で取得し、Jraマップの混入を防ぐ）
    baba_code_match = re.search(r'(?:k_babaCode|babaCode|ba)=(\d+)', url)
    if baba_code_match:
      raw_code = baba_code_match.group(1)
      r_place = nar_baba_map.get(raw_code) or nar_baba_map.get(raw_code.zfill(2)) or '地方競馬'

    race_no_match = re.search(r'(?:k_raceNo|race_no|r_no|raceNo|R_no)=(\d+)', url)
    if race_no_match:
      r_race_no = race_no_match.group(1)

    return r_date, f'{r_place}{r_race_no}R'

  race_date, race_title = auto_detect_race_info(page_text, target_url)

  # 4. 前処理
  def pure_fact_preprocessing(raw_df):
    df = raw_df.copy()
    columns_to_keep = [
        col for col in df.columns if col not in ['Python_Preprocessed_Score']
    ]
    df = df[columns_to_keep]
    for col in df.select_dtypes(include=['object']):
      df[col] = df[col].astype(str).str.strip()

    total_horses = len(df)
    missing_odds_count = (
        df['単勝オッズ'].isna().sum() if '単勝オッズ' in df.columns else 0
    )
    fact_summary = (
        f'[SYSTEM FACT SUMMARY]: Total_Entries={total_horses},'
        f' Missing_Odds_Count={missing_odds_count}'
    )
    df.attrs['Fact_Summary'] = fact_summary
    return df

  tables = pd.read_html(StringIO(html_content))
  if not tables:
    raise Exception('テーブルデータが見つかりませんでした。')

  raw_df = tables[0]
  processed_df = pure_fact_preprocessing(raw_df)
  fact_summary = processed_df.attrs.get('Fact_Summary', '')

  # 🚀 2段階分割モデル推論（Step 1: オッズ完全BLIND能力算出 ➔ Step 2: Market Layer照合・買い目構築）
  models_to_try = [
      'gemini-3.8-flash',
      'gemini-3.6-flash',
      'gemini-3.5-flash-lite',
  ]

  step1_result = None
  used_model = ''

  # ==========================================
  # 🟢 STEP 1: オッズ完全非含有データでの能力・確率算出
  # ==========================================
  blind_df = processed_df.drop(
      columns=[col for col in processed_df.columns if 'オッズ' in col or '人気' in col or '単勝' in col],
      errors='ignore'
  )
  blind_table_text = blind_df.to_markdown(index=False)
  step1_target = (
      f'{fact_summary}\n\n{blind_table_text}\n\n[TARGET RACE]: {race_date} {race_title}\n\n'
      '[INSTRUCTION]: これはSTEP 1（予測フェーズ）である。オッズ情報は一切存在しない。'
      '各馬の能力・適性・展開・Model Prob・Fair Oddsを純粋なデータのみから算出してリストを確定させよ。'
  )

  retry_keywords = ['503', '429', 'disconnected', 'Connection', 'timeout']

  for model_name in models_to_try:
    success = False
    for attempt in range(3):
      try:
        print(f'🔄 [Step 1] モデル [{model_name}] で能力・確率を算出中 (試行 {attempt + 1}/3)...')
        response1 = client.models.generate_content(
            model=model_name,
            contents=(
                jackal_prompt_instruction
                + '\n\n[STEP 1: PREDICTION PHASE (ODDS BLIND)]\n'
                + step1_target
            ),
        )
        step1_result = response1.text
        used_model = model_name
        success = True
        break
      except Exception as e:
        print(f'⚠️ [Step 1] モデル [{model_name}] エラー (試行 {attempt + 1}): {e}')
        if any(kw in str(e) for kw in retry_keywords):
          print('⏳ サーバー混雑・切断のため、5秒後に再試行します...')
          time.sleep(5)
        else:
          break
    if success:
      break

  if step1_result is None:
    raise Exception('Step 1（能力・確率算出）の生成に失敗しました。')

  # ==========================================
  # 🟢 STEP 2: 確定した確率とリアルタイムオッズの突合・買い目構築
  # ==========================================
  full_table_text = processed_df.to_markdown(index=False)
  step2_target = (
      f'{fact_summary}\n\n{full_table_text}\n\n[TARGET RACE]: {race_date} {race_title}\n\n'
      f'[STEP 1 FIXED RESULT (PROBABILITY & BASE ANALYSIS)]:\n{step1_result}\n\n'
      '[INSTRUCTION]: これはSTEP 2（市場レイヤー）である。'
      'すでに確定したモデル確率と、上記の【最新オッズを含む全データ】を突合させよ。'
      'Market Edge、Conservative EV、Pruning Filter、および鉄の掟（絶対的NO BET判定）を適用し、'
      '指定されたスマホ対応リスト形式および最終フォーマットで結果を出力せよ。'
  )

  api_response = None
  for attempt in range(3):
    try:
      print(f'🔄 [Step 2] モデル [{used_model}] でオッズ照合・買い目構築中 (試行 {attempt + 1}/3)...')
      api_response = client.models.generate_content(
          model=used_model,
          contents=(
              jackal_prompt_instruction
              + '\n\n[STEP 2: MARKET LAYER & BETTING EXECUTION]\n'
              + step2_target
          ),
      )
      break
    except Exception as e:
      print(f'⚠️ [Step 2] エラー (試行 {attempt + 1}): {e}')
      if any(kw in str(e) for kw in retry_keywords):
        print('⏳ サーバー混雑・切断のため、5秒後に再試行します...')
        time.sleep(5)
      else:
        break

  if api_response is None:
    raise Exception('Step 2（買い目構築）の生成に失敗しました。')

  final_text = api_response.text

  # 結果を返す
  return (
      f'🎯 **JACKAL 予測結果** ({race_date} {race_title} / 2-Step Pipeline)\n\n'
      f'{final_text}'
  )

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
  markdown_table_text = processed_df.to_markdown(index=False)
  fact_summary = processed_df.attrs.get('Fact_Summary', '')

  # AIにはテーブルを渡すが、出力には絶対含めないよう強力に指示
  strict_output_instruction = (
      '\n\n[STRICT OUTPUT FORMAT RULE - OVERRIDE]: '
      '1. 出力には長大な出走表テーブル（Markdownの表など）を一切含めないこと。表を出力した時点で失敗とみなします。'
      '2. 軸馬、推奨買い目・資金配分、および投資根拠のみを簡潔に出力すること。'
  )

  execution_target = (
      f'{fact_summary}\n\n{markdown_table_text}\n\n[TARGET RACE]: {race_date}'
      f' {race_title}' + strict_output_instruction
  )

  # 🚀 モデル推論
  models_to_try = [
      'gemini-3.8-flash',
      'gemini-3.6-flash',
      'gemini-3.5-flash-lite',
  ]

  api_response = None
  used_model = ''

  for model_name in models_to_try:
    success = False
    for attempt in range(3):
      try:
        print(f'🔄 モデル [{model_name}] で推論中 (試行 {attempt + 1}/3)...')
        api_response = client.models.generate_content(
            model=model_name,
            contents=(
                jackal_prompt_instruction
                + '\n\n[TARGET & STRUCTURED PURE RAW FACT DATA SOURCE]\n'
                + execution_target
            ),
        )
        used_model = model_name
        success = True
        break
      except Exception as e:
        print(f'⚠️ モデル [{model_name}] エラー (試行 {attempt + 1}): {e}')
        if '503' in str(e) or '429' in str(e):
          print('⏳ サーバー混雑のため、5秒後に再試行します...')
          time.sleep(5)
        else:
          break

    if success:
      break

  if api_response is None:
    raise Exception(
        'すべてのモデルでの生成に失敗しました（サーバー混雑の可能性があります）。'
    )

  raw_text = api_response.text

  # 🛡️ 【強制テーブル除去フィルター】AIが万が一表を出してきたらここで完全に削り取る！
  def force_strip_markdown_tables(text: str) -> str:
    lines = text.split('\n')
    cleaned = []
    for line in lines:
      # マークダウンの表の区切りやセル（'|' が含まれる行）をスキップ
      if '|' in line and ('---' in line or '馬番' in line or '馬名' in line or line.strip().startswith('|')):
        continue
      cleaned.append(line)
    return '\n'.join(cleaned)

  final_cleaned_text = force_strip_markdown_tables(raw_text)

  # 結果を返す
  return (
      f'🎯 **JACKAL 予測結果** ({race_date} {race_title} / {used_model})\n\n'
      f'{final_cleaned_text}'
  )

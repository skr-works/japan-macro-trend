import os
import json
import base64
import datetime
import requests
import pandas as pd
import yfinance as yf
import jpholiday

# --- 定数設定 ---
TICKERS = {
    "Copper": "HG=F",      # [稼ぎ] 銅
    "JGB_ETF": "1475.T",   # [信用] 日本国債
    "Oil": "BZ=F",         # [物理コスト] 原油
    "Nasdaq": "^NDX",      # [デジタルコスト] ナスダック
    "USDJPY": "JPY=X",     # [換算] ドル円
    "US_Rate": "^TNX"      # [圧力] 米金利
}

# 表示用ラベル
LABELS = {
    "Copper": "銅 (輸出需要)",
    "JGB_ETF": "日本国債ETF",
    "Cost_Index": "輸入コスト指数 (原油×IT)",
    "USDJPY": "ドル円",
    "US_Rate": "米10年債金利",
    "Oil": "原油",
    "Nasdaq": "ナスダック"
}

# チャート・アイコン用カラー
COLORS = {
    "Copper": "#ff7f0e",     # オレンジ
    "JGB_ETF": "#9467bd",    # 紫
    "Cost_Index": "#d62728", # 赤
    "USDJPY": "#2ca02c",     # 緑
    "US_Rate": "#7f7f7f",    # グレー
    "Oil": "#8c564b",        # 茶 (補助)
    "Nasdaq": "#17becf"      # 水色 (補助)
}

def get_jst_now():
    """現在時刻(JST)を取得"""
    return datetime.datetime.now(datetime.timezone(datetime.timedelta(hours=9)))

def is_market_holiday():
    """日本の祝日・土日判定"""
    now_jst = get_jst_now()
    today = now_jst.date()
    
    # 土日 (5=Sat, 6=Sun)
    if today.weekday() >= 5:
        return True
    # 祝日 (jpholiday)
    if jpholiday.is_holiday(today):
        return True
    return False

def get_market_data():
    """Yahoo Financeからデータ取得＆整形"""
    print("Fetching market data...")
    end_date = datetime.datetime.now()
    start_date = end_date - datetime.timedelta(days=500) # トレンド判定用に長めに取得

    # データ取得
    raw_df = yf.download(list(TICKERS.values()), start=start_date, end=end_date, progress=False)['Close']
    
    # yfinanceのバージョンによるMultiIndex対応
    if isinstance(raw_df.columns, pd.MultiIndex):
        raw_df.columns = raw_df.columns.droplevel(1)
    
    # 欠損値補完 (Fill Forward)
    raw_df = raw_df.fillna(method='ffill')
    
    # 輸入コスト指数 (Cost Index) の計算: 原油 * ナスダック
    raw_df['Cost_Index'] = raw_df[TICKERS['Oil']] * raw_df[TICKERS['Nasdaq']]
    
    return raw_df

def analyze_trends(raw_df):
    """365日前と比較してトレンド(UP/DOWN/FLAT)を判定"""
    current_data = raw_df.iloc[-1]
    
    # 365日前の近似データを探す
    target_date = raw_df.index[-1] - datetime.timedelta(days=365)
    idx_365 = raw_df.index.get_indexer([target_date], method='nearest')[0]
    old_data = raw_df.iloc[idx_365]

    trends = {}
    ratios = {}
    
    # 判定対象のキー（TICKERSのキー + Cost_Index）
    # ※原油とナスダック単体はCost_Indexに含まれるため判定の主役ではないが、比率は計算しておく
    check_keys = list(TICKERS.keys()) + ['Cost_Index']
    
    # Tickerマップ（内部キー -> Tickerシンボル）
    ticker_map = TICKERS.copy()
    ticker_map['Cost_Index'] = 'Cost_Index' # 計算済み列

    for key in check_keys:
        col_name = ticker_map[key]
        
        val_now = current_data[col_name]
        val_old = old_data[col_name]
        
        if val_old == 0: ratio = 1.0 # ゼロ除算回避
        else: ratio = val_now / val_old
        
        ratios[key] = ratio
        
        # 判定基準: ±5%
        if ratio >= 1.05:
            trends[key] = "UP"
        elif ratio <= 0.95:
            trends[key] = "DOWN"
        else:
            trends[key] = "FLAT"
            
    return trends, ratios, current_data

def diagnose_economy(trends):
    """10パターンの景気判定ロジック"""
    
    # 変数ショートカット
    cop = trends["Copper"]
    jgb = trends["JGB_ETF"]
    cost = trends["Cost_Index"]
    uj = trends["USDJPY"]
    rate = trends["US_Rate"]

    # --- Priority 1: クライシス判定 ---
    if jgb == "DOWN" and uj == "UP":
        return {"level": "critical", "name": "日本売り (トリプル安)", "desc": "国債価格の急落(金利急騰)と円安が連鎖しています。財政への信認低下リスクがある危険な状態です。"}
    
    if cop == "DOWN" and cost == "UP":
        return {"level": "danger", "name": "スタグフレーション", "desc": "不況下の物価高。稼ぐ力(輸出需要)が落ちているのに、輸入コストだけが上昇している最悪の経済状態です。"}

    # --- Priority 2: 悪いインフレ・構造的搾取 ---
    if cop == "FLAT" and cost == "UP" and uj == "UP":
        return {"level": "warning", "name": "デジタル赤字貧乏", "desc": "輸出は横ばいですが、ITコスト増(デジタル赤字)と円安のダブルパンチで国富が流出しています。"}
    
    if cop == "UP" and cost == "UP" and uj == "UP":
        return {"level": "warning", "name": "利益なき繁忙 (コストプッシュ)", "desc": "売上は立っていますが、仕入れコスト増と行き過ぎた円安で利益が圧迫されています。"}
    
    if cop == "DOWN" and cost == "UP":
        return {"level": "warning", "name": "供給ショック・資源インフレ", "desc": "世界需要は弱いですが、戦争や供給制約などでコスト高になっています。"}
    
    if rate == "UP" and cost == "UP" and uj == "UP":
        return {"level": "warning", "name": "米独り勝ち (日米格差)", "desc": "米国金利と米国株(コスト)だけが高く、資金が米国へ吸い上げられている状態です。"}

    # --- Priority 3: 良いインフレ・健全な成長 ---
    if cop == "UP" and (cost == "FLAT" or cost == "DOWN"):
        return {"level": "safe", "name": "黄金期 (高次元バランス)", "desc": "輸出需要が強く、かつ輸入コストは落ち着いています。交易条件が改善する理想的な好況です。"}
    
    if cop == "UP" and uj == "UP":
        return {"level": "safe", "name": "昭和型ブーム (輸出ボーナス)", "desc": "円安と輸出増が噛み合い、輸出企業が利益を最大化する伝統的な勝ちパターンです。"}

    # --- Priority 4: デフレ・不況 ---
    if cop == "DOWN" and uj == "DOWN":
        return {"level": "stagnation", "name": "円高不況", "desc": "急激な円高により、輸出産業の競争力が削がれ、業績が悪化しています。"}
    
    if cop == "DOWN" and cost == "DOWN":
        return {"level": "stagnation", "name": "世界同時不況 (デフレ回帰)", "desc": "需要もコストも縮小中。世界的なリセッションにより、経済活動が停滞しています。"}

    # --- その他 ---
    return {"level": "other", "name": "トレンド交錯", "desc": "明確なパターンに当てはまりません。個別の動きを注視してください。"}

def generate_html(raw_df, trends, ratios, current_data, diagnosis):
    """WordPress投稿用のHTML生成 (Chart.js含む)"""
    
    # --- チャートデータ作成 (365日分, 起点=100) ---
    chart_df = raw_df.tail(365).copy()
    normalized_df = chart_df.div(chart_df.iloc[0]).mul(100).round(2)
    
    # 必要な列を日本語ラベルに変換
    plot_data = {}
    display_keys = ["Copper", "JGB_ETF", "Cost_Index", "USDJPY", "US_Rate"]
    
    for key in display_keys:
        col_key = TICKERS.get(key, key) # Cost_Indexはそのまま
        series = normalized_df[col_key].fillna(method='ffill')
        plot_data[LABELS[key]] = series.tolist()

    chart_labels = normalized_df.index.strftime('%Y/%m/%d').tolist()
    
    # Chart.js Dataset作成
    datasets = []
    for label_jp, data_list in plot_data.items():
        # 逆引きでキーを取得して色を決定
        key_code = [k for k, v in LABELS.items() if v == label_jp][0]
        color = COLORS.get(key_code, "#333")
        
        datasets.append({
            "label": label_jp,
            "data": data_list,
            "borderColor": color,
            "backgroundColor": color,
            "borderWidth": 2,
            "pointRadius": 0,
            "pointHoverRadius": 5,
            "fill": False,
            "tension": 0.2
        })

    json_labels = json.dumps(chart_labels)
    json_datasets = json.dumps(datasets)

    # --- 診断結果のスタイル定義 ---
    style_map = {
        "critical":   {"bg": "#ffebee", "text": "#b71c1c", "border": "#d32f2f"}, # 赤
        "danger":     {"bg": "#ffecb3", "text": "#e65100", "border": "#ff8f00"}, # 濃いオレンジ
        "warning":    {"bg": "#fff8e1", "text": "#f57f17", "border": "#ffca28"}, # 黄
        "safe":       {"bg": "#e8f5e9", "text": "#1b5e20", "border": "#43a047"}, # 緑
        "stagnation": {"bg": "#e3f2fd", "text": "#0d47a1", "border": "#1e88e5"}, # 青
        "other":      {"bg": "#f5f5f5", "text": "#424242", "border": "#9e9e9e"}  # グレー
    }
    st = style_map.get(diagnosis['level'], style_map["other"])

    # --- HTML構築 ---
    last_update = get_jst_now().strftime('%Y-%m-%d %H:%M')
    
    html = f"""
    <div style="font-family: -apple-system, BlinkMacSystemFont, 'Helvetica Neue', sans-serif; max-width: 800px; margin: 0 auto; color: #333;">
        <p style="text-align: right; font-size: 0.8rem; color: #888;">Data Updated: {last_update} (JST)</p>

        <div style="background: {st['bg']}; border-left: 6px solid {st['border']}; padding: 20px; border-radius: 4px; margin-bottom: 30px; box-shadow: 0 2px 5px rgba(0,0,0,0.05);">
            <div style="font-size: 0.9rem; color: {st['text']}; font-weight: bold; margin-bottom: 5px;">現在の日本経済フェーズ</div>
            <h2 style="margin: 0 0 10px 0; color: {st['text']}; font-size: 1.6rem;">{diagnosis['name']}</h2>
            <p style="margin: 0; font-size: 1.05rem; line-height: 1.6;">{diagnosis['desc']}</p>
        </div>

        <h3 style="font-size: 1.1rem; border-bottom: 2px solid #eee; padding-bottom: 10px; margin-bottom: 20px;">主要指標のトレンド (対365日前比)</h3>
        <div style="display: grid; grid-template-columns: repeat(auto-fit, minmax(140px, 1fr)); gap: 15px; margin-bottom: 30px;">
    """

    icons = {"UP": "📈", "FLAT": "➡️", "DOWN": "📉"}
    
    for key in display_keys:
        trend = trends[key]
        ratio = ratios[key]
        label = LABELS[key]
        icon = icons[trend]
        
        # 数値フォーマット
        raw_val = current_data[TICKERS.get(key, 'Cost_Index')] if key != 'Cost_Index' else current_data['Cost_Index']
        fmt_val = f"{raw_val:,.0f}" if key == "JGB_ETF" else f"{raw_val:,.2f}"
        if key == "Cost_Index": fmt_val = "-" # 指数は生値を出さない

        # トレンド色
        t_color = "#333"
        if trend == "UP": t_color = "#d32f2f"
        elif trend == "DOWN": t_color = "#1976d2"

        html += f"""
            <div style="background: #fff; border: 1px solid #e0e0e0; border-radius: 8px; padding: 15px; text-align: center; box-shadow: 0 1px 3px rgba(0,0,0,0.05);">
                <div style="font-size: 0.75rem; color: #666; font-weight: bold; height: 32px; display: flex; align-items: center; justify-content: center;">{label}</div>
                <div style="font-size: 2rem; margin: 5px 0;">{icon}</div>
                <div style="font-size: 1.1rem; font-weight: bold; color: {t_color};">x {ratio:.2f}</div>
                <div style="font-size: 0.7rem; color: #999; margin-top: 5px;">現在: {fmt_val}</div>
            </div>
        """

    html += """
        </div>

        <details style="margin-bottom: 40px; background: #fafafa; border: 1px solid #eee; border-radius: 6px;">
            <summary style="padding: 15px; cursor: pointer; font-weight: bold; outline: none; color: #555;">🧐 景気判定ロジックの解説 (クリックで開閉)</summary>
            <div style="padding: 0 20px 20px 20px; font-size: 0.9rem; line-height: 1.7; border-top: 1px solid #eee;">
                <p>現在値と365日前を比較し、以下の優先順位で自動判定しています。</p>
                
                <h4 style="margin: 15px 0 5px 0; color: #d32f2f;">Priority 1: クライシス・危険</h4>
                <ul style="margin: 0; padding-left: 20px;">
                    <li><strong>日本売り:</strong> 国債下落 ＋ 円安</li>
                    <li><strong>スタグフレーション:</strong> 銅(需要)下落 ＋ 輸入コスト増</li>
                </ul>

                <h4 style="margin: 15px 0 5px 0; color: #f57f17;">Priority 2: 構造的課題・警戒</h4>
                <ul style="margin: 0; padding-left: 20px;">
                    <li><strong>デジタル赤字貧乏:</strong> 輸出横ばい ＋ ITコスト増 ＋ 円安</li>
                    <li><strong>利益なき繁忙:</strong> 輸出増 ＋ コスト増 ＋ 円安</li>
                    <li><strong>米独り勝ち:</strong> 米金利高 ＋ コスト増 ＋ 円安</li>
                </ul>

                <h4 style="margin: 15px 0 5px 0; color: #2e7d32;">Priority 3: 健全な成長</h4>
                <ul style="margin: 0; padding-left: 20px;">
                    <li><strong>黄金期:</strong> 銅上昇 ＋ コスト安定</li>
                    <li><strong>昭和型ブーム:</strong> 銅上昇 ＋ 円安 (輸出ボーナス)</li>
                </ul>
            </div>
        </details>

        <h3 style="font-size: 1.1rem; border-bottom: 2px solid #eee; padding-bottom: 10px;">過去365日の相対パフォーマンス (起点=100)</h3>
        <p style="font-size: 0.75rem; color: #888; margin-bottom: 10px;">※ 凡例クリックで表示切替可能です</p>
        
        <div style="position: relative; width: 100%; height: 450px; border: 1px solid #eee; border-radius: 4px; padding: 10px; background: #fff;">
            <canvas id="j_economy_chart"></canvas>
        </div>

        <script src="https://cdn.jsdelivr.net/npm/chart.js"></script>
        <script>
        (function() {
            const ctx = document.getElementById('j_economy_chart').getContext('2d');
            new Chart(ctx, {
                type: 'line',
                data: {
                    labels: """ + json_labels + """,
                    datasets: """ + json_datasets + """
                },
                options: {
                    responsive: true,
                    maintainAspectRatio: false,
                    interaction: { mode: 'index', intersect: false },
                    plugins: {
                        legend: {
                            position: 'bottom',
                            labels: { usePointStyle: true, padding: 20, font: {size: 11} }
                        },
                        tooltip: {
                            mode: 'index', intersect: false,
                            backgroundColor: 'rgba(255, 255, 255, 0.95)',
                            titleColor: '#333', bodyColor: '#333', borderColor: '#ddd', borderWidth: 1
                        }
                    },
                    scales: {
                        y: {
                            grid: { color: '#f5f5f5' },
                            title: { display: true, text: '相対指数 (Start=100)' }
                        },
                        x: { grid: { display: false }, ticks: { maxTicksLimit: 8 } }
                    },
                    elements: { point: { radius: 0, hitRadius: 10, hoverRadius: 5 } }
                }
            });
        })();
        </script>
    </div>
    """
    return html

def push_to_pipeline(content):
    """
    データパイプライン(実態はWordPress)へデータを送信
    環境変数は汎用的な名称(API_ENDPOINT等)で読み込む
    """
    # 難読化されたSecretsの読み込み
    pipeline_conf = os.environ.get("DATA_PIPELINE_CREDENTIALS", "")
    conf = {}
    
    # "KEY=VALUE" 形式のテキストをパース
    for line in pipeline_conf.splitlines():
        if "=" in line:
            k, v = line.split("=", 1)
            conf[k.strip()] = v.strip()

    # マッピング: 抽象名 -> WPパラメータ
    api_url = conf.get("API_ENDPOINT")  # WP_URL
    user_id = conf.get("CLIENT_ID")     # WP_USER
    secret  = conf.get("CLIENT_SECRET") # WP_PASSWORD
    target  = conf.get("RESOURCE_TARGET") # PAGE_ID

    if not all([api_url, user_id, secret, target]):
        print("Pipeline configuration incomplete.")
        return

    # WordPress API エンドポイント構築
    endpoint = f"{api_url.rstrip('/')}/wp-json/wp/v2/pages/{target}"
    
    # 認証トークン生成
    creds = f"{user_id}:{secret}"
    token = base64.b64encode(creds.encode()).decode('utf-8')
    
    headers = {
        'Authorization': f'Basic {token}',
        'Content-Type': 'application/json'
    }
    payload = {'content': content}

    print(f"Pushing data to endpoint: {endpoint}...")
    
    try:
        res = requests.post(endpoint, headers=headers, json=payload)
        if res.status_code == 200:
            print("Data push successful.")
        else:
            print(f"Data push failed: {res.status_code}")
            # セキュリティのためレスポンス詳細はログに出さない
    except Exception as e:
        print(f"Connection error: {e}")

if __name__ == "__main__":
    # 1. 休日チェック
    if is_market_holiday():
        print("Market holiday. Skipping execution.")
        exit(0)

    try:
        # 2. データ取得
        raw_df = get_market_data()
        
        # 3. トレンド分析
        trends, ratios, current_data = analyze_trends(raw_df)
        
        # 4. 診断ロジック
        diagnosis = diagnose_economy(trends)
        
        # 5. HTML生成
        html_content = generate_html(raw_df, trends, ratios, current_data, diagnosis)
        
        # 6. 外部送信 (隠蔽されたWP)
        push_to_pipeline(html_content)
        
    except Exception as e:
        print("An error occurred during execution.")
        import traceback
        traceback.print_exc()
        exit(1)

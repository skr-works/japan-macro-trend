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
    "Copper": "HG=F",       # [稼ぎ] 銅
    "JGB_ETF": "1475.T",    # [信用] 日本国債
    "Oil": "BZ=F",          # [製造業コスト] 原油
    "Nasdaq": "QQQ",        # [ITコスト] ナスダックETF
    "USDJPY": "JPY=X",      # [換算] ドル円
    "US_Rate": "^TNX"       # [圧力] 米金利
}

# 表示用ラベル
LABELS = {
    "Copper": "銅 (輸出需要)",
    "JGB_ETF": "日本国債ETF",
    "Oil": "原油 (製造コスト)",
    "Nasdaq": "ナスダック (ITコスト)",
    "USDJPY": "ドル円",
    "US_Rate": "米10年債金利"
}

# チャート・アイコン用カラー
COLORS = {
    "Copper": "#ff7f0e",     # オレンジ
    "JGB_ETF": "#9467bd",    # 紫
    "Oil": "#8c564b",        # 茶
    "Nasdaq": "#17becf",     # 水色
    "USDJPY": "#2ca02c",     # 緑
    "US_Rate": "#7f7f7f"     # グレー
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
    start_date = end_date - datetime.timedelta(days=550) # トレンド判定用に十分長めに取得

    # データ取得
    raw_df = yf.download(list(TICKERS.values()), start=start_date, end=end_date, progress=False)['Close']
    
    # yfinanceのバージョンによるMultiIndex対応
    if isinstance(raw_df.columns, pd.MultiIndex):
        raw_df.columns = raw_df.columns.droplevel(1)
    
    # 欠損値補完 (修正箇所1: Fill Forward)
    raw_df = raw_df.ffill()

    # 【重要】全ての列がNaNの行（休日やデータ取得直後の空行）を削除
    raw_df = raw_df.dropna(how='all')
    
    return raw_df

def analyze_trends(raw_df):
    """365日前と比較してトレンド(UP/DOWN/FLAT)を判定"""
    current_data = raw_df.iloc[-1]
    
    # 365日前の近似データを探す
    target_date = raw_df.index[-1] - datetime.timedelta(days=365)
    
    # 過去データが十分にあるか確認
    if target_date < raw_df.index[0]:
        idx_365 = 0
    else:
        idx_365 = raw_df.index.get_indexer([target_date], method='nearest')[0]
        
    old_data = raw_df.iloc[idx_365]

    trends = {}
    ratios = {}
    
    # 全てのTickerを判定対象とする
    for key, ticker in TICKERS.items():
        col_name = ticker
        
        # データが存在しない場合のガード
        if col_name not in current_data or pd.isna(current_data[col_name]):
            ratios[key] = 1.0
            trends[key] = "FLAT"
            continue

        val_now = current_data[col_name]
        val_old = old_data[col_name]
        
        if val_old == 0 or pd.isna(val_old): 
            ratio = 1.0
        else: 
            ratio = val_now / val_old
        
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
    """10パターンの景気判定ロジック (原油とNasdaqを分離版)"""
    
    # 変数ショートカット
    cop = trends["Copper"]
    jgb = trends["JGB_ETF"]
    oil = trends["Oil"]
    nas = trends["Nasdaq"]
    uj = trends["USDJPY"]
    rate = trends["US_Rate"]

    # コスト高判定（どちらか一方でも上がっていればコスト増圧力ありとみなす）
    is_cost_up = (oil == "UP" or nas == "UP")
    # コスト安判定（両方とも下がっている、あるいは安定）
    is_cost_down_or_flat = (oil != "UP" and nas != "UP")

    # --- Priority 1: クライシス判定 ---
    if jgb == "DOWN" and uj == "UP":
        return {"level": "critical", "name": "日本売り (トリプル安)", "desc": "国債価格の急落(金利急騰)と円安が連鎖しています。財政への信認低下リスクがある危険な状態です。"}
    
    if cop == "DOWN" and is_cost_up:
        return {"level": "danger", "name": "スタグフレーション", "desc": "不況下の物価高。稼ぐ力(輸出需要)が落ちているのに、輸入コスト(原油またはIT)が上昇している最悪の経済状態です。"}

    # --- Priority 2: 悪いインフレ・構造的搾取 ---
    # デジタル赤字貧乏: Nasdaqの上昇を条件にする
    if cop == "FLAT" and nas == "UP" and uj == "UP":
        return {"level": "warning", "name": "デジタル赤字貧乏", "desc": "輸出は横ばいですが、ITコスト増(ナスダック高)と円安のダブルパンチで国富が流出しています。"}
    
    # 利益なき繁忙: 原油またはNasdaqの上昇
    if cop == "UP" and is_cost_up and uj == "UP":
        cost_factor = "IT" if nas == "UP" else "資源"
        if nas == "UP" and oil == "UP": cost_factor = "資源とIT"
        return {"level": "warning", "name": "利益なき繁忙 (コストプッシュ)", "desc": f"売上は立っていますが、仕入れコスト({cost_factor})増と行き過ぎた円安で利益が圧迫されています。"}
    
    # 供給ショック: 主に原油高
    if cop == "DOWN" and oil == "UP":
        return {"level": "warning", "name": "供給ショック・資源インフレ", "desc": "世界需要は弱いですが、戦争や供給制約などで原油価格が高騰しています。"}
    
    # 米独り勝ち: Nasdaq高(株高)と金利高
    if rate == "UP" and nas == "UP" and uj == "UP":
        return {"level": "warning", "name": "米独り勝ち (日米格差)", "desc": "米国金利と米国株だけが高く、資金が米国へ吸い上げられている状態です。"}

    # --- Priority 3: 良いインフレ・健全な成長 ---
    if cop == "UP" and is_cost_down_or_flat:
        return {"level": "safe", "name": "黄金期 (高次元バランス)", "desc": "輸出需要が強く、かつ輸入コスト(原油・IT)は落ち着いています。交易条件が改善する理想的な好況です。"}
    
    if cop == "UP" and uj == "UP":
        return {"level": "safe", "name": "昭和型ブーム (輸出ボーナス)", "desc": "円安と輸出増が噛み合い、輸出企業が利益を最大化する伝統的な勝ちパターンです。"}

    # --- Priority 4: デフレ・不況 ---
    if cop == "DOWN" and uj == "DOWN":
        return {"level": "stagnation", "name": "円高不況", "desc": "急激な円高により、輸出産業の競争力が削がれ、業績が悪化しています。"}
    
    # 世界同時不況: 全部下がり
    if cop == "DOWN" and oil == "DOWN" and nas == "DOWN":
        return {"level": "stagnation", "name": "世界同時不況 (デフレ回帰)", "desc": "需要も、資源価格も、IT株価も縮小中。世界的なリセッションにより経済活動が停滞しています。"}

    # --- その他 ---
    return {"level": "other", "name": "トレンド交錯", "desc": "明確なパターンに当てはまりません。個別の動きを注視してください。"}

def generate_html(raw_df, trends, ratios, current_data, diagnosis):
    """WordPress投稿用のHTML生成"""
    
    # --- チャートデータ作成 (正確に過去365日分) ---
    target_date = raw_df.index[-1] - datetime.timedelta(days=365)
    chart_df = raw_df[raw_df.index >= target_date].copy()
    
    # 最初の行を100として正規化
    first_row = chart_df.iloc[0].replace(0, 1) 
    normalized_df = chart_df.div(first_row).mul(100).round(2)
    
    # 必要な列を日本語ラベルに変換
    plot_data = {}
    display_keys = ["Copper", "JGB_ETF", "Oil", "Nasdaq", "USDJPY", "US_Rate"]
    
    for key in display_keys:
        col_key = TICKERS[key]
        if col_key in normalized_df:
            # 修正箇所2: .ffill()に変更
            series = normalized_df[col_key].ffill()
            plot_data[LABELS[key]] = series.tolist()

    chart_labels = normalized_df.index.strftime('%Y/%m/%d').tolist()
    
    # Chart.js Dataset作成
    datasets = []
    for label_jp, data_list in plot_data.items():
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
    html = f"""
    <div style="font-family: -apple-system, BlinkMacSystemFont, 'Helvetica Neue', sans-serif; max-width: 800px; margin: 0 auto; color: #333;">

        <div style="background: {st['bg']}; border-left: 6px solid {st['border']}; padding: 20px; border-radius: 4px; margin-bottom: 30px; box-shadow: 0 2px 5px rgba(0,0,0,0.05);">
            <div style="font-size: 0.85rem; color: {st['text']}; font-weight: bold; margin-bottom: 5px;">現在の日本経済フェーズ</div>
            <h3 style="margin: 0 0 10px 0; color: {st['text']}; font-size: 1.4rem;">{diagnosis['name']}</h3>
            <p style="margin: 0; font-size: 1.0rem; line-height: 1.6;">{diagnosis['desc']}</p>
        </div>

        <h4 style="font-size: 1.0rem; border-bottom: 2px solid #eee; padding-bottom: 10px; margin-bottom: 20px; color: #555;">主要指標のトレンド (対365日前比)</h4>
        <div style="display: grid; grid-template-columns: repeat(auto-fit, minmax(140px, 1fr)); gap: 15px; margin-bottom: 30px;">
    """

    icons = {"UP": "📈", "FLAT": "➡️", "DOWN": "📉"}
    display_keys = ["Copper", "JGB_ETF", "Oil", "Nasdaq", "USDJPY", "US_Rate"]
    
    for key in display_keys:
        trend = trends[key]
        ratio = ratios[key]
        label = LABELS[key]
        icon = icons[trend]
        
        if TICKERS[key] in current_data:
            raw_val = current_data[TICKERS[key]]
            fmt_val = f"{raw_val:,.0f}" if key == "JGB_ETF" else f"{raw_val:,.2f}"
        else:
            fmt_val = "-"

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
            <summary style="padding: 15px; cursor: pointer; font-weight: bold; outline: none; color: #555;">景気判定ロジックの解説 (クリックで開閉)</summary>
            <div style="padding: 0 20px 20px 20px; font-size: 0.9rem; line-height: 1.8; border-top: 1px solid #eee;">
                <p style="margin-bottom: 20px;">現在値と365日前を比較し、各指標の組み合わせから経済状態を自動判定しています。</p>
                
                <h5 style="margin: 20px 0 10px 0; border-left: 4px solid #d32f2f; padding-left: 10px; color: #333;">🔴 危険領域 (クライシス)</h5>
                <div style="margin-bottom: 15px;">
                    <strong style="color: #d32f2f;">日本売り (トリプル安)</strong><br>
                    <span style="font-size: 0.8rem; color: #666; background: #eee; padding: 2px 6px; border-radius: 4px;">国債下落</span> ＋ <span style="font-size: 0.8rem; color: #666; background: #eee; padding: 2px 6px; border-radius: 4px;">円安</span><br>
                    国債が売られて金利が急騰する中で、通貨安（円安）も止まらない状態です。国家財政への信認が揺らぎ、資金が日本から逃避している危険なサインです。
                </div>
                <div>
                    <strong style="color: #e65100;">スタグフレーション</strong><br>
                    <span style="font-size: 0.8rem; color: #666; background: #eee; padding: 2px 6px; border-radius: 4px;">銅(景気)下落</span> ＋ <span style="font-size: 0.8rem; color: #666; background: #eee; padding: 2px 6px; border-radius: 4px;">コスト増</span><br>
                    「景気の体温計」である銅価格が下落し需要が冷え込む一方で、原油やITなどの輸入コストが上昇中。不景気なのに物価が上がる、生活が最も苦しい局面です。
                </div>

                <h5 style="margin: 25px 0 10px 0; border-left: 4px solid #f57f17; padding-left: 10px; color: #333;">🟠 警戒領域 (構造的課題)</h5>
                <div style="margin-bottom: 15px;">
                    <strong style="color: #f57f17;">デジタル赤字貧乏</strong><br>
                    <span style="font-size: 0.8rem; color: #666; background: #eee; padding: 2px 6px; border-radius: 4px;">輸出横ばい</span> ＋ <span style="font-size: 0.8rem; color: #666; background: #eee; padding: 2px 6px; border-radius: 4px;">ITコスト増</span> ＋ <span style="font-size: 0.8rem; color: #666; background: #eee; padding: 2px 6px; border-radius: 4px;">円安</span><br>
                    日本の輸出（稼ぐ力）は伸び悩んでいるのに、海外へのITサービス支払い（デジタル赤字）と円安によって、国富が一方的に流出している状態です。
                </div>
                <div style="margin-bottom: 15px;">
                    <strong style="color: #f57f17;">利益なき繁忙 (コストプッシュ)</strong><br>
                    <span style="font-size: 0.8rem; color: #666; background: #eee; padding: 2px 6px; border-radius: 4px;">輸出増</span> ＋ <span style="font-size: 0.8rem; color: #666; background: #eee; padding: 2px 6px; border-radius: 4px;">コスト増</span> ＋ <span style="font-size: 0.8rem; color: #666; background: #eee; padding: 2px 6px; border-radius: 4px;">円安</span><br>
                    輸出数量は伸びていますが、それ以上に資源高や円安による輸入コスト増が激しく、売上はあっても利益が残りにくい「忙しいだけ」の状態です。
                </div>
                <div style="margin-bottom: 15px;">
                    <strong style="color: #f57f17;">米独り勝ち</strong><br>
                    <span style="font-size: 0.8rem; color: #666; background: #eee; padding: 2px 6px; border-radius: 4px;">米金利高</span> ＋ <span style="font-size: 0.8rem; color: #666; background: #eee; padding: 2px 6px; border-radius: 4px;">米株高</span><br>
                    米国の金利高と株高が両立しており、世界の資金が米国に吸い寄せられています。日本からは円安を通じて資金が流出しやすい局面です。
                </div>
                 <div>
                    <strong style="color: #f57f17;">供給ショック・資源インフレ</strong><br>
                    <span style="font-size: 0.8rem; color: #666; background: #eee; padding: 2px 6px; border-radius: 4px;">銅(景気)下落</span> ＋ <span style="font-size: 0.8rem; color: #666; background: #eee; padding: 2px 6px; border-radius: 4px;">原油高</span><br>
                    需要不足（不況）にもかかわらず、地政学リスクなどで原油価格だけが高騰。コストプッシュ型の悪いインフレ圧力が発生しています。
                </div>

                <h5 style="margin: 25px 0 10px 0; border-left: 4px solid #2e7d32; padding-left: 10px; color: #333;">🟢 成長領域 (好循環)</h5>
                <div style="margin-bottom: 15px;">
                    <strong style="color: #2e7d32;">黄金期 (高次元バランス)</strong><br>
                    <span style="font-size: 0.8rem; color: #666; background: #eee; padding: 2px 6px; border-radius: 4px;">銅(景気)上昇</span> ＋ <span style="font-size: 0.8rem; color: #666; background: #eee; padding: 2px 6px; border-radius: 4px;">コスト安定</span><br>
                    世界景気の拡大で輸出が伸びる一方、輸入コストは安定。交易条件が改善し、日本企業が最も利益を上げやすく給料アップにも繋がりやすい理想的な環境です。
                </div>
                <div>
                    <strong style="color: #2e7d32;">昭和型ブーム (輸出ボーナス)</strong><br>
                    <span style="font-size: 0.8rem; color: #666; background: #eee; padding: 2px 6px; border-radius: 4px;">銅(景気)上昇</span> ＋ <span style="font-size: 0.8rem; color: #666; background: #eee; padding: 2px 6px; border-radius: 4px;">円安</span><br>
                    世界的な需要増と円安が重なり、輸出企業の業績が爆発的に伸びるパターン。高度経済成長期のような輸出主導の好景気です。
                </div>

                <h5 style="margin: 25px 0 10px 0; border-left: 4px solid #1976d2; padding-left: 10px; color: #333;">🔵 停滞・不況</h5>
                <div style="margin-bottom: 15px;">
                    <strong style="color: #0d47a1;">円高不況</strong><br>
                    <span style="font-size: 0.8rem; color: #666; background: #eee; padding: 2px 6px; border-radius: 4px;">銅(景気)下落</span> ＋ <span style="font-size: 0.8rem; color: #666; background: #eee; padding: 2px 6px; border-radius: 4px;">円高</span><br>
                    世界不況に加え、円高によって輸出競争力が低下。製造業を中心に業績が悪化し、デフレ圧力が強まる不況局面です。
                </div>
                <div>
                    <strong style="color: #0d47a1;">世界同時不況</strong><br>
                    <span style="font-size: 0.8rem; color: #666; background: #eee; padding: 2px 6px; border-radius: 4px;">全指標下落</span><br>
                    需要（銅）、エネルギー（原油）、IT株価がすべて下落。世界経済全体が収縮しており、日本もその波に飲み込まれている状態です。
                </div>

                <h5 style="margin: 25px 0 10px 0; border-left: 4px solid #757575; padding-left: 10px; color: #333;">⚪ その他</h5>
                <div>
                    <strong style="color: #616161;">トレンド交錯・過渡期</strong><br>
                    <span style="font-size: 0.8rem; color: #666; background: #eee; padding: 2px 6px; border-radius: 4px;">パターン合致なし</span><br>
                    主要指標の方向性がバラバラで、明確なトレンドが出ていません。市場の迷い、あるいはトレンドの転換点（過渡期）にある可能性が高い状態です。
                </div>
            </div>
        </details>

        <h4 style="font-size: 1.0rem; border-bottom: 2px solid #eee; padding-bottom: 10px; color: #555;">過去365日の相対パフォーマンス (起点=100)</h4>
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

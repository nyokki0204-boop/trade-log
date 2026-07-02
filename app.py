import streamlit as st
import pandas as pd
import matplotlib.pyplot as plt
import io
import json
import base64
import datetime
import requests
import warnings
warnings.filterwarnings('ignore')

try:
    import japanize_matplotlib
except:
    pass

st.set_page_config(page_title="Trade Log", page_icon="📒", layout="wide")
st.title("📒 TRADE LOG")
st.caption("トレード記録 — CFD / 現物（米株）")

CSV_PATH = 'data/trade_log.csv'

GITHUB_TOKEN = st.secrets.get('github_token', '')
GITHUB_REPO  = st.secrets.get('github_repo', '')
GITHUB_API   = f'https://api.github.com/repos/{GITHUB_REPO}/contents/{CSV_PATH}'

COLUMNS = ['id','entry_date','ticker','type','direction',
           'entry_price','stop_price','exit_price','exit_date','memo']

def github_load():
    if not GITHUB_TOKEN:
        return pd.DataFrame(columns=COLUMNS), None
    try:
        headers = {'Authorization': f'token {GITHUB_TOKEN}'}
        r = requests.get(GITHUB_API, headers=headers, timeout=10)
        if r.status_code == 200:
            data = r.json()
            content = base64.b64decode(data['content']).decode('utf-8')
            df = pd.read_csv(io.StringIO(content))
            return df, data['sha']
        else:
            return pd.DataFrame(columns=COLUMNS), None
    except Exception as e:
        st.error(f'読み込みエラー: {e}')
        return pd.DataFrame(columns=COLUMNS), None

def github_save(df, sha=None):
    if not GITHUB_TOKEN:
        st.error('GitHubトークンが設定されていません')
        return False
    try:
        csv_str = df.to_csv(index=False, encoding='utf-8-sig')
        content_b64 = base64.b64encode(csv_str.encode('utf-8')).decode('utf-8')
        headers = {'Authorization': f'token {GITHUB_TOKEN}'}
        payload = {
            'message': f'Update trade_log {datetime.datetime.now().strftime("%Y-%m-%d %H:%M")}',
            'content': content_b64,
        }
        if sha:
            payload['sha'] = sha
        r = requests.put(GITHUB_API, headers=headers, data=json.dumps(payload), timeout=10)
        if r.status_code in (200, 201):
            return True
        else:
            st.error(f'保存エラー: {r.status_code} {r.text[:200]}')
            return False
    except Exception as e:
        st.error(f'保存エラー: {e}')
        return False

def calc_pnl_pct(row):
    try:
        entry = float(row['entry_price'])
        exit_ = float(row['exit_price'])
        if pd.isna(exit_) or entry == 0:
            return None
        if row['direction'] == '売り':
            return round((entry - exit_) / entry * 100, 2)
        else:
            return round((exit_ - entry) / entry * 100, 2)
    except:
        return None

def calc_rr(row):
    try:
        entry = float(row['entry_price'])
        stop  = float(row['stop_price'])
        exit_ = float(row['exit_price'])
        risk = abs(entry - stop)
        if risk == 0 or pd.isna(exit_):
            return None
        reward = abs(exit_ - entry)
        return round(reward / risk, 2)
    except:
        return None

def get_status(row):
    if pd.isna(row['exit_price']) or row['exit_price'] == '':
        return '🟢 保有中'
    pnl = calc_pnl_pct(row)
    if pnl is None:
        return '🟢 保有中'
    if pnl > 0:
        return '🏆 利確'
    elif pnl < 0:
        return '🔴 損切り'
    else:
        return '⚪ 手仕舞い'

tab1, tab2, tab3 = st.tabs(['➕ 新規記録', '📋 取引一覧', '📊 成績'])

with tab1:
    st.subheader('➕ 新しい取引を記録')

    c1, c2 = st.columns(2)
    with c1:
        entry_date = st.date_input('エントリー日', value=datetime.date.today())
        ticker     = st.text_input('銘柄（ティッカー）', placeholder='例: AAPL').upper()
        trade_type = st.radio('種別', ['現物', 'CFD'], horizontal=True)
    with c2:
        if trade_type == 'CFD':
            direction = st.radio('方向', ['買い', '売り'], horizontal=True)
        else:
            direction = '買い'
            st.radio('方向', ['買い'], horizontal=True, disabled=True)
        entry_price = st.number_input('エントリー価格', min_value=0.0, step=0.01, format='%.2f')
        stop_price  = st.number_input('損切り価格', min_value=0.0, step=0.01, format='%.2f')

    memo = st.text_input('メモ（任意）', placeholder='エントリー根拠など')

    if entry_price > 0 and stop_price > 0:
        risk_pct = abs(entry_price - stop_price) / entry_price * 100
        st.info(f'損切りまでの値幅: {risk_pct:.1f}%')

    st.divider()
    if st.button('💾 記録する', type='primary', use_container_width=True):
        if not ticker:
            st.error('銘柄を入力してください')
        elif entry_price == 0:
            st.error('エントリー価格を入力してください')
        else:
            df, sha = github_load()
            new_id = 1 if len(df) == 0 else int(df['id'].max()) + 1
            new_row = pd.DataFrame([{
                'id'         : new_id,
                'entry_date' : str(entry_date),
                'ticker'     : ticker,
                'type'       : trade_type,
                'direction'  : direction,
                'entry_price': entry_price,
                'stop_price' : stop_price,
                'exit_price' : '',
                'exit_date'  : '',
                'memo'       : memo,
            }])
            df = pd.concat([df, new_row], ignore_index=True)
            with st.spinner('保存中...'):
                if github_save(df, sha):
                    st.success(f'✅ {ticker} を記録しました！')
                    st.balloons()

with tab2:
    st.subheader('📋 取引一覧')
    df, sha = github_load()

    if len(df) == 0:
        st.info('まだ記録がありません。')
    else:
        df_disp = df.copy()
        df_disp['損益%']   = df_disp.apply(calc_pnl_pct, axis=1)
        df_disp['RR']      = df_disp.apply(calc_rr, axis=1)
        df_disp['状態']    = df_disp.apply(get_status, axis=1)

        filt = st.radio('種別で絞り込み', ['すべて', '現物', 'CFD'], horizontal=True)
        if filt != 'すべて':
            df_disp = df_disp[df_disp['type'] == filt]

        show_cols = ['id','entry_date','ticker','type','direction',
                     'entry_price','stop_price','exit_price','損益%','RR','状態','memo']
        st.dataframe(df_disp[show_cols].iloc[::-1].reset_index(drop=True),
                     use_container_width=True, height=400)

        st.divider()
        st.subheader('✏️ 決済を記録 / 編集')
        open_trades = df[df['exit_price'].isna() | (df['exit_price'] == '')]
        if len(open_trades) > 0:
            st.caption('🟢 保有中の取引に決済価格を入力')
            options = [f"#{int(r['id'])} {r['ticker']} ({r['type']}/{r['direction']}) @ {r['entry_price']}"
                       for _, r in open_trades.iterrows()]
            selected = st.selectbox('決済する取引を選択', options)
            sel_id = int(selected.split(' ')[0].replace('#', ''))

            ec1, ec2 = st.columns(2)
            with ec1:
                exit_price = st.number_input('決済価格', min_value=0.0, step=0.01, format='%.2f')
            with ec2:
                exit_date = st.date_input('決済日', value=datetime.date.today())

            if st.button('💾 決済を保存', type='primary'):
                if exit_price == 0:
                    st.error('決済価格を入力してください')
                else:
                    df['exit_price'] = df['exit_price'].astype('object')
                    df['exit_date']  = df['exit_date'].astype('object')
                    df.loc[df['id'] == sel_id, 'exit_price'] = str(exit_price)
                    df.loc[df['id'] == sel_id, 'exit_date']  = str(exit_date)
                    with st.spinner('保存中...'):
                        if github_save(df, sha):
                            st.success('✅ 決済を記録しました！')
                            st.rerun()
        else:
            st.caption('保有中の取引はありません')

        with st.expander('🗑️ 記録を削除'):
            del_id = st.selectbox('削除する取引ID', df['id'].tolist())
            if st.button('削除する', type='secondary'):
                df2 = df[df['id'] != del_id]
                if github_save(df2, sha):
                    st.success(f'#{del_id} を削除しました')
                    st.rerun()

with tab3:
    st.subheader('📊 成績')
    df, _ = github_load()

    if len(df) == 0:
        st.info('まだ記録がありません。')
    else:
        df['損益%'] = df.apply(calc_pnl_pct, axis=1)
        closed = df[df['損益%'].notna()].copy()

        if len(closed) == 0:
            st.info('決済済みの取引がまだありません。')
        else:
            def show_stats(data, title):
                if len(data) == 0:
                    st.write(f'**{title}**: 取引なし')
                    return
                wins   = data[data['損益%'] > 0]
                losses = data[data['損益%'] < 0]
                win_rate = len(wins) / len(data) * 100 if len(data) > 0 else 0
                total_win  = wins['損益%'].sum()
                total_loss = abs(losses['損益%'].sum())
                pf = (total_win / total_loss) if total_loss > 0 else float('inf')

                st.markdown(f'### {title}')
                m1, m2, m3, m4 = st.columns(4)
                m1.metric('取引数', f'{len(data)}件')
                m2.metric('勝率', f'{win_rate:.0f}%')
                m3.metric('平均損益', f'{data["損益%"].mean():.2f}%')
                pf_str = '∞' if pf == float('inf') else f'{pf:.2f}'
                m4.metric('PF', pf_str)

            show_stats(closed, '📊 全体')
            st.divider()
            show_stats(closed[closed['type']=='現物'], '📈 現物（米株）')
            st.divider()
            show_stats(closed[closed['type']=='CFD'], '⚡ CFD')

            st.divider()
            st.subheader('📈 損益曲線（累積損益%）')
            closed_sorted = closed.sort_values('entry_date')
            closed_sorted['累積'] = closed_sorted['損益%'].cumsum()

            fig, ax = plt.subplots(figsize=(12, 5), facecolor='#0d1117')
            ax.set_facecolor('#0d1117')
            ax.tick_params(colors='#aaaaaa', labelsize=9)
            ax.grid(True, alpha=0.12, color='#444444')
            for spine in ax.spines.values():
                spine.set_color('#2a2a2a')
            ax.axhline(0, color='#555555', linewidth=1.0, linestyle='--')

            colors = ['#00ff88' if v >= 0 else '#ff6b6b' for v in closed_sorted['累積']]
            ax.plot(range(len(closed_sorted)), closed_sorted['累積'],
                    color='white', linewidth=2.0, marker='o', markersize=5, zorder=3)
            for i, (v, c) in enumerate(zip(closed_sorted['累積'], colors)):
                ax.scatter(i, v, color=c, s=50, zorder=4)

            ax.set_ylabel('累積損益%', color='#aaaaaa', fontsize=10)
            ax.set_title('損益曲線', color='white', fontsize=12, fontweight='bold')
            ax.set_xticks(range(len(closed_sorted)))
            ax.set_xticklabels(closed_sorted['ticker'], rotation=45, fontsize=8, color='#aaaaaa')
            plt.tight_layout()
            st.pyplot(fig)

st.caption(f'最終更新: {pd.Timestamp.now().strftime("%Y/%m/%d %H:%M")}')

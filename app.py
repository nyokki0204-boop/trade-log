import streamlit as st
import pandas as pd
import matplotlib.pyplot as plt
import io
import json
import base64
import datetime
import requests
import hmac
import warnings
from asset_history import ASSET_COLUMNS, prepare_history
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
           'entry_price','stop_price','exit_price','exit_date','tag','memo']

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
            for col in COLUMNS:
                if col not in df.columns:
                    df[col] = ''
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


ASSET_PATH = 'data/asset_history.csv'


def assets_connection():
    """Only allow account balances in a configured private repository."""
    repo = st.secrets.get('assets_github_repo', '')
    token = st.secrets.get('assets_github_token', '')
    if not repo or not token:
        st.info('資産履歴の保存先が未設定です。非公開リポジトリと専用トークンをSecretsに設定してください。')
        return None
    if '/' not in repo or len(repo.split('/')) != 2:
        st.error('assets_github_repo は owner/repo の形式で設定してください。')
        return None
    headers = {'Authorization': f'Bearer {token}', 'Accept': 'application/vnd.github+json'}
    try:
        response = requests.get(f'https://api.github.com/repos/{repo}', headers=headers, timeout=10)
        response.raise_for_status()
        if response.json().get('private') is not True:
            st.error('資産額は非公開リポジトリにのみ保存できます。保存先の公開設定を確認してください。')
            return None
    except requests.RequestException:
        st.error('非公開リポジトリを確認できません。設定と接続を確認してください。')
        return None
    return f'https://api.github.com/repos/{repo}/contents/{ASSET_PATH}', headers


def assets_load(connection):
    url, headers = connection
    try:
        response = requests.get(url, headers=headers, timeout=10)
        if response.status_code == 404:
            return pd.DataFrame(columns=ASSET_COLUMNS), None
        response.raise_for_status()
        data = response.json()
        content = base64.b64decode(data['content']).decode('utf-8-sig')
        history = pd.read_csv(io.StringIO(content), dtype={'memo': 'string'})
        prepare_history(history)
        return history, data['sha']
    except (requests.RequestException, KeyError, ValueError, UnicodeError) as error:
        st.error(f'資産履歴を読み込めません。保存操作を停止しました。詳細: {error}')
        return None, None


def assets_save(connection, history, sha):
    # Check privacy again immediately before writing.
    current_connection = assets_connection()
    if current_connection is None:
        return False
    url, headers = current_connection
    if url != connection[0]:
        st.error('保存先が変更されました。画面を再読み込みしてください。')
        return False
    try:
        prepare_history(history)
        content = base64.b64encode(history[ASSET_COLUMNS].to_csv(index=False).encode('utf-8-sig')).decode('ascii')
        payload = {'message': 'Update account asset history', 'content': content}
        if sha:
            payload['sha'] = sha
        response = requests.put(url, headers=headers, json=payload, timeout=10)
        response.raise_for_status()
        return True
    except (requests.RequestException, ValueError) as error:
        st.error(f'資産履歴を保存できませんでした。再読込して確認してください。詳細: {error}')
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

def calc_r(row):
    """R倍数：決めたリスクの何倍取れたか"""
    try:
        entry = float(row['entry_price'])
        stop  = float(row['stop_price'])
        exit_ = float(row['exit_price'])
        risk = abs(entry - stop)
        if risk == 0 or pd.isna(exit_):
            return None
        if row['direction'] == '売り':
            profit = entry - exit_
        else:
            profit = exit_ - entry
        return round(profit / risk, 2)
    except:
        return None

def calc_hold_days(row):
    """保有日数"""
    try:
        d1 = pd.to_datetime(row['entry_date'])
        d2 = pd.to_datetime(row['exit_date'])
        if pd.isna(d2):
            return None
        return (d2 - d1).days
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

tab1, tab2, tab3, tab4 = st.tabs(['➕ 新規記録', '📋 取引一覧', '📊 成績', '💰 総資産'])

with tab1:
    st.subheader('➕ 新しい取引を記録')

    # 過去に使ったタグを集める
    df_all, _ = github_load()
    past_tags = []
    if len(df_all) > 0 and 'tag' in df_all.columns:
        past_tags = sorted([t for t in df_all['tag'].dropna().unique() if str(t).strip() != ''])

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

    # タグ入力（過去のタグから選ぶ or 新規入力）
    st.markdown('**タグ**（分類用の短い言葉）')
    if past_tags:
        tag_choice = st.selectbox('過去のタグから選ぶ', ['（新しく入力）'] + past_tags)
    else:
        tag_choice = '（新しく入力）'
    if tag_choice == '（新しく入力）':
        tag = st.text_input('タグを入力', placeholder='例: 押し目買い', label_visibility='collapsed')
    else:
        tag = tag_choice

    memo = st.text_input('メモ（自由記入）', placeholder='振り返りなど')

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
                'tag'        : tag,
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
        df_disp['R']       = df_disp.apply(calc_r, axis=1)
        df_disp['保有日数'] = df_disp.apply(calc_hold_days, axis=1)
        df_disp['状態']    = df_disp.apply(get_status, axis=1)

        filt = st.radio('種別で絞り込み', ['すべて', '現物', 'CFD'], horizontal=True)
        if filt != 'すべて':
            df_disp = df_disp[df_disp['type'] == filt]

        show_cols = ['id','entry_date','ticker','type','direction',
                     'entry_price','stop_price','exit_price',
                     '損益%','R','保有日数','状態','tag','memo']
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
        df['R']     = df.apply(calc_r, axis=1)
        df['保有日数'] = df.apply(calc_hold_days, axis=1)
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
                avg_r = data['R'].mean() if data['R'].notna().any() else 0

                st.markdown(f'### {title}')
                m1, m2, m3, m4, m5 = st.columns(5)
                m1.metric('取引数', f'{len(data)}件')
                m2.metric('勝率', f'{win_rate:.0f}%')
                m3.metric('平均損益', f'{data["損益%"].mean():.2f}%')
                pf_str = '∞' if pf == float('inf') else f'{pf:.2f}'
                m4.metric('PF', pf_str)
                m5.metric('平均R', f'{avg_r:.2f}R')

            show_stats(closed, '📊 全体')
            st.divider()
            show_stats(closed[closed['type']=='現物'], '📈 現物（米株）')
            st.divider()
            show_stats(closed[closed['type']=='CFD'], '⚡ CFD')

            # 勝ち負けの中身比較
            st.divider()
            st.subheader('🔍 勝ち負けの中身')
            wins   = closed[closed['損益%'] > 0]
            losses = closed[closed['損益%'] < 0]
            cc1, cc2 = st.columns(2)
            with cc1:
                st.markdown('**勝ちトレード**')
                if len(wins) > 0:
                    st.write(f'平均利益: +{wins["損益%"].mean():.2f}%')
                    st.write(f'平均保有: {wins["保有日数"].mean():.1f}日')
                else:
                    st.write('なし')
            with cc2:
                st.markdown('**負けトレード**')
                if len(losses) > 0:
                    st.write(f'平均損失: {losses["損益%"].mean():.2f}%')
                    st.write(f'平均保有: {losses["保有日数"].mean():.1f}日')
                else:
                    st.write('なし')

            # タグ別成績
            st.divider()
            st.subheader('🏷️ タグ別成績')
            if 'tag' in closed.columns and closed['tag'].notna().any():
                tag_data = closed[closed['tag'].astype(str).str.strip() != '']
                if len(tag_data) > 0:
                    tag_summary = (
                        tag_data.groupby('tag')
                        .agg(
                            取引数=('損益%', 'count'),
                            勝率=('損益%', lambda x: f'{(x>0).sum()/len(x)*100:.0f}%'),
                            平均損益=('損益%', lambda x: round(x.mean(), 2)),
                            平均R=('R', lambda x: round(x.mean(), 2) if x.notna().any() else 0),
                        )
                        .sort_values('取引数', ascending=False)
                    )
                    st.dataframe(tag_summary, use_container_width=True)
                else:
                    st.caption('タグ付きの取引がまだありません')
            else:
                st.caption('タグ付きの取引がまだありません')

            # 月別成績
            st.divider()
            st.subheader('📅 月別成績')
            closed['month'] = pd.to_datetime(closed['entry_date']).dt.to_period('M').astype(str)
            monthly = (
                closed.groupby('month')
                .agg(
                    取引数=('損益%', 'count'),
                    勝率=('損益%', lambda x: f'{(x>0).sum()/len(x)*100:.0f}%'),
                    合計損益=('損益%', lambda x: round(x.sum(), 2)),
                )
                .sort_index(ascending=False)
            )
            st.dataframe(monthly, use_container_width=True)

            # 損益曲線
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

            ax.plot(range(len(closed_sorted)), closed_sorted['累積'],
                    color='white', linewidth=2.0, marker='o', markersize=5, zorder=3)
            for i, v in enumerate(closed_sorted['累積']):
                c = '#00ff88' if v >= 0 else '#ff6b6b'
                ax.scatter(i, v, color=c, s=50, zorder=4)

            ax.set_ylabel('累積損益%', color='#aaaaaa', fontsize=10)
            ax.set_title('損益曲線', color='white', fontsize=12, fontweight='bold')
            ax.set_xticks(range(len(closed_sorted)))
            ax.set_xticklabels(closed_sorted['ticker'], rotation=45, fontsize=8, color='#aaaaaa')
            plt.tight_layout()
            st.pyplot(fig)

with tab4:
    st.subheader('💰 トレード口座の総資産')
    st.caption('現金＋保有商品の評価額を、証券口座の表示と同じ通貨で記録します。取引記録の騰落率はここに足しません。')
    password = st.secrets.get('assets_access_password', '')
    if not password:
        st.warning('資産額を表示するには、Secretsに assets_access_password を設定してください。')
    else:
        entered = st.text_input('資産履歴のパスワード', type='password', key='assets_password_input')
        if entered and hmac.compare_digest(entered, password):
            connection = assets_connection()
            if connection is not None:
                history, sha = assets_load(connection)
                if history is not None:
                    prepared = prepare_history(history)
                    currency = prepared['currency'].iloc[0] if len(prepared) else 'JPY'
                    symbol = '¥' if currency == 'JPY' else '$'
                    decimals = 0 if currency == 'JPY' else 2

                    if len(prepared):
                        first, latest = prepared.iloc[0], prepared.iloc[-1]
                        total_flow = prepared['net_flow'].sum()
                        st.caption(f"基準日 {first['date']:%Y/%m/%d} → 最新記録 {latest['date']:%Y/%m/%d}（{currency}）")
                        m1, m2, m3 = st.columns(3)
                        m1.metric('現在の総資産', f"{symbol}{latest['total_assets']:,.{decimals}f}")
                        m2.metric('総資産の増減', f"{latest['asset_change']:+,.{decimals}f} {currency}")
                        m3.metric('入出金を除いた増減', f"{latest['cumulative_operating_change']:+,.{decimals}f} {currency}")
                        st.caption(f"基準額 {symbol}{first['total_assets']:,.{decimals}f} ／ 累計入出金 {total_flow:+,.{decimals}f} {currency}。入出金を除いた増減＝最新総資産−基準額−累計入出金。保有商品の評価変動を含みます。")
                        chart = prepared.set_index('date')
                        st.markdown('#### 総資産の推移')
                        st.line_chart(chart['total_assets'])
                        st.markdown('#### 入出金を除いた累計増減')
                        st.line_chart(chart['cumulative_operating_change'])
                        display = prepared[['date', 'total_assets', 'net_flow', 'operating_change', 'memo']].copy()
                        display['date'] = display['date'].dt.strftime('%Y-%m-%d')
                        display.columns = ['日付', '総資産', '前回からの入出金', '前回からの調整後増減', 'メモ']
                        st.dataframe(display.iloc[::-1], hide_index=True, use_container_width=True)
                        st.download_button('履歴をCSVでバックアップ', history[ASSET_COLUMNS].to_csv(index=False).encode('utf-8-sig'), 'asset_history.csv', 'text/csv')
                    else:
                        st.info('まず基準となる口座の総資産を登録してください。')

                    with st.form('new_asset_snapshot'):
                        st.markdown('#### 総資産を記録')
                        if not len(prepared):
                            currency = st.selectbox('記録する通貨（以降は変更できません）', ['JPY', 'USD'])
                        date = st.date_input('評価日', value=datetime.date.today(), max_value=datetime.date.today())
                        total = st.number_input(f'口座の総資産（{currency}）', min_value=0.0, step=1000.0 if currency == 'JPY' else 1.0, format='%.0f' if currency == 'JPY' else '%.2f')
                        flow = 0.0
                        if len(prepared):
                            flow = st.number_input('前回の記録から今回までの入出金合計（入金＋／出金−）', value=0.0, step=1000.0 if currency == 'JPY' else 1.0, format='%.0f' if currency == 'JPY' else '%.2f')
                        memo = st.text_input('メモ（任意）')
                        if st.form_submit_button('資産額を保存', type='primary'):
                            if len(prepared) and date <= latest['date'].date():
                                st.error('最新記録より後の日付にしてください。同日の修正は下の「最新記録を修正」からできます。')
                            else:
                                new_row = pd.DataFrame([{'date': str(date), 'total_assets': total, 'net_flow': flow, 'currency': currency, 'memo': memo}])
                                updated = pd.concat([history, new_row], ignore_index=True)
                                if assets_save(connection, updated, sha):
                                    st.success('資産額を保存しました。')
                                    st.rerun()

                    if len(prepared):
                        with st.expander('最新記録を修正'):
                            with st.form('edit_asset_snapshot'):
                                corrected_total = st.number_input('修正後の総資産', min_value=0.0, value=float(latest['total_assets']), format='%.0f' if currency == 'JPY' else '%.2f')
                                corrected_flow = 0.0 if len(prepared) == 1 else st.number_input('修正後の入出金合計', value=float(latest['net_flow']), format='%.0f' if currency == 'JPY' else '%.2f')
                                corrected_memo = st.text_input('修正後のメモ', value='' if pd.isna(latest['memo']) else str(latest['memo']))
                                if st.form_submit_button('修正を保存'):
                                    updated = history.copy()
                                    idx = updated.index[updated['date'].astype(str) == latest['date'].strftime('%Y-%m-%d')][0]
                                    updated.loc[idx, ['total_assets', 'net_flow', 'memo']] = [corrected_total, corrected_flow, corrected_memo]
                                    if assets_save(connection, updated, sha):
                                        st.success('修正しました。')
                                        st.rerun()
                        with st.expander('最新記録を取り消す'):
                            st.caption('最新の記録だけを取り消せます。取り消した記録の入出金も集計から外れます。')
                            if st.checkbox('最新記録の取り消しを確認する') and st.button('最新記録を取り消す'):
                                updated = history[history['date'].astype(str) != latest['date'].strftime('%Y-%m-%d')].copy()
                                if assets_save(connection, updated, sha):
                                    st.success('最新記録を取り消しました。')
                                    st.rerun()
        elif entered:
            st.error('パスワードが違います。')

st.caption(f'最終更新: {pd.Timestamp.now().strftime("%Y/%m/%d %H:%M")}')

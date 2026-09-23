"""Account snapshot calculations. All amounts use a single user-selected currency."""

import pandas as pd


ASSET_COLUMNS = ['date', 'total_assets', 'net_flow', 'currency', 'memo']


def prepare_history(history):
    """Validate snapshots and return dated, chronological rows with derived changes."""
    if history.empty:
        return pd.DataFrame(columns=ASSET_COLUMNS + ['asset_change', 'operating_change', 'cumulative_operating_change'])

    rows = history.copy()
    if not set(ASSET_COLUMNS).issubset(rows.columns):
        raise ValueError('資産履歴の列が不足しています。')
    rows['date'] = pd.to_datetime(rows['date'], errors='coerce')
    rows['total_assets'] = pd.to_numeric(rows['total_assets'], errors='coerce')
    rows['net_flow'] = pd.to_numeric(rows['net_flow'], errors='coerce')
    rows['currency'] = rows['currency'].astype(str).str.strip()
    if rows[['date', 'total_assets', 'net_flow']].isna().any().any():
        raise ValueError('資産履歴に無効な日付または金額があります。')
    if (rows['total_assets'] < 0).any():
        raise ValueError('総資産は0以上にしてください。')
    if len(set(rows['currency'])) != 1 or rows['currency'].iloc[0] not in ('JPY', 'USD'):
        raise ValueError('資産履歴の通貨は円かドルのいずれか一種類にしてください。')
    if rows['date'].duplicated().any():
        raise ValueError('同じ日付の資産記録が複数あります。')
    rows = rows.sort_values('date').reset_index(drop=True)
    if rows.loc[0, 'net_flow'] != 0:
        raise ValueError('最初の記録の入出金は0にしてください。')
    rows['asset_change'] = rows['total_assets'] - rows.loc[0, 'total_assets']
    rows['operating_change'] = rows['total_assets'].diff().fillna(0) - rows['net_flow']
    rows['cumulative_operating_change'] = rows['operating_change'].cumsum()
    return rows

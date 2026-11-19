from pathlib import Path

import joblib
import numpy as np
import pandas as pd

MODEL_DIR = Path(__file__).resolve().parent / 'models'

VARIABLES = ['PM2.5', 'PM10', 'CO', 'NO2', 'Temperature', 'Humidity']
pollutants = VARIABLES

time_cols = ['Month', 'DayOfYear', 'DayOfWeek', 'doy_sin', 'doy_cos', 'hour_sin', 'hour_cos']
hist_cols = [f'{k}_{p}' for p in pollutants for k in ('last', 'age', 'med1h', 'med3h')]
ctx_cols = time_cols + hist_cols
cur_cols = [f'cur_{p}' for p in pollutants]


def make_features(frame):
    F = pd.DataFrame(index=frame.index)
    F['Month'] = frame.index.month
    F['DayOfYear'] = frame.index.dayofyear
    F['doy_sin'] = np.sin(2 * np.pi * frame.index.dayofyear / 365.0)
    F['doy_cos'] = np.cos(2 * np.pi * frame.index.dayofyear / 365.0)
    F['DayOfWeek'] = frame.index.dayofweek
    h = frame.index.hour + frame.index.minute / 60.0
    F['hour_sin'] = np.sin(2 * np.pi * h / 24)
    F['hour_cos'] = np.cos(2 * np.pi * h / 24)
    for p in pollutants:
        s = frame[p]
        F[f'cur_{p}'] = s
        prev = s.shift(1)
        t_obs = pd.Series(np.where(prev.notna(), frame.index.values, np.datetime64('NaT')),
                          index=frame.index).ffill()
        age = (frame.index.to_series() - t_obs).dt.total_seconds() / 3600.0
        stale = age.isna() | (age > 48)
        F[f'last_{p}'] = prev.ffill().where(~stale)
        F[f'age_{p}'] = age.where(~stale, 48.0)
        F[f'med1h_{p}'] = s.rolling('1h', closed='left').median()
        F[f'med3h_{p}'] = s.rolling('3h', closed='left').median()
    return F


def pass2_input(F, pass1_preds, p):
    X = F[ctx_cols].copy()
    for o in pollutants:
        if o != p:
            X[f'cur_{o}'] = F[f'cur_{o}'].fillna(pass1_preds[o])
    return X


def dyn_cols(p, cols, sel_cols):
    return [c for c in cols if c in sel_cols[p]] if p in sel_cols else list(cols)


def predict_dynamic(frame, model):
    sel = model.get('sel_cols', {'CO': model['co_cols']} if 'co_cols' in model else {})
    F = make_features(frame)
    pass1_preds = pd.DataFrame({p: model['pass1'][p].predict(F[dyn_cols(p, ctx_cols, sel)])
                                for p in pollutants}, index=F.index)
    out = {}
    for p in pollutants:
        X2 = pass2_input(F, pass1_preds, p)
        out[p] = model['pass2'][p].predict(X2[dyn_cols(p, X2.columns, sel)])
    return pd.DataFrame(out, index=F.index)


def predict_mice(frame, model):
    F = make_features(frame)
    arr = model['imputer'].transform(np.hstack([model['pre'].transform(F[ctx_cols]), F[cur_cols].values]))
    return pd.DataFrame(arr[:, -len(pollutants):], columns=pollutants, index=F.index)


def stack_input(F, Y, p):
    other_p = [o for o in pollutants if o != p]
    return np.hstack([F[ctx_cols].values, Y[other_p].values])


def predict_stacking(frame, model):
    F = make_features(frame)
    Y_current = frame[pollutants].copy()
    for p in pollutants:
        miss = Y_current[p].isna()
        if miss.any():
            Y_current.loc[miss, p] = model['warm'][p].predict(F.loc[miss, ctx_cols])
    for k in range(len(model['meta'])):
        Y_next = Y_current.copy()
        for p in pollutants:
            m = frame[p].isna().values
            if m.any():
                Z = stack_input(F, Y_current, p)[m]
                Y_next.loc[m, p] = model['meta'][k][p].predict(
                    np.column_stack([base.predict(Z) for base in model['bases'][k][p]]))
        Y_current = Y_next.copy()
    return Y_current


MODELS = {
    'dynamic': ('dynamic_imputation.joblib', predict_dynamic),
    'mice': ('mice_extratrees.joblib', predict_mice),
    'stacking': ('stacking_ensemble.joblib', predict_stacking),
}


def impute(frame, model_name='mice'):
    file_name, predict = MODELS[model_name]
    model = joblib.load(MODEL_DIR / file_name)
    frame = frame[VARIABLES].astype(float)
    if not frame.isna().any().any():
        return frame.copy()
    return frame.fillna(predict(frame, model).clip(lower=0))

"""Imputers M0-M3 and HGB-native. All share fit(clean, masked) / predict_frame(masked) / impute(history, record)."""
import joblib
import numpy as np
import pandas as pd
from sklearn.pipeline import make_pipeline
from sklearn.impute import SimpleImputer
from sklearn.preprocessing import StandardScaler
from sklearn.linear_model import Ridge, RidgeCV
from sklearn.neighbors import KNeighborsRegressor
from sklearn.neural_network import MLPRegressor
from sklearn.experimental import enable_iterative_imputer  # noqa: F401
from sklearn.impute import IterativeImputer
from sklearn.ensemble import (RandomForestRegressor, ExtraTreesRegressor,
                              HistGradientBoostingRegressor)
from sklearn.model_selection import TimeSeriesSplit
from sklearn.metrics import mean_absolute_error
from .features import make_features, features_for_record, VARS, time_features

MAX = {"pm25": 1000, "pm10": 1000, "no2": 1000, "co": 50, "temp": 50, "rh": 100}

def hist_cols(cols):
    return [c for c in cols if c.split("_")[0] in ("last", "age", "med1h", "med3h")]

def time_cols(cols):
    return [c for c in cols if c.startswith(("hour_", "dow", "season_"))]

def postprocess(pred: pd.DataFrame) -> pd.DataFrame:
    for v in pred.columns:
        pred[v] = pred[v].clip(0, MAX[v])
    if "pm25" in pred and "pm10" in pred:
        pred["pm25"] = np.minimum(pred["pm25"], pred["pm10"])
    return pred

def _feats(masked, last_only):
    f = make_features(masked)
    return f.iloc[[-1]] if last_only else f

def filled(model):
    """Wrap a model that cannot take NaN."""
    return make_pipeline(SimpleImputer(strategy="median"), StandardScaler(), model)

class Base:
    name = "base"
    def fit(self, clean, masked): raise NotImplementedError
    def predict_frame(self, masked, last_only=False):
        """Predict every variable at every row (vectorised; used for evaluation).
        last_only=True: features use the whole frame, but only the last row is predicted (run time)."""
        raise NotImplementedError
    def impute(self, history, record):
        """Run time: fill the null fields of one record. history = >= 49 h of previous records."""
        frame = pd.concat([history, record.to_frame().T.astype(float)])
        pred = self.predict_frame(frame, last_only=True).iloc[-1]
        out = record.copy()
        for v in VARS:
            if pd.isna(record[v]):
                out[v] = pred[v]
        return out
    def save(self, path): joblib.dump(self, path)
    @staticmethod
    def load(path, single_thread=True):
        """single_thread=True: one-row predictions run without a thread pool (much faster at run time)."""
        m = joblib.load(path)
        if single_thread:
            _set_n_jobs(m, 1, set())
        return m

def _set_n_jobs(obj, n, seen):
    if id(obj) in seen:
        return
    seen.add(id(obj))
    if hasattr(obj, "n_jobs") and not isinstance(obj, type):
        try:
            obj.n_jobs = n
        except AttributeError:
            pass
    items = obj.values() if isinstance(obj, dict) else obj if isinstance(obj, (list, tuple)) else \
        (vars(obj).values() if hasattr(obj, "__dict__") and not isinstance(obj, (str, bytes, np.ndarray, pd.DataFrame, pd.Series)) else [])
    for x in items:
        if isinstance(x, (dict, list, tuple)) or hasattr(x, "__dict__"):
            _set_n_jobs(x, n, seen)

class M0(Base):
    """Last observation carried forward (<= 6 h), else seasonal hour-of-day median."""
    name = "M0"
    def fit(self, clean, masked):
        key = [clean.index.month, clean.index.hour]
        self.prof = {v: clean[v].groupby(key).median() for v in VARS}
        return self
    def predict_frame(self, masked, last_only=False):
        f = _feats(masked, last_only)
        out = pd.DataFrame(index=f.index)
        for v in VARS:
            locf = f[f"last_{v}"].where(f[f"age_{v}"] <= 6)
            prof = pd.Series([self.prof[v].get((m, h), np.nan) for m, h in
                              zip(f.index.month, f.index.hour)], index=f.index)
            out[v] = locf.fillna(prof)
        return postprocess(out)

CANDIDATES = {
    "Ridge": lambda: filled(Ridge()),
    "KNN": lambda: filled(KNeighborsRegressor(n_neighbors=10)),
    "RF": lambda: filled(RandomForestRegressor(n_estimators=50, max_depth=16, min_samples_leaf=10, n_jobs=-1, random_state=0)),
    "HGB": lambda: HistGradientBoostingRegressor(random_state=0),
    "MLP": lambda: filled(MLPRegressor(hidden_layer_sizes=(64, 32), max_iter=300, random_state=0)),
}

def _train_rows(clean, f, v):
    return clean[v].notna()

class TwoPass(Base):
    """Shared two-pass logic: pass 1 = time + history only; pass 2 = + current co-variables,
    where a missing co-variable is replaced by its pass-1 estimate."""
    def _p1_X(self, f): return f[self.p1_cols]
    def _p2_X(self, f, p1, v):
        X = f[self.p2_cols[v]].copy()
        for o in VARS:
            c = f"cur_{o}"
            if c in X:
                X[c] = X[c].fillna(p1[o])
        return X
    def _setup(self, f):
        self.p1_cols = time_cols(f.columns) + hist_cols(f.columns)
        self.p2_cols = {v: self.p1_cols + [f"cur_{o}" for o in VARS if o != v] for v in VARS}
    def _pass1(self, f):
        return pd.DataFrame({v: self.p1[v].predict(self._p1_X(f)) for v in VARS}, index=f.index)

class M1(TwoPass):
    """Dynamic imputation: best model per target chosen on a validation split."""
    name = "M1"
    def __init__(self, candidates=("Ridge", "KNN", "RF", "HGB", "MLP")):
        self.candidates = candidates
    def fit(self, clean, masked, val_clean=None, val_masked=None):
        f = make_features(masked); self._setup(f)
        self.p1 = {v: CANDIDATES["HGB"]().fit(self._p1_X(f)[_train_rows(clean, f, v)],
                                              clean[v][_train_rows(clean, f, v)]) for v in VARS}
        p1 = self._pass1(f)
        fv = make_features(val_masked) if val_masked is not None else None
        p1v = self._pass1(fv) if fv is not None else None
        self.choice, self.p2 = {}, {}
        for v in VARS:
            rows = _train_rows(clean, f, v)
            X, y = self._p2_X(f, p1, v)[rows], clean[v][rows]
            if fv is None:
                self.choice[v] = "HGB"
            else:
                vr = val_masked[v].isna() & val_clean[v].notna()   # score only hidden, truly observed
                Xv, yv = self._p2_X(fv, p1v, v)[vr], val_clean[v][vr]
                scores = {k: mean_absolute_error(yv, CANDIDATES[k]().fit(X, y).predict(Xv))
                          for k in self.candidates}
                self.choice[v] = min(scores, key=scores.get)
            self.p2[v] = CANDIDATES[self.choice[v]]().fit(X, y)
        return self
    def fit_fixed(self, clean, masked, choice):
        """Refit with a model choice made earlier (e.g. on 2024), on more data."""
        f = make_features(masked); self._setup(f)
        self.p1 = {v: CANDIDATES["HGB"]().fit(self._p1_X(f)[clean[v].notna()], clean[v][clean[v].notna()])
                   for v in VARS}
        p1 = self._pass1(f)
        self.choice, self.p2 = dict(choice), {}
        for v in VARS:
            rows = clean[v].notna()
            self.p2[v] = CANDIDATES[choice[v]]().fit(self._p2_X(f, p1, v)[rows], clean[v][rows])
        return self
    def predict_frame(self, masked, last_only=False):
        f = _feats(masked, last_only); p1 = self._pass1(f)
        out = pd.DataFrame({v: self.p2[v].predict(self._p2_X(f, p1, v)) for v in VARS}, index=f.index)
        return postprocess(out)

class M2(Base):
    """Iterative imputation with ExtraTrees (MICE-style, single draw).
    Only the six current-value columns are imputed iteratively; time and history
    features are median-filled first, which keeps the model small enough for a Pi."""
    name = "M2"
    def __init__(self, n_estimators=30, max_depth=12, max_iter=3, min_samples_leaf=20):
        self.kw = dict(n_estimators=n_estimators, max_depth=max_depth, min_samples_leaf=min_samples_leaf)
        self.max_iter = max_iter
    def fit(self, clean, masked):
        f = make_features(masked)
        self.cur = [f"cur_{v}" for v in VARS]
        self.ctx = [c for c in f.columns if c not in self.cur]
        self.pre = SimpleImputer(strategy="median").fit(f[self.ctx])
        X = np.hstack([self.pre.transform(f[self.ctx]), f[self.cur].values])
        self.imp = IterativeImputer(
            estimator=ExtraTreesRegressor(**self.kw, n_jobs=-1, random_state=0),
            max_iter=self.max_iter, initial_strategy="median", random_state=0)
        self.imp.fit(X)
        return self
    def predict_frame(self, masked, last_only=False):
        f = _feats(masked, last_only)
        X = np.hstack([self.pre.transform(f[self.ctx]), f[self.cur].values])
        arr = self.imp.transform(X)[:, -len(VARS):]
        return postprocess(pd.DataFrame(arr, index=f.index, columns=VARS))

class M3(TwoPass):
    """Stacking: HGB + ExtraTrees + RF, RidgeCV meta-learner on out-of-fold predictions."""
    name = "M3"
    def __init__(self, n_estimators=50, max_depth=16, min_samples_leaf=10):
        self.n, self.d, self.leaf = n_estimators, max_depth, min_samples_leaf
    def _bases(self):
        return [HistGradientBoostingRegressor(random_state=0),
                filled(ExtraTreesRegressor(n_estimators=self.n, max_depth=self.d, min_samples_leaf=self.leaf, n_jobs=-1, random_state=0)),
                filled(RandomForestRegressor(n_estimators=self.n, max_depth=self.d, min_samples_leaf=self.leaf, n_jobs=-1, random_state=0))]
    def fit(self, clean, masked):
        f = make_features(masked); self._setup(f)
        self.p1 = {v: CANDIDATES["HGB"]().fit(self._p1_X(f)[clean[v].notna()], clean[v][clean[v].notna()])
                   for v in VARS}
        p1 = self._pass1(f)
        self.bases, self.meta = {}, {}
        cv = TimeSeriesSplit(n_splits=5)
        for v in VARS:
            rows = clean[v].notna()
            X, y = self._p2_X(f, p1, v)[rows], clean[v][rows]
            oof = np.full((len(X), 3), np.nan)
            for tr_i, te_i in cv.split(X):            # out-of-fold, forward in time
                for j, b in enumerate(self._bases()):
                    oof[te_i, j] = b.fit(X.iloc[tr_i], y.iloc[tr_i]).predict(X.iloc[te_i])
            ok = ~np.isnan(oof).any(axis=1)           # first fold has no OOF prediction
            self.meta[v] = RidgeCV(alphas=np.logspace(-3, 3, 13)).fit(oof[ok], y.values[ok])
            self.bases[v] = [b.fit(X, y) for b in self._bases()]
        return self
    def predict_frame(self, masked, last_only=False):
        f = _feats(masked, last_only); p1 = self._pass1(f)
        out = {}
        for v in VARS:
            X = self._p2_X(f, p1, v)
            P = np.column_stack([b.predict(X) for b in self.bases[v]])
            out[v] = self.meta[v].predict(P)
        return postprocess(pd.DataFrame(out, index=f.index))

class HGBNative(Base):
    """One gradient-boosted model per target, trained directly on features with NaN."""
    name = "HGB-native"
    def fit(self, clean, masked):
        f = make_features(masked)
        self.cols = {v: [c for c in f.columns if c != f"cur_{v}"] for v in VARS}
        self.m = {v: HistGradientBoostingRegressor(random_state=0).fit(
            f[self.cols[v]][clean[v].notna()], clean[v][clean[v].notna()]) for v in VARS}
        return self
    def predict_frame(self, masked, last_only=False):
        f = _feats(masked, last_only)
        return postprocess(pd.DataFrame({v: self.m[v].predict(f[self.cols[v]]) for v in VARS}, index=f.index))

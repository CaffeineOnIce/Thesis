"""Site adaptation of the seasonal bands for live PolluSense data (spec §5.4, Phase 4).

  python -m tools.site_adapt_bands --ratio no2=1.8 co=0.9 \
      [--kb data/seasonal_bands/knowledge_base_2023_2024.json] [--out data/seasonal_bands/knowledge_base_live.json]
  python -m tools.site_adapt_bands --live-median no2=40 pm25=70 --season post_monsoon   # decide + scale

For each pollutant given, p5, p95, mad and median are multiplied by ratio = live median / CPCB median, in every
season and (if present) every month, in a COPY of the knowledge base. mad_log is left unchanged (a multiplicative
rescaling shifts log values but does not change their spread, up to the +1 in log1p). With --live-median the
ratio is computed against the CPCB season median and applied only if the live median is outside the season's
p5-p95 band or differs from the CPCB median by more than 2x (spec §5.4). The ratios are recorded in the output's
metadata ("site_adaptation"). The original knowledge_base.json is never written.
"""
import argparse
import copy
import json
import os

ORIGINAL = os.path.normpath("data/seasonal_bands/knowledge_base.json")
SCALED = ("p5", "p95", "mad", "median")


def needs_adaptation(live_median, st):
    r = live_median / st["median"]
    return live_median < st["p5"] or live_median > st["p95"] or r > 2 or r < 0.5


def adapt(kb, ratios):
    out = copy.deepcopy(kb)
    for v, r in ratios.items():
        if r <= 0:
            raise ValueError(f"{v}: ratio must be > 0, got {r}")
        tables = [out["pollutants"][v]] + ([out["pollutants_monthly"][v]] if v in out.get("pollutants_monthly", {}) else [])
        for tab in tables:
            for st in tab.values():
                for k in SCALED:
                    if k in st:
                        st[k] = round(st[k] * r, 6)
    out.setdefault("metadata", {})["site_adaptation"] = {
        "ratios_live_over_cpcb": ratios, "scaled_fields": list(SCALED),
        "note": "spec §5.4; written by tools/site_adapt_bands.py"}
    return out


def _pairs(items):
    return {k: float(x) for k, x in (i.split("=") for i in items or [])}


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--kb", default="data/seasonal_bands/knowledge_base_2023_2024.json")
    ap.add_argument("--out", default="data/seasonal_bands/knowledge_base_live.json")
    ap.add_argument("--ratio", nargs="*", help="pollutant=ratio (live median / CPCB median)")
    ap.add_argument("--live-median", nargs="*", help="pollutant=live median; needs --season")
    ap.add_argument("--season")
    a = ap.parse_args(argv)
    if os.path.normpath(a.out) == ORIGINAL:
        raise SystemExit(f"refusing to overwrite the original {ORIGINAL}")
    with open(a.kb, encoding="utf-8-sig") as f:
        kb = json.load(f)
    ratios = _pairs(a.ratio)
    if a.live_median:
        if not a.season:
            ap.error("--live-median needs --season")
        for v, lm in _pairs(a.live_median).items():
            st = kb["pollutants"][v][a.season]
            r = lm / st["median"]
            print(f"  {v}: live {lm} / CPCB {st['median']} = {r:.3f} -> "
                  f"{'scale' if needs_adaptation(lm, st) else 'keep (inside band, within 2x)'}")
            if needs_adaptation(lm, st):
                ratios[v] = round(r, 4)
    out = adapt(kb, ratios)
    os.makedirs(os.path.dirname(a.out) or ".", exist_ok=True)
    with open(a.out, "w", encoding="utf-8") as f:
        json.dump(out, f, indent=4); f.write("\n")
    print(f"  written {a.out}; ratios {ratios}")
    return out


if __name__ == "__main__":
    main()

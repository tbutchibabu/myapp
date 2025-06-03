import os
import csv
import zipfile
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta

from flask import Flask, render_template, request, jsonify
import pandas as pd

app = Flask(__name__)

# ─── Setup ──────────────────────────────────────────────────────────────────

# Turbine code ↔ ID maps
TURBINE_MAP = {
    'DB91012': 'T01', 'DB91010': 'T02', 'DB91004': 'T03', 'DB91009': 'T04',
    'DB91003': 'T05', 'DB91006': 'T06', 'DB91005': 'T07', 'DB91008': 'T08',
    'DB91007': 'T09', 'DB91011': 'T10'
}
TURBINE_INV = {v: k for k, v in TURBINE_MAP.items()}

BASEDIR = os.path.abspath(os.path.dirname(__file__))
PARAM_CSV = os.path.join(BASEDIR, 'data', 'parameters.csv')
DATA_DIR  = os.path.join(BASEDIR, 'data', '10Min')
STATISTICS_DIR = os.path.join(BASEDIR, 'data', 'Statistics')


# ─── Robustly load parameters.csv ───────────────────────────────────────────

param_map = {}
with open(PARAM_CSV, newline='', encoding='utf-8') as f:
    reader   = csv.DictReader(f)
    raw_hdrs = reader.fieldnames or []
    hdrs     = [h.strip() for h in raw_hdrs]

    # Normalize for matching
    norm = [h.lower() for h in hdrs]

    # Look for likely columns
    code_idx = next((i for i,h in enumerate(norm)
                     if h in ('var_pk','code','id','varpk')),  None)
    name_idx = next((i for i,h in enumerate(norm)
                     if h in ('parameter','param','name','description')), None)

    # Fallback to first two columns if nothing matched
    if code_idx is None or name_idx is None:
        if len(hdrs) >= 2:
            code_idx, name_idx = 0, 1
        else:
            raise RuntimeError(f"Can't find code/name in {PARAM_CSV}: {hdrs}")

    code_col = raw_hdrs[code_idx]
    name_col = raw_hdrs[name_idx]

    # Build mapping
    for row in reader:
        code = row.get(code_col, '').strip()
        name = row.get(name_col, '').strip()
        if code and name:
            param_map[code] = name

# Reverse lookup: name → code
param_inv = {v: k for k,v in param_map.items()}


def yesterday_str():
    return (datetime.today() - timedelta(days=1))\
           .strftime("%Y-%m-%d")


# ─── Routes ─────────────────────────────────────────────────────────────────

@app.route("/")
def index():
    turbines   = sorted(TURBINE_MAP.values())
    parameters = list(param_map.values())
    aggs       = ["Average","Min","Max"]
    default_d  = yesterday_str()
    return render_template("index.html",
                           turbines=turbines,
                           parameters=parameters,
                           aggs=aggs,
                           default_date=default_d)


@app.route("/get_data", methods=["POST"])
def get_data():
    req    = request.get_json() or {}
    from_d = req.get("from_date", yesterday_str())
    to_d   = req.get("to_date",   yesterday_str())
    sel_t  = req.get("turbines",  sorted(TURBINE_MAP.values()))
    sel_p  = req.get("parameters", list(param_map.values()))
    sel_a  = req.get("agg",        ["Average"])
    aggs   = [sel_a] if isinstance(sel_a, str) else sel_a

    # Date range
    dt_from = datetime.strptime(from_d, "%Y-%m-%d")
    dt_to   = datetime.strptime(to_d,   "%Y-%m-%d") + timedelta(hours=23,minutes=59)

    # Build day-list "DD.MM.YYYY"
    days = []
    cur  = dt_from
    while cur <= dt_to:
        days.append(cur.strftime("%d.%m.%Y"))
        cur += timedelta(days=1)

    # Map selected display-names → codes
    sel_codes = [param_inv[n] for n in sel_p if n in param_inv]

    # Prepare in-memory buckets
    data = {
        code: {agg: {t: [] for t in sel_t} for agg in aggs}
        for code in sel_codes
    }

    # ── Core: loop turbines → days → open each ZIP once ────────────────
    for turb in sel_t:
        code_key = TURBINE_INV.get(turb)
        if not code_key:
            continue

        for day in days:
            # find the matching .zip
            for fname in os.listdir(DATA_DIR):
                if not fname.lower().endswith(".zip"):
                    continue
                if code_key not in fname or day not in fname:
                    continue

                try:
                    with zipfile.ZipFile(os.path.join(DATA_DIR, fname)) as zf:
                        for xml_fn in zf.namelist():
                            if not xml_fn.lower().endswith(".xml"):
                                continue
                            root = ET.fromstring(zf.read(xml_fn))
                            for mean in root.findall("MEAN"):
                                ts = mean.get("END")
                                try:
                                    dt = datetime.strptime(ts, "%d.%m.%Y %H:%M")
                                except:
                                    continue
                                if dt < dt_from or dt > dt_to:
                                    continue
                                iso_ts = dt.isoformat()

                                # Single pass over all DP tags
                                for dp in mean.findall("DP"):
                                    vpk = dp.get("VAR_PK")
                                    if vpk not in sel_codes:
                                        continue
                                    for agg in aggs:
                                        if agg=="Average":
                                            txt = dp.find("V").text if dp.find("V") is not None else None
                                        elif agg=="Min":
                                            txt = dp.get("MIN")
                                        else:
                                            txt = dp.get("MAX")
                                        try:
                                            val = float(txt)
                                        except:
                                            continue
                                        # filter unrealistic temps
                                        name_l = param_map[vpk].lower()
                                        if "temp" in name_l and val>200:
                                            continue
                                        data[vpk][agg][turb].append((iso_ts,val))
                except:
                    continue

    # Build JSON
    out = {"parameters":[]}
    for code in sel_codes:
        disp = param_map[code]
        for agg in aggs:
            traces=[]
            for turb in sel_t:
                pts = data[code][agg][turb]
                if not pts: continue
                pts.sort(key=lambda x:x[0])
                times, vals = zip(*pts)
                traces.append({
                    "turbine": turb,
                    "times":   list(times),
                    "values":  list(vals)
                })
            if traces:
                out["parameters"].append({
                    "name": f"{disp} ({agg})",
                    "unit": "",
                    "traces": traces
                })


    # Load reference power curve
    try:
        ref_path = os.path.join(app.root_path, 'data', 'refpc.csv')
        ref_df = pd.read_csv(ref_path)
        out['reference'] = {
            'wind': ref_df.iloc[:,0].tolist(),
            'power': ref_df.iloc[:,1].tolist()
        }
    except Exception:
        pass

    return jsonify(out)



@app.route("/get_dgr", methods=["POST"])
@app.route("/get_dgr", methods=["POST"])
def get_dgr():
    req = request.get_json() or {}
    from_d = req.get("from_date", yesterday_str())
    to_d = req.get("to_date",   yesterday_str())
    turbines = req.get("turbines", sorted(TURBINE_MAP.values()))

    # build list of dates
    dt_from = datetime.strptime(from_d, "%Y-%m-%d")
    dt_to   = datetime.strptime(to_d,   "%Y-%m-%d")
    days = []
    while dt_from <= dt_to:
        days.append(dt_from.strftime("%Y-%m-%d"))
        dt_from += timedelta(days=1)

    # initialize tables
    values = {d: {t: 0.0 for t in turbines} for d in days}
    availability = {d: {} for d in days}

    # populate generation & availability
    for t in turbines:
        code_key = TURBINE_INV.get(t)
        for day in days:
            dd = datetime.strptime(day, "%Y-%m-%d").strftime("%d.%m.%Y")
            downtime = 0.0
            # look for matching ZIP
            try:
                for fn in os.listdir(STATISTICS_DIR):
                    if fn.lower().endswith(".zip") and code_key in fn and dd in fn:
                        with zipfile.ZipFile(os.path.join(STATISTICS_DIR, fn)) as zf:
                            xmls = [x for x in zf.namelist() if x.lower().endswith(".xml")]
                            if not xmls:
                                continue
                            root = ET.fromstring(zf.read(xmls[0]))
                            stat = root.find("STATISTIC")
                            # sum generation
                            total_kwh = 0.0
                            for p in stat.findall("PRODUCTION"):
                                try:
                                    total_kwh += float(p.get("KWH_LastDay", "0") or 0)
                                except:
                                    pass
                            values[day][t] = total_kwh
                            # sum downtime
                            for op in stat.findall("OPERATION"):
                                if op.get("MODE") in {"1","2","3","4","5","22"}:
                                    time_str = op.get("TIMELASTDAY", "0:00:00")
                                    parts = list(map(int, time_str.split(':')))
                                    if len(parts) == 3:
                                        h,m,s = parts
                                    elif len(parts) == 2:
                                        h = 0; m,s = parts
                                    else:
                                        h = 0; m = parts[0]; s = 0
                                    downtime += h*3600 + m*60 + s
                        break
            except Exception:
                pass
            # calculate availability %
            availability[day][t] = round((86400 - downtime) / 86400 * 100, 2)

    # return both tables
    return jsonify({
        "days": days,
        "turbines": turbines,
        "values": values,
        "availability": availability
    })



@app.route("/get_powercurve", methods=["POST"])
def get_powercurve():
    """
    Expects JSON: { "from_date": "YYYY-MM-DD", "to_date": "YYYY-MM-DD", "turbines": ["T01","T02",...] }
    Returns: { "curves": [ { "turbine": <turbine>, "wind": [...], "power": [...] }, ... ] }
    """
    req = request.get_json() or {}
    from_d = req.get("from_date", yesterday_str())
    to_d   = req.get("to_date",   yesterday_str())
    sel_turbines = req.get("turbines", sorted(TURBINE_MAP.values()))

    # Parse dates (inclusive to 23:59)
    try:
        dt_from = datetime.strptime(from_d, "%Y-%m-%d")
        dt_to   = datetime.strptime(to_d,   "%Y-%m-%d") + timedelta(hours=23, minutes=59)
    except Exception:
        return jsonify({"error": "Invalid date format. Use YYYY-MM-DD."}), 400

    # Build day strings "DD.MM.YYYY"
    days = []
    cur = dt_from
    while cur <= dt_to:
        days.append(cur.strftime("%d.%m.%Y"))
        cur += timedelta(days=1)

    WIND_VARPK  = "1431"  # (Met) Wind speed
    POWER_VARPK = "634"   # (Gri) Active power

    data_dict = {t: [] for t in sel_turbines}

    for turb in sel_turbines:
        code_key = TURBINE_INV.get(turb)
        if not code_key:
            continue

        for day in days:
            for fname in os.listdir(DATA_DIR):
                if not fname.lower().endswith(".zip"):
                    continue
                if code_key not in fname or day not in fname:
                    continue
                zip_path = os.path.join(DATA_DIR, fname)

                try:
                    with zipfile.ZipFile(zip_path) as zf:
                        for xml_fn in zf.namelist():
                            if not xml_fn.lower().endswith(".xml"):
                                continue
                            root = ET.fromstring(zf.read(xml_fn))
                            for mean in root.findall("MEAN"):
                                ts = mean.get("END")
                                try:
                                    dt = datetime.strptime(ts, "%d.%m.%Y %H:%M")
                                except Exception:
                                    continue
                                if dt < dt_from or dt > dt_to:
                                    continue

                                wind_val = None
                                powr_val = None
                                for dp in mean.findall("DP"):
                                    vpk = dp.get("VAR_PK")
                                    if vpk == WIND_VARPK:
                                        txt = dp.find("V").text if dp.find("V") is not None else None
                                        if txt is not None:
                                            try:
                                                wind_val = float(txt)
                                            except:
                                                wind_val = None
                                    elif vpk == POWER_VARPK:
                                        txt = dp.find("V").text if dp.find("V") is not None else None
                                        if txt is not None:
                                            try:
                                                powr_val = float(txt)
                                            except:
                                                powr_val = None

                                # Only include points where power > 0 and < 2500
                                if wind_val is not None and powr_val is not None and 10 < powr_val < 2100:
                                    data_dict[turb].append((wind_val, powr_val))
                except Exception:
                    continue

    out = {"curves": []}
    for turb in sel_turbines:
        points = data_dict.get(turb, [])
        if not points:
            continue
        points.sort(key=lambda x: x[0])
        winds  = [p[0] for p in points]
        powers = [p[1] for p in points]
        out["curves"].append({
            "turbine": turb,
            "wind":    winds,
            "power":   powers
        })


    # Load reference power curve
    try:
        ref_path = os.path.join(app.root_path, 'data', 'refpc.csv')
        ref_df = pd.read_csv(ref_path)
        out['reference'] = {
            'wind': ref_df.iloc[:,0].tolist(),
            'power': ref_df.iloc[:,1].tolist()
        }
    except Exception:
        pass

    return jsonify(out)

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8000, debug=False)

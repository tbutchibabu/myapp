import os
import io
import csv
import zipfile

# ─── Switch to lxml for faster XML parsing ──────────────────────────────
from lxml import etree as ET
# ────────────────────────────────────────────────────────────────────────

from datetime import datetime, timedelta
from flask import Flask, render_template, request, jsonify
import pandas as pd

# ─── GCS Client setup ────────────────────────────────────────────────────
from google.cloud import storage
GCS_BUCKET_NAME = "tulugudata"
GCS_PREFIX      = "data"
_storage_client = storage.Client()
_bucket         = _storage_client.bucket(GCS_BUCKET_NAME)
# ────────────────────────────────────────────────────────────────────────

app = Flask(__name__)

# ─── “DB910##” → “T0#” mapping (exactly as in your original code) ────────
TURBINE_MAP = {
    'DB91012': 'T01',
    'DB91010': 'T02',
    'DB91004': 'T03',
    'DB91009': 'T04',
    'DB91003': 'T05',
    'DB91006': 'T06',
    'DB91005': 'T07',
    'DB91008': 'T08',
    'DB91007': 'T09',
    'DB91011': 'T10'
}
TURBINE_INV = {v: k for k, v in TURBINE_MAP.items()}
# ────────────────────────────────────────────────────────────────────────

def yesterday_str():
    return (datetime.utcnow() - timedelta(days=1)).strftime("%Y-%m-%d")

# ─── Load parameters.csv from GCS once (at startup) ──────────────────────
param_map = {}
param_blob = _bucket.blob(f"{GCS_PREFIX}/parameters.csv")
param_bytes = param_blob.download_as_bytes()
param_stream = io.StringIO(param_bytes.decode("utf-8"))
reader = csv.DictReader(param_stream)
raw_hdrs = reader.fieldnames or []
hdrs = [h.strip() for h in raw_hdrs]
norm = [h.lower() for h in hdrs]

code_idx = next((i for i, h in enumerate(norm) if h in ("var_pk","code","id","varpk")), None)
name_idx = next((i for i, h in enumerate(norm) if h in ("parameter","param","name","description")), None)
if code_idx is None or name_idx is None:
    if len(hdrs) >= 2:
        code_idx, name_idx = 0, 1
    else:
        raise RuntimeError(f"Cannot locate code/name columns in PARAMETERS.CSV: {hdrs}")

code_col = raw_hdrs[code_idx]
name_col = raw_hdrs[name_idx]

for row in reader:
    code = row.get(code_col, "").strip()
    name = row.get(name_col, "").strip()
    if code and name:
        param_map[code] = name

param_inv = {v: k for k, v in param_map.items()}
# ────────────────────────────────────────────────────────────────────────

@app.route("/")
def index():
    turbines   = sorted(TURBINE_MAP.values())
    parameters = list(param_map.values())
    aggs       = ["Average", "Min", "Max"]
    default_d  = yesterday_str()
    return render_template(
        "index.html",
        turbines=turbines,
        parameters=parameters,
        aggs=aggs,
        default_date=default_d
    )

@app.route("/get_data", methods=["POST"])
def get_data():
    req = request.get_json() or {}
    from_d = req.get("from_date", yesterday_str())
    to_d   = req.get("to_date",   yesterday_str())
    sel_t  = req.get("turbines",  sorted(TURBINE_MAP.values()))
    sel_p  = req.get("parameters", list(param_map.values()))
    sel_a  = req.get("agg",        ["Average"])
    aggs   = [sel_a] if isinstance(sel_a, str) else sel_a

    # Parse the date range into datetime objects
    dt_from = datetime.strptime(from_d, "%Y-%m-%d")
    dt_to   = datetime.strptime(to_d,   "%Y-%m-%d") + timedelta(hours=23, minutes=59)

    # Build list of “DD.MM.YYYY” strings
    days = []
    cur = dt_from
    while cur <= dt_to:
        days.append(cur.strftime("%d.%m.%Y"))
        cur += timedelta(days=1)

    # Map selected parameter *names* → VAR_PK *codes*
    sel_codes = [param_inv[n] for n in sel_p if n in param_inv]

    # Initialize an in‐memory data structure:
    #   data[VAR_PK][agg][turbine] = list of (iso_ts, value)
    data = {
        code: { agg: { t: [] for t in sel_t } for agg in aggs }
        for code in sel_codes
    }

    for turb in sel_t:
        code_key = TURBINE_INV.get(turb)  # e.g. "DB91003"
        if not code_key:
            continue

        for day in days:
            # Construct the exact GCS object name:
            #   "data/10Min/DB91003 LOG 03.06.2025.zip"
            blob_name = f"{GCS_PREFIX}/10Min/{code_key} LOG {day}.zip"
            blob = _bucket.blob(blob_name)
            if not blob.exists():
                # If that exact ZIP does not exist, skip
                continue

            try:
                zip_bytes = blob.download_as_bytes()
                with zipfile.ZipFile(io.BytesIO(zip_bytes)) as zf:
                    for xml_fn in zf.namelist():
                        if not xml_fn.lower().endswith(".xml"):
                            continue
                        xml_data = zf.read(xml_fn)
                        root = ET.fromstring(xml_data)
                        for mean in root.findall("MEAN"):
                            ts = mean.get("END")
                            try:
                                dt = datetime.strptime(ts, "%d.%m.%Y %H:%M")
                            except:
                                continue
                            if dt < dt_from or dt > dt_to:
                                continue
                            iso_ts = dt.isoformat()

                            for dp in mean.findall("DP"):
                                vpk = dp.get("VAR_PK")
                                if vpk not in sel_codes:
                                    continue
                                for agg in aggs:
                                    if agg == "Average":
                                        txt = dp.find("V").text if dp.find("V") is not None else None
                                    elif agg == "Min":
                                        txt = dp.get("MIN")
                                    else:  # agg == "Max"
                                        txt = dp.get("MAX")
                                    try:
                                        val = float(txt)
                                    except:
                                        continue
                                    name_l = param_map[vpk].lower()
                                    # Skip unrealistic “temp” values
                                    if "temp" in name_l and val > 200:
                                        continue
                                    data[vpk][agg][turb].append((iso_ts, val))
            except Exception:
                # If download/parsing fails for any reason, skip this ZIP
                continue

    # Build the JSON response
    out = {"parameters": []}
    for code in sel_codes:
        disp = param_map[code]
        for agg in aggs:
            traces = []
            for turb in sel_t:
                pts = data[code][agg][turb]
                if not pts:
                    continue
                pts.sort(key=lambda x: x[0])
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

    # Load reference power curve from GCS (still only one CSV)
    try:
        ref_blob  = _bucket.blob(f"{GCS_PREFIX}/refpc.csv")
        ref_bytes = ref_blob.download_as_bytes()
        ref_df    = pd.read_csv(io.BytesIO(ref_bytes))
        out["reference"] = {
            "wind":  ref_df.iloc[:, 0].tolist(),
            "power": ref_df.iloc[:, 1].tolist()
        }
    except Exception:
        pass

    return jsonify(out)

@app.route("/get_dgr", methods=["POST"])
def get_dgr():
    req      = request.get_json() or {}
    from_d   = req.get("from_date", yesterday_str())
    to_d     = req.get("to_date",   yesterday_str())
    turbines = req.get("turbines",  sorted(TURBINE_MAP.values()))

    dt_from = datetime.strptime(from_d, "%Y-%m-%d")
    dt_to   = datetime.strptime(to_d,   "%Y-%m-%d")

    days = []
    while dt_from <= dt_to:
        days.append(dt_from.strftime("%Y-%m-%d"))
        dt_from += timedelta(days=1)

    values       = {d: {t: 0.0 for t in turbines} for d in days}
    availability = {d: {} for d in days}

    for t in turbines:
        code_key = TURBINE_INV.get(t)  # e.g. "DB91003"
        for day in days:
            # We expect statistics ZIP named like:
            #   "data/Statistics/DB91003 LOG STAT 03.06.2025.zip"
            dd = datetime.strptime(day, "%Y-%m-%d").strftime("%d.%m.%Y")
            stat_blob_name = f"{GCS_PREFIX}/Statistics/{code_key} LOG STAT {dd}.zip"
            blob = _bucket.blob(stat_blob_name)
            if not blob.exists():
                continue

            downtime = 0.0
            try:
                zip_bytes = blob.download_as_bytes()
                with zipfile.ZipFile(io.BytesIO(zip_bytes)) as zf:
                    xmls = [x for x in zf.namelist() if x.lower().endswith(".xml")]
                    if not xmls:
                        continue
                    root = ET.fromstring(zf.read(xmls[0]))
                    stat = root.find("STATISTIC")
                    total_kwh = 0.0
                    for p in stat.findall("PRODUCTION"):
                        try:
                            total_kwh += float(p.get("KWH_LastDay", "0") or 0)
                        except:
                            pass
                    values[day][t] = total_kwh

                    for op in stat.findall("OPERATION"):
                        mode = op.get("MODE")
                        if mode in {"1", "2", "3", "4", "5", "22"}:
                            time_str = op.get("TIMELASTDAY", "0:00:00")
                            parts = list(map(int, time_str.split(":")))
                            if len(parts) == 3:
                                h, m, s = parts
                            elif len(parts) == 2:
                                h = 0; m, s = parts
                            else:
                                h = 0; m = parts[0]; s = 0
                            downtime += h * 3600 + m * 60 + s
            except Exception:
                continue

            availability[day][t] = round((86400 - downtime) / 86400 * 100, 2)

    return jsonify({
        "days": days,
        "turbines": turbines,
        "values": values,
        "availability": availability
    })

@app.route("/get_powercurve", methods=["POST"])
def get_powercurve():
    req = request.get_json() or {}
    from_d = req.get("from_date", yesterday_str())
    to_d   = req.get("to_date",   yesterday_str())
    sel_turbines = req.get("turbines", sorted(TURBINE_MAP.values()))

    try:
        dt_from = datetime.strptime(from_d, "%Y-%m-%d")
        dt_to   = datetime.strptime(to_d,   "%Y-%m-%d") + timedelta(hours=23, minutes=59)
    except:
        return jsonify({"error": "Invalid date format. Use YYYY-MM-DD."}), 400

    days = []
    cur = dt_from
    while cur <= dt_to:
        days.append(cur.strftime("%d.%m.%Y"))
        cur += timedelta(days=1)

    WIND_VARPK  = "1431"   # (Met) wind speed 1
    POWER_VARPK = "634"    # (Gri) active power 1sec.

    data_dict = {t: [] for t in sel_turbines}

    for turb in sel_turbines:
        code_key = TURBINE_INV.get(turb)
        if not code_key:
            continue

        for day in days:
            # Build the exact blob name for each turbine-day ZIP
            blob_name = f"{GCS_PREFIX}/10Min/{code_key} LOG {day}.zip"
            blob = _bucket.blob(blob_name)
            if not blob.exists():
                continue

            try:
                zip_bytes = blob.download_as_bytes()
                with zipfile.ZipFile(io.BytesIO(zip_bytes)) as zf:
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

                            wind_val = None
                            powr_val = None
                            for dp in mean.findall("DP"):
                                vpk = dp.get("VAR_PK")
                                if vpk == WIND_VARPK:
                                    txt = dp.find("V").text if dp.find("V") is not None else None
                                    try:
                                        wind_val = float(txt) if txt is not None else None
                                    except:
                                        wind_val = None
                                elif vpk == POWER_VARPK:
                                    txt = dp.find("V").text if dp.find("V") is not None else None
                                    try:
                                        powr_val = float(txt) if txt is not None else None
                                    except:
                                        powr_val = None

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

    # Load reference power curve from GCS
    try:
        ref_blob   = _bucket.blob(f"{GCS_PREFIX}/refpc.csv")
        ref_bytes  = ref_blob.download_as_bytes()
        ref_df     = pd.read_csv(io.BytesIO(ref_bytes))
        out["reference"] = {
            "wind":  ref_df.iloc[:, 0].tolist(),
            "power": ref_df.iloc[:, 1].tolist()
        }
    except Exception:
        pass

    return jsonify(out)


if __name__ == "__main__":
    # Cloud Run expects your app to listen on 0.0.0.0:$PORT
    port = int(os.environ.get("PORT", 8080))
    app.run(host="0.0.0.0", port=port, debug=False)

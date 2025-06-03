let countdownInterval, remainingSecs, lastData = null;

// ─── Utility & UI Helpers ────────────────────────────────────────────────
function toggleCheckboxes(id) {
  document.querySelectorAll('.checkboxes').forEach(panel => {
    panel.style.display = panel.id===id+'-checkboxes'
      ? (panel.style.display==='block'?'none':'block')
      : 'none';
  });
}

function filterParameters() {
  const q = document.getElementById('param-search').value.toLowerCase();
  document.querySelectorAll('#parameters-checkboxes label').forEach(lbl=>{
    const cb = lbl.querySelector('input.param-chk');
    if(!cb) return;
    lbl.style.display = lbl.textContent.toLowerCase().includes(q)
      ? 'block':'none';
  });
}

function getChecked(cls){
  return Array.from(document.querySelectorAll(`.${cls}:checked`))
              .map(cb=>cb.value);
}
function updateTurbineLabel(){
  document.getElementById('turbines-placeholder')
    .textContent = `Turbines (${getChecked('turbine-chk').length})`;
}
function updateParameterLabel(){
  document.getElementById('parameters-placeholder')
    .textContent = `Parameters (${getChecked('param-chk').length})`;
}
function updateAggregationLabel(){
  const a=getChecked('agg-chk');
  document.getElementById('aggregations-placeholder')
    .textContent = a.length?a.join(', '):'Select Aggregations';
}

function showInlineLoading(){
  clearInterval(countdownInterval);
  ['plot-btn','download-csv-btn','download-pdf-btn']
    .forEach(id=>document.getElementById(id).disabled=true);
  document.getElementById('loading-indicator').style.display='inline-flex';
  document.getElementById('loading-text')
    .textContent = `Est. time: ${remainingSecs}s`;
  countdownInterval = setInterval(()=>{
    remainingSecs=Math.max(0,remainingSecs-1);
    document.getElementById('loading-text')
      .textContent = `Est. time: ${remainingSecs}s`;
    if(remainingSecs===0) clearInterval(countdownInterval);
  },1000);
}

function hideInlineLoading(loadTime){
  clearInterval(countdownInterval);
  document.getElementById('loading-indicator').style.display='none';
  ['plot-btn','download-csv-btn','download-pdf-btn']
    .forEach(id=>document.getElementById(id).disabled=false);
  document.getElementById('status-message')
    .textContent = `Loaded in ${loadTime.toFixed(2)}s`;
}

// ─── Main Fetch & Render ─────────────────────────────────────────────────
async function fetchData(){
  document.getElementById('status-message').textContent='';
  const fromDate   = document.getElementById('from_date').value;
  const toDate     = document.getElementById('to_date').value;
  const turbines   = getChecked('turbine-chk');
  const parameters = getChecked('param-chk');
  const aggs       = getChecked('agg-chk');
  const mode       = document.getElementById('chart-type').value;
  
  
  if (mode === 'dgr') {
    // hide other panels
    document.getElementById('parameters-checkboxes').closest('.multiselect').style.display = 'none';
    document.getElementById('aggregations-checkboxes').closest('.multiselect').style.display = 'none';

    if (!turbines.length) {
      alert('Select at least one turbine.');
      return;
    }

    // calculate ETA and show loading
    const days = Math.max(1, (new Date(toDate) - new Date(fromDate)) / (1000 * 60 * 60 * 24));
    remainingSecs = Math.ceil(turbines.length * days * 0.3);
    showInlineLoading();

    const t0 = performance.now();
    try {
      const resp = await fetch('/get_dgr', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ from_date: fromDate, to_date: toDate, turbines: turbines })
      });
      const json = await resp.json();
      lastData = { mode: 'dgr', turbines: json.turbines, days: json.days, values: json.values, downtime: json.downtime };

      // 1) Generation Table
      let html = '<h3>Daily Generation (kWh)</h3><table class="dgr-table"><thead><tr><th>Date</th>' +
        json.turbines.map(t => `<th>${t}</th>`).join('') +
        '</tr></thead><tbody>';
      json.days.forEach(day => {
        html += `<tr><td>${day}</td>` +
          json.turbines.map(t => `<td>${json.values[day][t].toFixed(0)}</td>`).join('') +
          '</tr>';
      });
      html += '</tbody></table>';

      document.getElementById('graphs').innerHTML = html;

      const loadTime = (performance.now() - t0) / 1000;
      hideInlineLoading(loadTime);
    } catch (err) {
      hideInlineLoading(0);
      alert('Error loading DGR');
    }
    return;
  }

  // ── Power Curve branch ────────────────────────────────────────────────────
  if (mode === 'powercurve') {
    // Hide parameter & aggregation selectors
    document.getElementById('parameters-checkboxes').closest('.multiselect').style.display = 'none';
    document.getElementById('aggregations-checkboxes').closest('.multiselect').style.display = 'none';

    if (!turbines.length) {
      return alert('Select at least one turbine.');
    }

    // Estimate loading time: turbines × days × 0.3s
    const days = Math.max(1, (new Date(toDate) - new Date(fromDate)) / (1000 * 60 * 60 * 24));
    remainingSecs = Math.ceil(turbines.length * days * 0.3);
    showInlineLoading();

    const t0 = performance.now();
    try {
      const resp = await fetch('/get_powercurve', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          from_date: fromDate,
          to_date:   toDate,
          turbines:  turbines
        })
      });
      const json = await resp.json();

      const traces = [];
      json.curves.forEach(curve => {
        traces.push({
          x: curve.wind,
          y: curve.power,
          mode: 'markers',
          name: curve.turbine,
          marker: { size: 5 }
        });
      });
        // Add reference power curve line
        if (json.reference) {
          traces.push({
            x: json.reference.wind,
            y: json.reference.power,
            mode: 'lines',
            name: 'Reference',
            line: { dash: 'line', color: 'blue' }
          });
        }


      const container = document.getElementById('graphs');
      container.innerHTML = '<div id="powercurve-div" class="chart"></div>';

      const layout = {
        title: 'Power Curve (Wind Speed vs Power)',
        xaxis: { title: 'Wind Speed (m/s)' },
        yaxis: { title: 'Active Power (kW)' },
        showlegend: true
      };
      Plotly.newPlot('powercurve-div', traces, layout);

      const loadTime = (performance.now() - t0) / 1000;
      hideInlineLoading(loadTime);
    } catch (err) {
      hideInlineLoading(0);
      alert('Error loading Power Curve');
    }
    return;
  }
  // ─────────────────────────────────────────────────────────────────────────

  if(!turbines.length||!parameters.length){
    return alert('Select at least one turbine and parameter.');
  }

  // ETA based on turbines x days x 0.3s
  const days=Math.max(1,(new Date(toDate)-new Date(fromDate))/(1000*60*60*24));
  remainingSecs=Math.ceil(turbines.length*days*0.3);
  showInlineLoading();

  const t0=performance.now();
  const resp=await fetch('/get_data',{
    method:'POST',
    headers:{'Content-Type':'application/json'},
    body:JSON.stringify({
      from_date:  fromDate,
      to_date:    toDate,
      turbines:   turbines,
      parameters: parameters,
      agg:        aggs
    })
  });
  const data=await resp.json();
  lastData=data;

  const container=document.getElementById('graphs');
  container.innerHTML='';

  // ── Temperature & Data-Bar Alerts ───────────────────────────────────────
if (mode === 'alerts') {
  const wrap = document.createElement('div');
  wrap.className = 'alerts-table';

  const tbl = document.createElement('table');
  tbl.className = 'max-table';
  const th = tbl.createTHead().insertRow();
  const c0 = th.insertCell();
  c0.textContent = 'Parameter';
  c0.style.backgroundColor = '#add8e6';

  // turbine columns
  data.parameters[0].traces.forEach(t => {
    th.insertCell().textContent = t.turbine;
  });

  const tb = tbl.createTBody();

  data.parameters.forEach(p => {
    const row = tb.insertRow();
    row.insertCell().textContent = p.name;

    // compute per-turbine maxima and overall max
    const maxima = p.traces.map(t => Math.max(...t.values));
    const avg    = maxima.reduce((s, v) => s + v, 0) / maxima.length;
    const maxAll = Math.max(...maxima);

    // decimal rules
    const isTemp             = p.name.toLowerCase().includes('temp');
    const isGriActivePower   = p.name === '(Gri) Active power ,1sec';
    const decimals           = isGriActivePower ? 0 : 1;

    p.traces.forEach((t, i) => {
      const maxV = maxima[i];
      const cell = row.insertCell();

      if (isTemp) {
        // existing temp thresholds
        if      (maxV > avg * 1.3) cell.style.backgroundColor = 'rgb(255,102,102)';
        else if (maxV > avg * 1.2) cell.style.backgroundColor = 'rgb(255,255,153)';
        else if (maxV > avg * 1.1) cell.style.backgroundColor = 'lightgrey';
        else                       cell.style.backgroundColor = 'lightgreen';
      } else {
        // blue data-bar for non-temps
        const pct = maxAll > 0 ? (maxV / maxAll) * 100 : 0;
        cell.style.position   = 'relative';
        cell.style.background = `linear-gradient(to right, #2196F3 ${pct}%, transparent ${pct}%)`;
      }

      // render with 1 decimal (0 for the one special param)
      cell.textContent = maxV.toFixed(decimals);
    });
  });

  wrap.appendChild(tbl);
  container.appendChild(wrap);
}
  // ── Time Series & HeatMap ───────────────────────────────────────────
  else if(mode==='timeseries'||mode==='heatmap'){
    data.parameters.forEach((p,i)=>{
      const div=document.createElement('div');
      div.id='chart'+i; div.className='chart';
      container.appendChild(div);

      if(mode==='timeseries'){
        Plotly.newPlot(div.id,
          p.traces.map(t=>({
            x:t.times, y:t.values,
            name:t.turbine, mode:'lines'
          })),
          {title:p.name, xaxis:{type:'date'}, height:600}
        );
      } else {
        Plotly.newPlot(div.id,[{
          x:p.traces[0].times,
          y:p.traces.map(t=>t.turbine),
          z:p.traces.map(t=>t.values),
          type:'heatmap',
          colorscale:[[0,'green'],[0.5,'yellow'],[1,'red']]
        }],{title:p.name,height:600});
      }
    });
  }
  
  // ── Day-wise Average ────────────────────────────────────────────────
  else if(mode==='dayavg'){
    lastData.parameters.forEach(p => {
      // header
      const h3=document.createElement('h3');
      h3.textContent=p.name;
      h3.style.marginTop='24px';
      container.appendChild(h3);

      const wrap=document.createElement('div');
      wrap.className='dayavg-group';
      container.appendChild(wrap);

      // build map of sums & counts per day per turbine
      const mapDay={};
      p.traces.forEach(t=>{
        t.times.forEach((ts,i)=>{
          const day=ts.split('T')[0];
          if(!mapDay[day]) mapDay[day]={};
          const rec=mapDay[day][t.turbine]||{sum:0,cnt:0};
          rec.sum+=t.values[i];
          rec.cnt++;
          mapDay[day][t.turbine]=rec;
        });
      });

      // table
      const tbl=document.createElement('table');
      const thead=tbl.createTHead().insertRow();
      thead.insertCell().textContent='Date';
      p.traces.forEach(t=>thead.insertCell().textContent=t.turbine);

      const tbody=tbl.createTBody();
      Object.keys(mapDay).sort().forEach(day=>{
        const row=tbody.insertRow();
        row.insertCell().textContent=day;
        p.traces.forEach(t=>{
          const rec=mapDay[day][t.turbine];
          row.insertCell().textContent=rec?(rec.sum/rec.cnt).toFixed(2):'0.00';
        });
      });

      wrap.appendChild(tbl);
    });
    const loadTime=(performance.now()-t0)/1000;
    hideInlineLoading(loadTime);
    return;
  }
// ── Day-wise Max ────────────────────────────────────────────────────
  else if(mode==='daymax'){
    data.parameters.forEach(p=>{
      // header
      const h3=document.createElement('h3');
      h3.textContent=p.name;
      h3.style.marginTop='24px';
      container.appendChild(h3);

      const wrap=document.createElement('div');
      wrap.className='daymax-group';
      wrap.style.display='flex'; wrap.style.gap='24px'; wrap.style.marginBottom='32px';

      // value table
      const vt=document.createElement('table');
      const vh=vt.createTHead().insertRow();
      vh.insertCell().textContent='Date';
      p.traces.forEach(t=>vh.insertCell().textContent=t.turbine);
      const vb=vt.createTBody();

      // time table
      const tt=document.createElement('table');
      const th=tt.createTHead().insertRow();
      th.insertCell().textContent='Date';
      p.traces.forEach(t=>th.insertCell().textContent=t.turbine);
      const tb=tt.createTBody();

      // gather per-day max & time
      const mapDay={};
      p.traces.forEach(t=>{
        t.times.forEach((ts,i)=>{
          const [d,tm]=ts.split('T');
          if(!mapDay[d]) mapDay[d]={};
          const v=t.values[i];
          if(!mapDay[d][t.turbine]||v>mapDay[d][t.turbine].val){
            mapDay[d][t.turbine]={val:v,time:tm.slice(0,5)};
          }
        });
      });

      Object.keys(mapDay).sort().forEach(d=>{
        const rv=vb.insertRow();
        const rt=tb.insertRow();
        rv.insertCell().textContent=d;
        rt.insertCell().textContent=d;
        p.traces.forEach(t=>{
          const rec=mapDay[d][t.turbine]||{};
          rv.insertCell().textContent=rec.val?.toFixed(2)||'';
          rt.insertCell().textContent=rec.time||'';
        });
      });

      wrap.appendChild(vt);
      wrap.appendChild(tt);
      container.appendChild(wrap);
    });
  }

  const loadTime=(performance.now()-t0)/1000;
  hideInlineLoading(loadTime);
}

// ─── Close dropdowns on outside click ────────────────────────────────
document.addEventListener('click',e=>{
  if(!e.target.closest('.multiselect')){
    document.querySelectorAll('.checkboxes')
      .forEach(c=>c.style.display='none');
  }
});

// ─── Initialize & bind ─────────────────────────────────────────────────
window.addEventListener('DOMContentLoaded',()=>{
  // chart‐type → adjust default parameters
  
document.getElementById('chart-type')
    .addEventListener('change', function(){
      const mode = this.value;
      const boxes = Array.from(document.querySelectorAll('.param-chk'));
      if (mode === 'alerts') {
        boxes.forEach((cb,i)=>cb.checked=(i<20));
      } else if (mode === 'dayavg') {
        boxes.forEach(cb => cb.checked = (cb.value === '(Met) Wind speed 1/2 ,calibration Act.'));
      } else {
        boxes.forEach((cb,i)=>cb.checked=(i===0));
      }
      document.getElementById('parameters-all').checked = false;
      updateParameterLabel();
    });


  // Turbines “Select All”
  const allTur=document.getElementById('turbines-all');
  allTur.addEventListener('change',e=>{
    document.querySelectorAll('.turbine-chk')
      .forEach(cb=>cb.checked=e.target.checked);
    updateTurbineLabel();
  });
  document.querySelectorAll('.turbine-chk').forEach(cb=>{
    cb.addEventListener('change',()=>{
      allTur.checked=
        getChecked('turbine-chk').length===
        document.querySelectorAll('.turbine-chk').length;
      updateTurbineLabel();
    });
  });

  // Parameters “Select All” (visible only)
  const allPar=document.getElementById('parameters-all');
  allPar.addEventListener('change',e=>{
    Array.from(document.querySelectorAll('#parameters-checkboxes input.param-chk'))
      .filter(cb=>cb.closest('label').style.display!=='none')
      .forEach(cb=>cb.checked=e.target.checked);
    updateParameterLabel();
  });
  document.querySelectorAll('.param-chk').forEach(cb=>{
    cb.addEventListener('change',()=>{
      const vis=Array.from(
        document.querySelectorAll('#parameters-checkboxes input.param-chk')
      ).filter(cb=>cb.closest('label').style.display!=='none');
      allPar.checked=vis.length>0 && vis.every(cb=>cb.checked);
      updateParameterLabel();
    });
  });

  // Aggregations
  const allAgg=document.getElementById('aggregations-all');
  allAgg.addEventListener('change',e=>{
    document.querySelectorAll('.agg-chk')
      .forEach(cb=>cb.checked=e.target.checked);
    updateAggregationLabel();
  });
  document.querySelectorAll('.agg-chk').forEach(cb=>{
    cb.addEventListener('change',()=>{
      allAgg.checked=
        getChecked('agg-chk').length===
        document.querySelectorAll('.agg-chk').length;
      updateAggregationLabel();
    });
  });

  document.getElementById('plot-btn').addEventListener('click',fetchData);
  document.getElementById('download-csv-btn').addEventListener('click',downloadCSV);
  document.getElementById('download-pdf-btn').addEventListener('click',downloadPDF);

  updateTurbineLabel();
  updateParameterLabel();
  updateAggregationLabel();
});

// ─── CSV Download ────────────────────────────────────────────────────────
function downloadCSV(){
  if(!lastData) return alert('No data to download.');
  const mode=document.getElementById('chart-type').value;
  const rows=[];
  if(mode==='dgr'){
    rows.push(['Date', ...lastData.turbines]);
    lastData.days.forEach(day=>{
      rows.push([day, ...lastData.turbines.map(t=>lastData.values[day][t].toFixed(0))]);
    });
  }
  else if(mode==='dayavg'){
    rows.push(['Parameter','Date', ...lastData.parameters[0].traces.map(t=>t.turbine)]);
    lastData.parameters.forEach(p => {
      const mapDay = {};
      p.traces.forEach(t => {
        t.times.forEach((ts,i) => {
          const d = ts.split('T')[0];
          mapDay[d] = mapDay[d] || {};
          const rec = mapDay[d][t.turbine] || {sum:0, cnt:0};
          rec.sum += t.values[i];
          rec.cnt += 1;
          mapDay[d][t.turbine] = rec;
        });
      });
      Object.keys(mapDay).sort().forEach(day => {
        const row = [p.name, day];
        lastData.parameters[0].traces.forEach(t => {
          const rec = mapDay[day][t.turbine];
          row.push(rec ? (rec.sum/rec.cnt).toFixed(2) : '0.00');
        });
        rows.push(row);
      });
    });
  }
  else

  if(mode==='timeseries'||mode==='heatmap'){
    rows.push(['Parameter','Turbine','Timestamp','Value']);
    lastData.parameters.forEach(p=>{
      p.traces.forEach(t=>{
        t.times.forEach((ts,i)=>{
          rows.push([p.name,t.turbine,ts,t.values[i]]);
        });
      });
    });
  }
  else if(mode==='alerts'){
    rows.push(['Parameter','Turbine','Max Value']);
    lastData.parameters.forEach(p=>{
      p.traces.forEach(t=>{
        rows.push([p.name,t.turbine, Math.max(...t.values)]);
      });
    });
  }
  else {
    rows.push(['Parameter','Date','Turbine','Max','Time']);
    lastData.parameters.forEach(p=>{
      const md={};
      p.traces.forEach(t=>{
        t.times.forEach((ts,i)=>{
          const [d,tm]=ts.split('T');
          if(!md[d]) md[d]={};
          const v=t.values[i];
          if(!md[d][t.turbine]||v>md[d][t.turbine].val){
            md[d][t.turbine]={val:v,time:tm.slice(0,5)};
          }
        });
      });
      Object.keys(md).sort().forEach(d=>{
        Object.entries(md[d]).forEach(([tu,r])=>{
          rows.push([p.name,d,tu,r.val,r.time]);
        });
      });
    });
  }

  const csv=rows.map(r=>r.map(c=>`"${c}"`).join(',')).join('\r\n');
  const blob=new Blob([csv],{type:'text/csv'});
  const link=document.createElement('a');
  link.href=URL.createObjectURL(blob);
  link.download=`windtree_${mode}.csv`;
  link.click();
}

// ─── PDF Download ────────────────────────────────────────────────────────
async function downloadPDF() {
  if (!lastData) return alert('No data to PDF.');

  const graphsEl = document.getElementById('graphs');
  const from     = document.getElementById('from_date').value;
  const to       = document.getElementById('to_date').value;
  const fn       = `windtree_${from}_to_${to}.pdf`;

  // Measure full scrollable dimensions
  const fullWidth  = graphsEl.scrollWidth;
  const fullHeight = graphsEl.scrollHeight;

  const opt = {
    margin:   0.5,
    filename: fn,
    image:    { type: 'jpeg', quality: 1 },
    html2canvas: {
      width:       fullWidth,
      height:      fullHeight,
      windowWidth: fullWidth,
      windowHeight: fullHeight,
      scale:       1
    },
    jsPDF: {
      unit:        'in',
      format:      'letter',
      orientation: 'landscape'
    },
    // Let html2pdf break pages where CSS says “page-break-after: always”
    pagebreak: {
      mode: ['css', 'legacy']
    }
  };

  await html2pdf()
    .set(opt)
    .from(graphsEl)
    .save();
}


// ─── On load: default mode & dates ──────────────────────────────────────
window.onload=()=>{
  document.getElementById('chart-type').value='alerts';
  const d=new Date(); d.setDate(d.getDate()-1);
  const pad=n=>String(n).padStart(2,'0');
  const iso=`${d.getFullYear()}-${pad(d.getMonth()+1)}-${pad(d.getDate())}`;
  document.getElementById('from_date').value=iso;
  document.getElementById('to_date').value=iso;
  fetchData();
  updateTurbineLabel();
  updateParameterLabel();
  updateAggregationLabel();
};

document.getElementById('chart-type').addEventListener('change', function(){
  const mode = this.value;

  // PARAMETER selection & visibility
  const paramMS = document.getElementById('parameters-checkboxes').closest('.multiselect');
  const paramBoxes = Array.from(document.querySelectorAll('.param-chk'));
  if (mode === 'alerts') {
    paramBoxes.forEach((cb, i) => cb.checked = (i < 20));
    paramMS.style.display = '';
  } else if (mode === 'dayavg') {
    paramBoxes.forEach(cb => cb.checked = (cb.value === '(Met) Wind speed 1/2 ,calibration Act.'));
    paramMS.style.display = '';
  } else if (mode === 'dgr') {
    // hide parameters in DGR
    paramBoxes.forEach(cb => cb.checked = false);
    paramMS.style.display = 'none';
  } else if (mode === 'powercurve') {
    // hide parameters in Powercurve
    paramBoxes.forEach(cb => cb.checked = false);
    paramMS.style.display = 'none';
  } else {
    // show & default first parameter for other modes
    paramBoxes.forEach((cb, i) => cb.checked = (i === 0));
    paramMS.style.display = '';
  }
  document.getElementById('parameters-all').checked = false;
  updateParameterLabel();

  // AGGREGATIONS default & visibility
  const aggMS = document.getElementById('aggregations-checkboxes').closest('.multiselect');
  const aggBoxes = Array.from(document.querySelectorAll('.agg-chk'));
  if (mode === 'dayavg') {
    aggMS.style.display = 'none';
    aggBoxes.forEach(cb => cb.checked = (cb.value === 'Average'));
  } else if (mode === 'dgr') {
    aggMS.style.display = 'none';
    aggBoxes.forEach(cb => cb.checked = false);
  } else if (mode === 'powercurve') {
    aggMS.style.display = 'none';
    aggBoxes.forEach(cb => cb.checked = false);
  } else {
    aggMS.style.display = '';
    aggBoxes.forEach(cb => cb.checked = (cb.value === 'Max'));
  }
  document.getElementById('aggregations-all').checked = false;
  updateAggregationLabel();
});

// Trigger defaults on load
document.getElementById('chart-type').dispatchEvent(new Event('change'));


// Trigger defaults on load
document.getElementById('chart-type').dispatchEvent(new Event('change'));

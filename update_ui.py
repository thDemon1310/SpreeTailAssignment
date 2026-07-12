import re

with open("frontend/src/pages/ImportPage.jsx", "r") as f:
    content = f.read()

# Add states
content = content.replace(
    'const [loading, setLoading] = useState(true);',
    'const [loading, setLoading] = useState(true);\n    const [previewMode, setPreviewMode] = useState(false);\n    const [csvPreview, setCsvPreview] = useState(null);\n    const [anomalyFilter, setAnomalyFilter] = useState("all");\n    const [resolvedFeedback, setResolvedFeedback] = useState(null);'
)

# Update handleFileChange
handle_file_change = """  const handleFileChange = (e) => {
    const f = e.target.files[0];
    setFile(f);
    if (f) {
      const reader = new FileReader();
      reader.onload = (evt) => {
        const text = evt.target.result;
        const lines = text.split('\\n').filter(l => l.trim());
        if (lines.length > 0) {
          const headers = lines[0].split(',');
          const rows = lines.slice(1, 4).map(l => l.split(','));
          setCsvPreview({ headers, rows, total: lines.length - 1 });
        }
      };
      reader.readAsText(f);
    } else {
      setCsvPreview(null);
    }
  };"""
content = re.sub(r'const handleFileChange = \(e\) => \{[\s\S]*?\};\n', handle_file_change + '\n', content)

# Update handleUpload
content = content.replace(
    'fetchAnomalies(res.data.batch_id);',
    'fetchAnomalies(res.data.batch_id);\n      setPreviewMode(true);'
)

# Update handleResolve
handle_resolve = """  const handleResolve = async (anomalyId, action, correctedData = {}) => {
    try {
      await api.post(`/groups/${selectedGroup.id}/anomalies/${anomalyId}/resolve/`, {
        action,
        corrected_data: correctedData,
      });
      setResolvedFeedback(anomalyId);
      setTimeout(() => setResolvedFeedback(null), 2000);
      fetchAnomalies(batch.batch_id);
    } catch (err) {
      alert(err.response?.data?.detail || "Resolution failed");
    }
  };"""
content = re.sub(r'const handleResolve = async \(anomalyId, action, correctedData = \{\}\) => \{[\s\S]*?alert.*?failed"\);\n    \}\n  \};', handle_resolve, content)

# Modify render for Upload section
upload_form_orig = """            <form onSubmit={handleUpload} className="upload-form m-0">
              <input type="file" accept=".csv" onChange={handleFileChange} />
              <button type="submit" disabled={uploading || !file}>
                {uploading ? "Importing..." : "Run Import"}
              </button>
              {error && <div className="error-text">{error}</div>}
            </form>"""
upload_form_new = """            <form onSubmit={handleUpload} className="upload-form m-0">
              <input type="file" accept=".csv" onChange={handleFileChange} />
              <button type="submit" disabled={uploading || !file}>
                {uploading ? "Analyzing..." : "Analyze CSV"}
              </button>
              {error && <div className="error-text">{error}</div>}
            </form>"""
content = content.replace(upload_form_orig, upload_form_new)

# Modify render for Batch/Preview section
batch_orig = r'\{batch && \([\s\S]*?\}\)'
batch_new = """{previewMode && batch && (
            <div className="card batch-summary fade-in">
              <h3>File Preview & Import Summary</h3>
              <p className="text-gray mb-4">Target Group: <strong>{selectedGroup?.name}</strong></p>
              
              <div className="summary-stats mb-4">
                <div className="stat-box">
                  <div className="stat-value">{batch.total_rows_processed}</div>
                  <div className="stat-label">Total Rows</div>
                </div>
                <div className="stat-box success">
                  <div className="stat-value">{batch.imported_rows}</div>
                  <div className="stat-label">Cleanly Imported</div>
                </div>
                <div className="stat-box warning">
                  <div className="stat-value">{batch.skipped_rows}</div>
                  <div className="stat-label">Anomalies Flagged</div>
                </div>
              </div>

              {csvPreview && (
                <div className="csv-preview mb-4">
                  <h4>CSV Data Preview (First 3 rows)</h4>
                  <table className="mini-table w-100">
                    <thead>
                      <tr>
                        {csvPreview.headers.map((h, i) => <th key={i}>{h}</th>)}
                      </tr>
                    </thead>
                    <tbody>
                      {csvPreview.rows.map((r, i) => (
                        <tr key={i}>
                          {r.map((cell, j) => <td key={j}>{cell}</td>)}
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              )}

              <div className="actions flex-row" style={{ gap: '1rem', marginTop: '1rem' }}>
                <button className="btn primary" onClick={() => setPreviewMode(false)}>Confirm Import & Review Anomalies</button>
                <button className="btn secondary" onClick={() => { setBatch(null); setFile(null); setPreviewMode(false); setCsvPreview(null); }}>Cancel</button>
              </div>
            </div>
          )}"""
content = re.sub(r'\{batch && \(\s*<div className="card batch-summary">[\s\S]*?</div>\s*\)\}', batch_new, content)

# Modify render for Anomalies section
anomalies_orig = r'\{anomalies.length > 0 && \([\s\S]*?\}\)'
anomalies_new = """{!previewMode && batch && anomalies.length > 0 && (
            <div className="anomalies-section fade-in">
              <div className="flex-row" style={{ justifyContent: 'space-between', alignItems: 'center', marginBottom: '1rem' }}>
                <div>
                  <h3>Anomaly Review</h3>
                  <p className="text-gray text-sm">
                    {anomalies.length} anomalies found — {anomalies.filter(a => a.status === 'blocked').length} action needed, {anomalies.filter(a => a.status !== 'blocked').length} resolved with fallback.
                  </p>
                </div>
                <select value={anomalyFilter} onChange={e => setAnomalyFilter(e.target.value)} style={{ padding: '0.5rem' }}>
                  <option value="all">All Anomalies</option>
                  <option value="action_needed">Action Needed</option>
                  {[...new Set(anomalies.map(a => a.problem_type))].map(type => (
                    <option key={type} value={type}>{type}</option>
                  ))}
                </select>
              </div>
              <table className="anomalies-table">
                <thead>
                  <tr>
                    <th>Row</th>
                    <th>Issue</th>
                    <th>Extracted Data</th>
                    <th>Status</th>
                    <th>Resolution</th>
                  </tr>
                </thead>
                <tbody>
                  {anomalies
                    .filter(a => anomalyFilter === 'all' ? true : anomalyFilter === 'action_needed' ? a.status === 'blocked' : a.problem_type === anomalyFilter)
                    .map(a => (
                    <AnomalyRow 
                      key={a.id} 
                      anomaly={a} 
                      members={selectedGroup?.memberships || []} 
                      onResolve={handleResolve} 
                      isRecentlyResolved={resolvedFeedback === a.id}
                    />
                  ))}
                </tbody>
              </table>
            </div>
          )}"""
content = re.sub(r'\{anomalies.length > 0 && \(\s*<div className="anomalies-section">[\s\S]*?</div>\s*\)\}', anomalies_new, content)

# Update AnomalyRow props and rendering
content = content.replace(
    'function AnomalyRow({ anomaly, members, onResolve }) {',
    'function AnomalyRow({ anomaly, members, onResolve, isRecentlyResolved }) {'
)
content = content.replace(
    '<tr className={`anomaly-row ${anomaly.status}`}>',
    '<tr className={`anomaly-row ${anomaly.status} ${isRecentlyResolved ? "success-flash" : ""}`}>'
)

# Replace raw JSON dump with a mini table
raw_data_orig = """      <td className="raw-data-cell">
        <pre>{JSON.stringify(anomaly.raw_data, null, 2)}</pre>
      </td>"""
raw_data_new = """      <td className="raw-data-cell">
        <table className="mini-table text-sm">
          <tbody>
            {Object.entries(anomaly.raw_data).map(([k, v]) => (
              <tr key={k}>
                <td className="text-gray" style={{ paddingRight: '1rem', fontWeight: 600 }}>{k}</td>
                <td>{v?.toString() || "-"}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </td>"""
content = content.replace(raw_data_orig, raw_data_new)

with open("frontend/src/pages/ImportPage.jsx", "w") as f:
    f.write(content)

# Update ImportPage.css
with open("frontend/src/pages/ImportPage.css", "a") as f:
    f.write("""
.fade-in {
  animation: fadeIn 0.3s ease-in;
}
@keyframes fadeIn {
  from { opacity: 0; transform: translateY(5px); }
  to { opacity: 1; transform: translateY(0); }
}

.stat-box {
  background: var(--bg-surface);
  padding: 1rem;
  border-radius: 8px;
  border: 1px solid var(--border-color);
  text-align: center;
  flex: 1;
}
.stat-box.success {
  border-left: 4px solid #10b981;
}
.stat-box.warning {
  border-left: 4px solid #f59e0b;
}
.stat-value {
  font-size: 1.5rem;
  font-weight: 700;
  margin-bottom: 0.25rem;
}
.stat-label {
  font-size: 0.875rem;
  color: var(--text-muted);
}
.flex-row {
  display: flex;
  flex-direction: row;
}
.w-100 {
  width: 100%;
}
.mini-table {
  border-collapse: collapse;
}
.mini-table td, .mini-table th {
  padding: 0.25rem 0.5rem;
  border-bottom: 1px solid var(--border-color);
}
.mini-table tr:last-child td {
  border-bottom: none;
}
.success-flash {
  animation: successFlash 2s ease-out;
}
@keyframes successFlash {
  0% { background-color: rgba(16, 185, 129, 0.2); }
  100% { background-color: transparent; }
}
""")

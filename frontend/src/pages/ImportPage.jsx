import { useState, useEffect } from "react";
import api from "../api/client";
import "./ImportPage.css";

export default function ImportPage() {
    const [groups, setGroups] = useState([]);
    const [selectedGroup, setSelectedGroup] = useState(null);
    const [file, setFile] = useState(null);
    const [uploading, setUploading] = useState(false);
    const [batch, setBatch] = useState(null);
    const [anomalies, setAnomalies] = useState([]);
    const [error, setError] = useState("");
    const [loading, setLoading] = useState(true);
    const [previewMode, setPreviewMode] = useState(false);
    const [csvPreview, setCsvPreview] = useState(null);
    const [anomalyFilter, setAnomalyFilter] = useState("all");
    const [resolvedFeedback, setResolvedFeedback] = useState(null);

    useEffect(() => {
        fetchGroups();
    }, []);

    const fetchGroups = async () => {
        try {
            const { data } = await api.get('/groups/');
            setGroups(data);
            if (data.length > 0) {
                setSelectedGroup(data[0]);
            }
        } catch (err) {
            setError("Failed to load groups");
        } finally {
            setLoading(false);
        }
    };

    const handleFileChange = (e) => {
    const f = e.target.files[0];
    setFile(f);
    if (f) {
      const reader = new FileReader();
      reader.onload = (evt) => {
        const text = evt.target.result;
        const lines = text.split(/\r?\n/).filter(l => l.trim());
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
  };

  const handleUpload = async (e) => {
    e.preventDefault();
    if (!file) {
      setError("Please select a file.");
      return;
    }
    setError("");
    setUploading(true);

    const formData = new FormData();
    formData.append("file", file);

    try {
      const res = await api.post(`/groups/${selectedGroup.id}/import/`, formData, {
        headers: { "Content-Type": "multipart/form-data" },
      });
      setBatch(res.data);
      fetchAnomalies(res.data.batch_id);
      setPreviewMode(true);
    } catch (err) {
      setError(err.response?.data?.detail || "Import failed");
    } finally {
      setUploading(false);
    }
  };

  const fetchAnomalies = async (batchId) => {
    try {
      const res = await api.get(`/groups/${selectedGroup.id}/import/${batchId}/anomalies/`);
      setAnomalies(res.data);
    } catch (err) {
      console.error("Failed to fetch anomalies", err);
    }
  };

    const handleResolve = async (anomalyId, action, correctedData = {}) => {
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
  };

  if (loading) return <div className="page">Loading...</div>;

  return (
    <div className="page import-page">
      <div className="page-header">
        <h1>Import Report</h1>
        <p className="page-subtitle">Import CSV and resolve blocked entries</p>
      </div>
      
      {groups.length === 0 ? (
        <div className="placeholder-card">
          <p>You must be in a group to import expenses.</p>
        </div>
      ) : (
        <>
          <div className="card">
            <div className="form-group mb-4">
              <label>Select Group</label>
              <select 
                value={selectedGroup?.id || ''} 
                onChange={e => setSelectedGroup(groups.find(g => g.id === parseInt(e.target.value, 10)))}
                style={{ padding: '0.5rem', width: '100%', maxWidth: '300px', display: 'block' }}
              >
                {groups.map(g => (
                  <option key={g.id} value={g.id}>{g.name}</option>
                ))}
              </select>
            </div>

            <form onSubmit={handleUpload} className="upload-form m-0">
              <input type="file" accept=".csv" onChange={handleFileChange} />
              <button type="submit" disabled={uploading || !file}>
                {uploading ? "Analyzing..." : "Analyze CSV"}
              </button>
              {error && <div className="error-text">{error}</div>}
            </form>
          </div>

          {previewMode && batch && (
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
          )}

          {!previewMode && batch && anomalies.length > 0 && (
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
          )}
        </>
      )}
    </div>
  );
}

function AnomalyRow({ anomaly, members, onResolve, isRecentlyResolved }) {
  const [corrected, setCorrected] = useState({});

  const handleApply = () => {
    onResolve(anomaly.id, "apply", corrected);
  };

  const handleDiscard = () => {
    if (window.confirm("Are you sure you want to discard this row?")) {
      onResolve(anomaly.id, "discard");
    }
  };

  const isBlocked = anomaly.status === "blocked";
  const isResolved = anomaly.status === "manually_resolved";

  return (
    <tr className={`anomaly-row ${anomaly.status} ${isRecentlyResolved ? "success-flash" : ""}`}>
      <td>{anomaly.row_number}</td>
      <td className="issue-cell">
        <strong>{anomaly.problem_type}</strong>
        <div className="text-sm text-gray">{anomaly.detection_method}</div>
        <div className="text-sm text-gray">{anomaly.detected_value}</div>
      </td>
      <td className="raw-data-cell">
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
      </td>
      <td>
        <span className={`status-badge ${anomaly.status}`}>
          {anomaly.status.replace("_", " ")}
        </span>
        <div className="text-sm mt-1">{anomaly.action_taken}</div>
      </td>
      <td className="resolution-cell">
        {isBlocked && (
          <div className="resolution-form">
            <ResolutionInputs
              type={anomaly.problem_type}
              members={members}
              value={corrected}
              onChange={(vals) => setCorrected({ ...corrected, ...vals })}
            />
            <div className="actions">
              <button onClick={handleApply} className="btn-primary">
                Apply
              </button>
              <button onClick={handleDiscard} className="btn-secondary">
                Discard
              </button>
            </div>
          </div>
        )}
        {isResolved && (
          <div className="resolved-info text-sm text-gray">Resolved</div>
        )}
      </td>
    </tr>
  );
}

function ResolutionInputs({ type, members, value, onChange }) {
  if (type === "missing_payer" || type === "name_mismatch") {
    return (
      <select
        value={value.paid_by_id || ""}
        onChange={(e) => onChange({ paid_by_id: e.target.value })}
      >
        <option value="">Select Payer...</option>
        {members.map((m) => (
          <option key={m.user_id} value={m.user_id}>
            {m.username}
          </option>
        ))}
      </select>
    );
  }

  if (type === "bad_date") {
    return (
      <input
        type="date"
        value={value.date || ""}
        onChange={(e) => onChange({ date: e.target.value })}
      />
    );
  }

  if (type === "zero_amount" || type === "missing_amount") {
    return (
      <input
        type="number"
        placeholder="Amount"
        value={value.amount || ""}
        onChange={(e) => onChange({ amount: e.target.value })}
      />
    );
  }

  if (type === "settlement_as_expense") {
    return (
      <div className="settlement-inputs flex-column">
        <select
          value={value.from_user_id || ""}
          onChange={(e) => onChange({ from_user_id: e.target.value })}
        >
          <option value="">From...</option>
          {members.map((m) => (
            <option key={m.user_id} value={m.user_id}>
              {m.username}
            </option>
          ))}
        </select>
        <select
          value={value.to_user_id || ""}
          onChange={(e) => onChange({ to_user_id: e.target.value })}
        >
          <option value="">To...</option>
          {members.map((m) => (
            <option key={m.user_id} value={m.user_id}>
              {m.username}
            </option>
          ))}
        </select>
        <input
          type="number"
          placeholder="Amount"
          value={value.amount || ""}
          onChange={(e) => onChange({ amount: e.target.value })}
        />
        <input
          type="date"
          value={value.date || ""}
          onChange={(e) => onChange({ date: e.target.value })}
        />
      </div>
    );
  }

  return <div className="text-sm">Provide missing info or discard.</div>;
}

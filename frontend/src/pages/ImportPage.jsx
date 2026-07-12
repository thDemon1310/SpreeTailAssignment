import React, { useState, useEffect } from 'react';
import { useParams } from 'react-router-dom';
import api from '../api';
import './ImportPage.css';

export default function ImportPage() {
    const { id } = useParams();
    const [file, setFile] = useState(null);
    const [uploading, setUploading] = useState(false);
    const [batch, setBatch] = useState(null);
    const [anomalies, setAnomalies] = useState([]);
    const [members, setMembers] = useState([]);
    const [error, setError] = useState('');

    useEffect(() => {
        api.get(`/groups/${id}/`)
            .then(res => setMembers(res.data.memberships))
            .catch(err => console.error("Failed to load members", err));
    }, [id]);

    const handleFileChange = (e) => {
        setFile(e.target.files[0]);
    };

    const handleUpload = async (e) => {
        e.preventDefault();
        if (!file) {
            setError('Please select a file.');
            return;
        }
        setError('');
        setUploading(true);

        const formData = new FormData();
        formData.append('file', file);

        try {
            const res = await api.post(`/groups/${id}/import/`, formData, {
                headers: { 'Content-Type': 'multipart/form-data' }
            });
            setBatch(res.data);
            fetchAnomalies(res.data.batch_id);
        } catch (err) {
            setError(err.response?.data?.detail || 'Import failed');
        } finally {
            setUploading(false);
        }
    };

    const fetchAnomalies = async (batchId) => {
        try {
            const res = await api.get(`/groups/${id}/import/${batchId}/anomalies/`);
            setAnomalies(res.data);
        } catch (err) {
            console.error("Failed to fetch anomalies", err);
        }
    };

    const handleResolve = async (anomalyId, action, correctedData = {}) => {
        try {
            await api.post(`/groups/${id}/anomalies/${anomalyId}/resolve/`, {
                action,
                corrected_data: correctedData
            });
            fetchAnomalies(batch.batch_id);
        } catch (err) {
            alert(err.response?.data?.detail || 'Resolution failed');
        }
    };

    return (
        <div className="page import-page">
            <div className="page-header">
                <h1>Import Report</h1>
                <p className="page-subtitle">Import CSV and resolve blocked entries</p>
            </div>
            
            <form onSubmit={handleUpload} className="card upload-form">
                <input 
                    type="file" 
                    accept=".csv" 
                    onChange={handleFileChange} 
                />
                <button type="submit" disabled={uploading || !file}>
                    {uploading ? 'Importing...' : 'Run Import'}
                </button>
                {error && <div className="error-text">{error}</div>}
            </form>

            {batch && (
                <div className="card batch-summary">
                    <h3>Import Summary</h3>
                    <div className="summary-stats">
                        <div><strong>{batch.total_rows_processed}</strong> Processed</div>
                        <div><strong>{batch.imported_rows}</strong> Imported</div>
                        <div><strong>{batch.skipped_rows}</strong> Skipped</div>
                    </div>
                </div>
            )}

            {anomalies.length > 0 && (
                <div className="anomalies-section">
                    <h3>Anomalies</h3>
                    <table className="anomalies-table">
                        <thead>
                            <tr>
                                <th>Row</th>
                                <th>Issue</th>
                                <th>Raw Data</th>
                                <th>Status</th>
                                <th>Resolution</th>
                            </tr>
                        </thead>
                        <tbody>
                            {anomalies.map(a => (
                                <AnomalyRow 
                                    key={a.id} 
                                    anomaly={a} 
                                    members={members} 
                                    onResolve={handleResolve} 
                                />
                            ))}
                        </tbody>
                    </table>
                </div>
            )}
        </div>
    );
}

function AnomalyRow({ anomaly, members, onResolve }) {
    const [corrected, setCorrected] = useState({});

    const handleApply = () => {
        onResolve(anomaly.id, 'apply', corrected);
    };

    const handleDiscard = () => {
        if (window.confirm("Are you sure you want to discard this row?")) {
            onResolve(anomaly.id, 'discard');
        }
    };

    const isBlocked = anomaly.status === 'blocked';
    const isResolved = anomaly.status === 'manually_resolved';

    return (
        <tr className={`anomaly-row ${anomaly.status}`}>
            <td>{anomaly.row_number}</td>
            <td className="issue-cell">
                <strong>{anomaly.problem_type}</strong>
                <div className="text-sm text-gray">{anomaly.detection_method}</div>
                <div className="text-sm text-gray">{anomaly.detected_value}</div>
            </td>
            <td className="raw-data-cell">
                <pre>{JSON.stringify(anomaly.raw_data, null, 2)}</pre>
            </td>
            <td>
                <span className={`status-badge ${anomaly.status}`}>
                    {anomaly.status.replace('_', ' ')}
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
                            onChange={(vals) => setCorrected({...corrected, ...vals})}
                        />
                        <div className="actions">
                            <button onClick={handleApply} className="btn-primary">Apply</button>
                            <button onClick={handleDiscard} className="btn-secondary">Discard</button>
                        </div>
                    </div>
                )}
                {isResolved && (
                    <div className="resolved-info text-sm text-gray">
                        Resolved
                    </div>
                )}
            </td>
        </tr>
    );
}

function ResolutionInputs({ type, members, value, onChange }) {
    if (type === 'missing_payer') {
        return (
            <select 
                value={value.paid_by_id || ''} 
                onChange={e => onChange({paid_by_id: e.target.value})}
            >
                <option value="">Select Payer...</option>
                {members.map(m => (
                    <option key={m.user.id} value={m.user.id}>{m.user.username}</option>
                ))}
            </select>
        );
    }
    
    if (type === 'bad_date') {
        return (
            <input 
                type="date" 
                value={value.date || ''} 
                onChange={e => onChange({date: e.target.value})} 
            />
        );
    }

    if (type === 'zero_amount' || type === 'missing_amount') {
        return (
            <input 
                type="number" 
                placeholder="Amount" 
                value={value.amount || ''} 
                onChange={e => onChange({amount: e.target.value})} 
            />
        );
    }

    if (type === 'settlement_as_expense') {
        return (
            <div className="settlement-inputs flex-column">
                <select 
                    value={value.from_user_id || ''} 
                    onChange={e => onChange({from_user_id: e.target.value})}
                >
                    <option value="">From...</option>
                    {members.map(m => (
                        <option key={m.user.id} value={m.user.id}>{m.user.username}</option>
                    ))}
                </select>
                <select 
                    value={value.to_user_id || ''} 
                    onChange={e => onChange({to_user_id: e.target.value})}
                >
                    <option value="">To...</option>
                    {members.map(m => (
                        <option key={m.user.id} value={m.user.id}>{m.user.username}</option>
                    ))}
                </select>
                <input 
                    type="number" 
                    placeholder="Amount" 
                    value={value.amount || ''} 
                    onChange={e => onChange({amount: e.target.value})} 
                />
                <input 
                    type="date" 
                    value={value.date || ''} 
                    onChange={e => onChange({date: e.target.value})} 
                />
            </div>
        );
    }

    return <div className="text-sm">Provide missing info or discard.</div>;
}

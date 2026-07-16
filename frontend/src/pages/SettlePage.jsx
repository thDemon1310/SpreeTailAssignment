import { useState, useEffect } from 'react';
import { useAuth } from '../context/AuthContext';
import api from '../api/client';
import './SettlePage.css';

export default function SettlePage() {
  const { refreshTrigger, triggerRefresh } = useAuth();
  const [groups, setGroups] = useState([]);
  const [selectedGroup, setSelectedGroup] = useState(null);
  const [loading, setLoading] = useState(true);
  
  const [fromUserId, setFromUserId] = useState('');
  const [toUserId, setToUserId] = useState('');
  const [amount, setAmount] = useState('');
  const [date, setDate] = useState(new Date().toISOString().split('T')[0]);
  
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState('');
  const [success, setSuccess] = useState('');

  useEffect(() => {
    fetchGroups(selectedGroup?.id);
  }, [refreshTrigger]);

  const fetchGroups = async (keepSelectedGroupId = null) => {
    try {
      const { data } = await api.get('/groups/');
      setGroups(data);
      if (data.length > 0) {
        const found = keepSelectedGroupId ? data.find(g => g.id === keepSelectedGroupId) : null;
        const groupToSelect = found || data[0];
        selectGroup(groupToSelect);
      }
    } catch (err) {
      setError('Failed to load groups');
    } finally {
      setLoading(false);
    }
  };

  const selectGroup = (group) => {
    setSelectedGroup(group);
    if (group.memberships.length >= 2) {
      setFromUserId(group.memberships[0].user_id.toString());
      setToUserId(group.memberships[1].user_id.toString());
    } else if (group.memberships.length === 1) {
      setFromUserId(group.memberships[0].user_id.toString());
    }
  };

  const handleSubmit = async (e) => {
    e.preventDefault();
    setError('');
    setSuccess('');
    
    if (fromUserId === toUserId) {
      setError('Cannot settle with yourself.');
      return;
    }

    setSubmitting(true);
    try {
      await api.post(`/groups/${selectedGroup.id}/settlements/`, {
        from_user_id: parseInt(fromUserId, 10),
        to_user_id: parseInt(toUserId, 10),
        amount,
        date
      });
      setSuccess('Settlement recorded successfully!');
      setAmount('');
      triggerRefresh();
    } catch (err) {
      setError(err.response?.data?.detail || 'Failed to record settlement.');
    } finally {
      setSubmitting(false);
    }
  };

  if (loading) return <div className="page"><p>Loading...</p></div>;

  return (
    <div className="page settle-page">
      <div className="page-header">
        <h1>Settle Up</h1>
        <p className="page-subtitle">Record payments between members to clear debts</p>
      </div>

      {groups.length === 0 ? (
        <div className="placeholder-card">
          <p>You must be in a group to settle up.</p>
        </div>
      ) : (
        <div className="settle-form-container">
          <div className="form-card">
            {error && <div className="error-banner">{error}</div>}
            {success && <div className="success-banner">{success}</div>}

            <form onSubmit={handleSubmit} className="settle-form">
              <div className="form-group">
                <label>Group</label>
                <select 
                  value={selectedGroup?.id || ''} 
                  onChange={e => selectGroup(groups.find(g => g.id === parseInt(e.target.value, 10)))}
                >
                  {groups.map(g => (
                    <option key={g.id} value={g.id}>{g.name}</option>
                  ))}
                </select>
              </div>

              <div className="form-row">
                <div className="form-group">
                  <label>Who Paid?</label>
                  <select value={fromUserId} onChange={e => setFromUserId(e.target.value)} required>
                    {selectedGroup?.memberships.map(m => (
                      <option key={m.user_id} value={m.user_id}>{m.username}</option>
                    ))}
                  </select>
                </div>
                
                <div className="arrow-icon">➔</div>
                
                <div className="form-group">
                  <label>Who Received?</label>
                  <select value={toUserId} onChange={e => setToUserId(e.target.value)} required>
                    {selectedGroup?.memberships.map(m => (
                      <option key={m.user_id} value={m.user_id}>{m.username}</option>
                    ))}
                  </select>
                </div>
              </div>

              <div className="form-row">
                <div className="form-group">
                  <label>Amount (INR)</label>
                  <input type="number" step="0.01" min="0.01" value={amount} onChange={e => setAmount(e.target.value)} required placeholder="0.00" />
                </div>
                
                <div className="form-group">
                  <label>Date</label>
                  <input type="date" value={date} onChange={e => setDate(e.target.value)} required />
                </div>
              </div>

              <div className="form-actions">
                <button type="submit" className="submit-btn" disabled={submitting}>
                  {submitting ? 'Recording...' : 'Record Settlement'}
                </button>
              </div>
            </form>
          </div>
        </div>
      )}
    </div>
  );
}

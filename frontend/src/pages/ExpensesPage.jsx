import { useState, useEffect } from 'react';
import { useAuth } from '../context/AuthContext';
import api from '../api/client';
import './ExpensesPage.css';

export default function ExpensesPage() {
  const { refreshTrigger, triggerRefresh } = useAuth();
  const [groups, setGroups] = useState([]);
  const [selectedGroup, setSelectedGroup] = useState(null);
  
  const [description, setDescription] = useState('');
  const [amount, setAmount] = useState('');
  const [currency, setCurrency] = useState('INR');
  const [date, setDate] = useState(new Date().toISOString().split('T')[0]);
  const [paidById, setPaidById] = useState('');
  const [splitType, setSplitType] = useState('equal');
  const [participantIds, setParticipantIds] = useState([]);
  const [splitDetails, setSplitDetails] = useState({});
  const [notes, setNotes] = useState('');
  
  const [loading, setLoading] = useState(true);
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
    const activeMembers = group.memberships.filter(m => !m.left_on);
    if (activeMembers.length > 0) {
      setPaidById(activeMembers[0].user_id.toString());
      setParticipantIds(activeMembers.map(m => m.user_id));
      
      const details = {};
      activeMembers.forEach(m => {
        details[m.user_id] = '';
      });
      setSplitDetails(details);
    }
  };

  const handleParticipantToggle = (userId) => {
    setParticipantIds(prev => {
      if (prev.includes(userId)) {
        return prev.filter(id => id !== userId);
      } else {
        return [...prev, userId];
      }
    });
  };

  const handleDetailChange = (userId, value) => {
    setSplitDetails(prev => ({
      ...prev,
      [userId]: value
    }));
  };

  const handleSubmit = async (e) => {
    e.preventDefault();
    setError('');
    setSuccess('');
    
    if (participantIds.length === 0) {
      setError('Select at least one participant');
      return;
    }

    // Clean up split_details
    const cleanedDetails = {};
    if (splitType !== 'equal') {
      for (const id of participantIds) {
        if (!splitDetails[id]) {
          setError(`Please provide a value for participant ID ${id}`);
          return;
        }
        cleanedDetails[id] = splitDetails[id];
      }
    }

    setSubmitting(true);
    try {
      await api.post(`/groups/${selectedGroup.id}/expenses/`, {
        description,
        amount,
        currency,
        date,
        paid_by_id: parseInt(paidById, 10),
        split_type: splitType,
        participant_ids: participantIds,
        split_details: cleanedDetails,
        notes
      });
      setSuccess('Expense added successfully!');
      // Reset form (keep group and date)
      setDescription('');
      setAmount('');
      setNotes('');
      // Reset details
      const details = {};
      selectedGroup.memberships.forEach(m => { details[m.user_id] = ''; });
      setSplitDetails(details);
      triggerRefresh();
    } catch (err) {
      const detail = err.response?.data;
      if (typeof detail === 'object') {
        const msg = Object.entries(detail).map(([k, v]) => `${k}: ${v}`).join('; ');
        setError(msg);
      } else {
        setError('Failed to add expense');
      }
    } finally {
      setSubmitting(false);
    }
  };

  if (loading) return <div className="page"><p>Loading...</p></div>;

  return (
    <div className="page expenses-page">
      <div className="page-header">
        <h1>Add Expense</h1>
        <p className="page-subtitle">Log a new shared expense</p>
      </div>

      {groups.length === 0 ? (
        <div className="placeholder-card">
          <p>You must be in a group to add expenses.</p>
        </div>
      ) : (
        <div className="expense-form-container">
          <div className="form-card">
            {error && <div className="error-banner">{error}</div>}
            {success && <div className="success-banner">{success}</div>}

            <form onSubmit={handleSubmit} className="expense-form">
              <div className="form-row">
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
                <div className="form-group">
                  <label>Date</label>
                  <input type="date" value={date} onChange={e => setDate(e.target.value)} required />
                </div>
              </div>

              <div className="form-group">
                <label>Description</label>
                <input type="text" value={description} onChange={e => setDescription(e.target.value)} required placeholder="What was this for?" />
              </div>

              <div className="form-row">
                <div className="form-group">
                  <label>Amount</label>
                  <input type="number" step="0.01" min="0.01" value={amount} onChange={e => setAmount(e.target.value)} required placeholder="0.00" />
                </div>
                <div className="form-group">
                  <label>Currency</label>
                  <input type="text" value={currency} onChange={e => setCurrency(e.target.value)} required maxLength={3} />
                </div>
                <div className="form-group">
                  <label>Paid By</label>
                  <select value={paidById} onChange={e => setPaidById(e.target.value)} required>
                    {selectedGroup?.memberships.filter(m => !m.left_on).map(m => (
                      <option key={m.user_id} value={m.user_id}>{m.username}</option>
                    ))}
                  </select>
                </div>
              </div>

              <div className="form-group">
                <label>Split Type</label>
                <div className="split-type-options">
                  {['equal', 'unequal', 'percentage', 'shares'].map(type => (
                    <label key={type} className="radio-label">
                      <input 
                        type="radio" 
                        name="splitType" 
                        value={type} 
                        checked={splitType === type} 
                        onChange={() => setSplitType(type)} 
                      />
                      <span>{type.charAt(0).toUpperCase() + type.slice(1)}</span>
                    </label>
                  ))}
                </div>
              </div>

              <div className="participants-section">
                <label>Split With</label>
                <div className="participants-list">
                  {selectedGroup?.memberships.filter(m => !m.left_on).map(m => (
                    <div key={m.user_id} className="participant-row">
                      <label className="checkbox-label">
                        <input 
                          type="checkbox" 
                          checked={participantIds.includes(m.user_id)} 
                          onChange={() => handleParticipantToggle(m.user_id)}
                        />
                        <span>{m.username}</span>
                      </label>
                      
                      {splitType !== 'equal' && participantIds.includes(m.user_id) && (
                        <div className="split-detail-input">
                          <input 
                            type="number" 
                            step="0.01" 
                            min="0"
                            placeholder={splitType === 'percentage' ? '%' : splitType === 'shares' ? 'Shares' : 'Amount'} 
                            value={splitDetails[m.user_id] || ''} 
                            onChange={e => handleDetailChange(m.user_id, e.target.value)} 
                            required 
                          />
                        </div>
                      )}
                    </div>
                  ))}
                </div>
              </div>

              <div className="form-group">
                <label>Notes (Optional)</label>
                <input type="text" value={notes} onChange={e => setNotes(e.target.value)} placeholder="Additional context" />
              </div>

              <div className="form-actions">
                <button type="submit" className="submit-btn" disabled={submitting}>
                  {submitting ? 'Adding...' : 'Add Expense'}
                </button>
              </div>
            </form>
          </div>
        </div>
      )}
    </div>
  );
}

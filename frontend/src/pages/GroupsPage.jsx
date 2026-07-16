import { useState, useEffect } from 'react';
import { useAuth } from '../context/AuthContext';
import api from '../api/client';
import './GroupsPage.css';

export default function GroupsPage() {
  const { refreshTrigger, triggerRefresh } = useAuth();
  const [groups, setGroups] = useState([]);
  const [selectedGroup, setSelectedGroup] = useState(null);
  const [expenses, setExpenses] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [showCreateForm, setShowCreateForm] = useState(false);
  const [newGroupName, setNewGroupName] = useState('');
  const [newGroupDesc, setNewGroupDesc] = useState('');
  const [createLoading, setCreateLoading] = useState(false);
  const [showAddMemberForm, setShowAddMemberForm] = useState(false);
  const [addUsername, setAddUsername] = useState('');
  const [addJoinedOn, setAddJoinedOn] = useState(new Date().toISOString().split('T')[0]);
  const [addMemberError, setAddMemberError] = useState('');
  const [addMemberLoading, setAddMemberLoading] = useState(false);

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
        selectGroup(groupToSelect, false);
      } else {
        setLoading(false);
      }
    } catch (err) {
      setError('Failed to load groups');
      setLoading(false);
    }
  };

  const selectGroup = async (group, isManual = false) => {
    setSelectedGroup(group);
    setLoading(true);
    if (isManual) {
      setShowAddMemberForm(false);
      setAddUsername('');
      setAddJoinedOn(new Date().toISOString().split('T')[0]);
      setAddMemberError('');
    }
    try {
      const { data } = await api.get(`/groups/${group.id}/expenses/`);
      setExpenses(data);
    } catch (err) {
      setError('Failed to load expenses');
    } finally {
      setLoading(false);
    }
  };

  const handleAddMember = async (e) => {
    e.preventDefault();
    if (!addUsername.trim()) {
      setAddMemberError('Username is required.');
      return;
    }
    setAddMemberLoading(true);
    setAddMemberError('');
    try {
      await api.post(`/groups/${selectedGroup.id}/members/`, {
        username: addUsername.trim(),
        joined_on: addJoinedOn,
      });
      // Fetch updated group detail to refresh members list
      const { data } = await api.get(`/groups/${selectedGroup.id}/`);
      setSelectedGroup(data);
      // Update this group in the groups list
      setGroups(groups.map(g => g.id === data.id ? data : g));
      setAddUsername('');
      setAddJoinedOn(new Date().toISOString().split('T')[0]);
      setShowAddMemberForm(false);
      triggerRefresh();
    } catch (err) {
      const data = err.response?.data;
      let errMsg = 'Failed to add member';
      if (data) {
        if (typeof data === 'object') {
          if (data.detail) {
            errMsg = data.detail;
          } else {
            const fieldErrors = Object.entries(data).map(([key, val]) => {
              const displayVal = Array.isArray(val) ? val[0] : val;
              return `${key}: ${displayVal}`;
            });
            if (fieldErrors.length > 0) {
              errMsg = fieldErrors.join(', ');
            }
          }
        } else if (typeof data === 'string') {
          errMsg = data;
        }
      }
      setAddMemberError(errMsg);
    } finally {
      setAddMemberLoading(false);
    }
  };

  if (loading && !selectedGroup) return <div className="page"><p>Loading...</p></div>;
  if (error) return <div className="page"><p className="error">{error}</p></div>;

  const handleCreateGroup = async (e) => {
    e.preventDefault();
    setCreateLoading(true);
    try {
      await api.post('/groups/', { name: newGroupName, description: newGroupDesc });
      setNewGroupName('');
      setNewGroupDesc('');
      setShowCreateForm(false);
      triggerRefresh();
    } catch (err) {
      setError('Failed to create group');
    } finally {
      setCreateLoading(false);
    }
  };

  return (
    <div className="page groups-page">
      <div className="page-header">
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
          <div>
            <h1>Groups</h1>
            <p className="page-subtitle">Manage your shared expense groups</p>
          </div>
          <button className="btn primary" onClick={() => setShowCreateForm(!showCreateForm)}>
            {showCreateForm ? 'Cancel' : 'Create New Group'}
          </button>
        </div>
      </div>
      
      {showCreateForm && (
        <div className="card mb-4">
          <h3>Create a Group</h3>
          <form onSubmit={handleCreateGroup}>
            <div className="form-group mb-4">
              <label>Name</label>
              <input type="text" value={newGroupName} onChange={e => setNewGroupName(e.target.value)} required />
            </div>
            <div className="form-group mb-4">
              <label>Description</label>
              <input type="text" value={newGroupDesc} onChange={e => setNewGroupDesc(e.target.value)} />
            </div>
            <button type="submit" className="btn primary" disabled={createLoading}>
              {createLoading ? 'Creating...' : 'Create Group'}
            </button>
          </form>
        </div>
      )}
      
      {groups.length === 0 ? (
        <div className="placeholder-card">
          <p>You are not part of any groups yet.</p>
        </div>
      ) : (
        <div className="groups-container">
          <div className="group-sidebar">
            <h3>Your Groups</h3>
            <ul className="group-list">
              {groups.map(g => (
                <li 
                  key={g.id} 
                  className={selectedGroup?.id === g.id ? 'active' : ''}
                  onClick={() => selectGroup(g, true)}
                >
                  {g.name}
                </li>
              ))}
            </ul>
          </div>
          
          {selectedGroup && (
            <div className="group-content">
              <div className="group-card">
                <h2>{selectedGroup.name}</h2>
                <p className="group-desc">{selectedGroup.description}</p>
                <div className="members-section">
                  <div className="section-header-row">
                    <h3>Members</h3>
                    <button className="btn secondary" onClick={() => setShowAddMemberForm(!showAddMemberForm)}>
                      {showAddMemberForm ? 'Cancel' : 'Add Member'}
                    </button>
                  </div>

                  {showAddMemberForm && (
                    <div className="add-member-form-card">
                      <h4>Add Member to Group</h4>
                      <form onSubmit={handleAddMember} className="add-member-form">
                        <div className="form-group">
                          <label>Username or Email</label>
                          <input 
                            type="text" 
                            value={addUsername} 
                            onChange={e => setAddUsername(e.target.value)} 
                            required 
                            placeholder="e.g. rohan"
                          />
                        </div>
                        <div className="form-group">
                          <label>Joined On</label>
                          <input 
                            type="date" 
                            value={addJoinedOn} 
                            onChange={e => setAddJoinedOn(e.target.value)} 
                            required 
                          />
                        </div>
                        <button type="submit" className="add-member-btn" disabled={addMemberLoading}>
                          {addMemberLoading ? 'Adding...' : 'Add Member'}
                        </button>
                      </form>
                      {addMemberError && <div className="add-member-error">{addMemberError}</div>}
                    </div>
                  )}

                  <table className="members-table">
                    <thead>
                      <tr>
                        <th>Name</th>
                        <th>Joined On</th>
                        <th>Left On</th>
                      </tr>
                    </thead>
                    <tbody>
                      {selectedGroup.memberships?.map(m => (
                        <tr key={m.id} className={m.left_on ? 'inactive-member' : ''}>
                          <td>{m.username}</td>
                          <td>{m.joined_on}</td>
                          <td>{m.left_on || 'Active'}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              </div>

              <div className="expenses-section">
                <div className="expenses-header">
                  <h3>Expenses</h3>
                </div>
                {loading ? <p>Loading expenses...</p> : (
                  expenses.length === 0 ? <p>No expenses logged yet.</p> : (
                    <table className="expenses-table">
                      <thead>
                        <tr>
                          <th>Date</th>
                          <th>Description</th>
                          <th>Paid By</th>
                          <th>Amount</th>
                          <th>Split Type</th>
                        </tr>
                      </thead>
                      <tbody>
                        {expenses.map(exp => (
                          <tr key={exp.id}>
                            <td>{exp.date}</td>
                            <td>{exp.description}</td>
                            <td>{exp.paid_by_username}</td>
                            <td>{exp.currency} {exp.amount}</td>
                            <td>{exp.split_type}</td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  )
                )}
              </div>
            </div>
          )}
        </div>
      )}
    </div>
  );
}

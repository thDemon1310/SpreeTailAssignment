import { useState, useEffect } from 'react';
import api from '../api/client';
import './GroupsPage.css';

export default function GroupsPage() {
  const [groups, setGroups] = useState([]);
  const [selectedGroup, setSelectedGroup] = useState(null);
  const [expenses, setExpenses] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');

  useEffect(() => {
    fetchGroups();
  }, []);

  const fetchGroups = async () => {
    try {
      const { data } = await api.get('/groups/');
      setGroups(data);
      if (data.length > 0) {
        selectGroup(data[0]);
      } else {
        setLoading(false);
      }
    } catch (err) {
      setError('Failed to load groups');
      setLoading(false);
    }
  };

  const selectGroup = async (group) => {
    setSelectedGroup(group);
    setLoading(true);
    try {
      const { data } = await api.get(`/groups/${group.id}/expenses/`);
      setExpenses(data);
    } catch (err) {
      setError('Failed to load expenses');
    } finally {
      setLoading(false);
    }
  };

  if (loading && !selectedGroup) return <div className="page"><p>Loading...</p></div>;
  if (error) return <div className="page"><p className="error">{error}</p></div>;

  return (
    <div className="page groups-page">
      <div className="page-header">
        <h1>Groups</h1>
        <p className="page-subtitle">Manage your shared expense groups</p>
      </div>
      
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
                  onClick={() => selectGroup(g)}
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
                  <h3>Members</h3>
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

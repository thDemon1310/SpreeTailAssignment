import { useState, useEffect } from 'react';
import api from '../api/client';
import './BalancesPage.css';

export default function BalancesPage() {
  const [groups, setGroups] = useState([]);
  const [selectedGroup, setSelectedGroup] = useState(null);
  const [balances, setBalances] = useState({});
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');

  // Drill-down state
  const [detailUser, setDetailUser] = useState(null);
  const [detailData, setDetailData] = useState(null);
  const [detailLoading, setDetailLoading] = useState(false);

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
    setDetailUser(null);
    setLoading(true);
    try {
      const { data } = await api.get(`/groups/${group.id}/balances/`);
      setBalances(data);
    } catch (err) {
      setError('Failed to load balances');
    } finally {
      setLoading(false);
    }
  };

  const loadDrillDown = async (userId) => {
    // Find member details for display name
    const member = selectedGroup.memberships.find(m => m.user_id.toString() === userId.toString());
    setDetailUser(member || { user_id: userId, username: `User ${userId}` });
    setDetailLoading(true);
    
    try {
      const { data } = await api.get(`/groups/${selectedGroup.id}/balances/${userId}/`);
      setDetailData(data);
    } catch (err) {
      console.error('Failed to load drill down', err);
    } finally {
      setDetailLoading(false);
    }
  };

  if (loading && !selectedGroup) return <div className="page"><p>Loading...</p></div>;

  return (
    <div className="page balances-page">
      <div className="page-header">
        <h1>Balances</h1>
        <p className="page-subtitle">See who owes whom</p>
      </div>

      {error && <div className="error-banner">{error}</div>}

      {groups.length === 0 ? (
        <div className="placeholder-card">
          <p>You must be in a group to see balances.</p>
        </div>
      ) : (
        <div className="balances-layout">
          <div className="balances-sidebar">
            <div className="form-group group-selector">
              <label>Select Group</label>
              <select 
                value={selectedGroup?.id || ''} 
                onChange={e => selectGroup(groups.find(g => g.id === parseInt(e.target.value, 10)))}
              >
                {groups.map(g => (
                  <option key={g.id} value={g.id}>{g.name}</option>
                ))}
              </select>
            </div>

            <div className="balances-summary">
              <h3>Summary</h3>
              {loading ? <p>Loading balances...</p> : (
                <ul className="balance-list">
                  {Object.entries(balances).map(([userId, bal]) => {
                    const member = selectedGroup?.memberships.find(m => m.user_id.toString() === userId);
                    const name = member ? member.username : `User ${userId}`;
                    const balNum = parseFloat(bal);
                    const balClass = balNum > 0 ? 'positive' : (balNum < 0 ? 'negative' : 'neutral');
                    
                    return (
                      <li 
                        key={userId} 
                        className={`balance-item ${detailUser?.user_id.toString() === userId ? 'active' : ''}`}
                        onClick={() => loadDrillDown(userId)}
                      >
                        <span className="balance-name">{name}</span>
                        <span className={`balance-amount ${balClass}`}>
                          {balNum > 0 ? '+' : ''}{balNum.toFixed(2)}
                        </span>
                      </li>
                    );
                  })}
                </ul>
              )}
            </div>
          </div>

          <div className="balances-content">
            {!detailUser ? (
              <div className="placeholder-card drill-down-placeholder">
                <p>Click a user to see the exact rows calculating their balance.</p>
              </div>
            ) : detailLoading ? (
              <div className="placeholder-card"><p>Loading details...</p></div>
            ) : detailData && (
              <div className="drill-down-card">
                <h2>{detailUser.username}'s Balance: <span className={parseFloat(detailData.balance) >= 0 ? 'positive' : 'negative'}>{parseFloat(detailData.balance).toFixed(2)}</span></h2>
                <div className="formula-bar">
                  <code>Balance = Total Paid ({detailData.total_paid}) - Total Owed ({detailData.total_owed}) + Settlements Made ({detailData.settlements_made}) - Settlements Received ({detailData.settlements_received})</code>
                </div>

                <div className="drill-sections">
                  <div className="drill-section">
                    <h4>Total Paid: +{detailData.total_paid}</h4>
                    <table className="drill-table">
                      <thead><tr><th>Date</th><th>Expense</th><th>Amount</th></tr></thead>
                      <tbody>
                        {detailData.paid_expenses.map(e => (
                          <tr key={e.id}><td>{e.date}</td><td>{e.description}</td><td>{e.amount}</td></tr>
                        ))}
                      </tbody>
                    </table>
                  </div>

                  <div className="drill-section">
                    <h4>Total Owed: -{detailData.total_owed}</h4>
                    <table className="drill-table">
                      <thead><tr><th>Date</th><th>Expense</th><th>Share</th></tr></thead>
                      <tbody>
                        {detailData.owed_splits.map(s => (
                          <tr key={s.id}><td>{s.expense.date}</td><td>{s.expense.description}</td><td>{s.share_amount}</td></tr>
                        ))}
                      </tbody>
                    </table>
                  </div>

                  <div className="drill-section">
                    <h4>Settlements Made (Paid Debt): +{detailData.settlements_made}</h4>
                    <table className="drill-table">
                      <thead><tr><th>Date</th><th>To User ID</th><th>Amount</th></tr></thead>
                      <tbody>
                        {detailData.settlements_made_list.map(s => (
                          <tr key={s.id}><td>{s.date}</td><td>{s.to_user_id}</td><td>{s.amount}</td></tr>
                        ))}
                      </tbody>
                    </table>
                  </div>

                  <div className="drill-section">
                    <h4>Settlements Received (Debt Paid Back): -{detailData.settlements_received}</h4>
                    <table className="drill-table">
                      <thead><tr><th>Date</th><th>From User ID</th><th>Amount</th></tr></thead>
                      <tbody>
                        {detailData.settlements_received_list.map(s => (
                          <tr key={s.id}><td>{s.date}</td><td>{s.from_user_id}</td><td>{s.amount}</td></tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                </div>
              </div>
            )}
          </div>
        </div>
      )}
    </div>
  );
}

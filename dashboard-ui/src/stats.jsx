import { useState, useEffect } from 'react';
import './stats.css';

function Stats() {
    const [data, setData] = useState([]);
    const [loading, setLoading] = useState(true);
    const [error, setError] = useState(null);

    useEffect(() => {
        // Define the async function inside the effect
        const fetchData = async () => {
            try {
                const response = await fetch('http://127.0.0.1:8000/stats');
                if (!response.ok) {
                    throw new Error(`HTTP error! status: ${response.status}`);
                }
                const json = await response.json();
                setData(json);
            } catch (err) {
                setError(err.message);
            } finally {
                setLoading(false);
            }
        };

        fetchData();
    }, []); // Empty dependency array ensures this runs exactly once on mount

    if (loading) return <p>Loading...</p>;
    if (error) return <p>Error: {error}</p>;

    return (
        <div>
            <p>Requests/sec: {data.requests_per_sec}</p>
            <p>p95 TTFT: {data.p95_ttft_ms ?? '—'} ms</p>
            <p>In flight: {data.in_flight}</p>
            <p>Waiting: {data.waiting}</p>
            <p>Errors (last min): {data.errors_last_minute}</p>
            <table className="recent-table">
                <thead>
                    <tr>
                        <th>ID</th>
                        <th>Received</th>
                        <th>Status</th>
                        <th>TTFT (ms)</th>
                        <th>Total (ms)</th>
                    </tr>
                </thead>
                <tbody>
                    {data.recent.map(r => (
                        <tr key={r.id}>
                            <td>{r.id}</td>
                            <td>{new Date(r.started_at).toLocaleString()}</td>
                            <td>{r.status}</td>
                            <td className="num">{r.ttft_ms ?? '—'}</td>
                            <td className="num">{r.total_ms}</td>
                        </tr>
                    ))}
                </tbody>
            </table>
        </div>
    );
}

export default Stats;

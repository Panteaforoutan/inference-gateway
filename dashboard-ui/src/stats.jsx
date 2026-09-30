import { useState, useEffect } from 'react';

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
            <p>Errors (last min): {data.errors_last_minute}</p>
            <ul>
                {data.recent.map(r => (
                    <li key={r.id}>{r.model} · {r.status} · {r.total_ms} ms</li>
                ))}
            </ul>
        </div>
    );
}

export default Stats;

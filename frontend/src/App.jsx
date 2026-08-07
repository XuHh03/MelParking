import { useState } from 'react'
import SearchBar from './components/SearchBar'
import Map from './components/Map'
import ZoneList from './components/ZoneList'

export default function App() {
    const [results, setResults] = useState(null)
    const [loading, setLoading] = useState(false)
    const [error, setError] = useState(null)
    const [selected, setSelected] = useState(null)

    async function handleSearch(address) {
        setLoading(true)
        setError(null)
        setResults(null)
        setSelected(null)

        try {
            const res = await fetch('/api/recommend', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ address, top_n: 10 }),
            })

            if (!res.ok) {
                const err = await res.json()
                throw new Error(err.detail ?? `Server error ${res.status}`)
            }

            const data = await res.json()
            setResults(data)
            setSelected(0)
        } catch (e) {
            setError(e.message)
        } finally {
            setLoading(false)
        }
    }

    return (
        <div className="flex flex-col h-full bg-gray-50">
            <header className="flex items-center gap-4 px-4 py-3 bg-white shadow-sm z-10">
                <div className="flex items-center gap-2">
                    <span className="text-2xl">🅿️</span>
                    <h1 className="text-lg font-semibold text-gray-800">MelParking</h1>
                </div>
                <div className="flex-1 max-w-xl">
                    <SearchBar onSearch={handleSearch} loading={loading} />
                </div>
                {error && (
                    <p className="text-sm text-red-500">{error}</p>
                )}
            </header>

            <div className="flex flex-1 overflow-hidden">
                <aside className="w-80 flex-shrink-0 overflow-y-auto bg-white border-r border-gray-200">
                    <ZoneList
                        results={results}
                        loading={loading}
                        selected={selected}
                        onSelect={setSelected}
                    />
                </aside>

                <main className="flex-1">
                    <Map
                        results={results}
                        selected={selected}
                        onSelect={setSelected}
                    />
                </main>
            </div>
        </div>
    )
}

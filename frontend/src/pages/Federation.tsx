import { useEffect, useState } from 'react'
import { api, can } from '../api'
import type { AdapterInfo, DiscoveredCamera } from '../api'

// Model 3: the middleware layer. Each adapter speaks one departmental
// system's dialect and hands back the same shape, so onboarding a new vendor
// never touches the registry or the workers.

export default function Federation() {
  const [rows, setRows] = useState<AdapterInfo[]>([])
  const [open, setOpen] = useState<string | null>(null)
  const [found, setFound] = useState<DiscoveredCamera[]>([])
  const [busy, setBusy] = useState('')
  const [note, setNote] = useState('')
  const [err, setErr] = useState('')

  const load = () => api.adapters().then(setRows).catch((e) => setErr(e.message ?? String(e)))
  useEffect(() => { load() }, [])

  const discover = async (key: string, probe: boolean) => {
    setBusy(key); setErr(''); setNote(''); setOpen(key)
    try {
      const r = await api.discoverAdapter(key, probe)
      setFound(r.cameras)
      setNote(`${r.count} camera${r.count === 1 ? '' : 's'} discovered via ${key}`)
    } catch (e: any) { setErr(e.message ?? String(e)); setFound([]) } finally { setBusy('') }
  }

  const onboard = async (key: string) => {
    setBusy(key); setErr(''); setNote('')
    try {
      const r = await api.onboardAdapter(key)
      setNote(`${key}: ${r.created} created, ${r.updated} updated from ${r.discovered} discovered`)
      await load()
    } catch (e: any) { setErr(e.message ?? String(e)) } finally { setBusy('') }
  }

  const configured = rows.filter((r) => r.configured).length

  return (
    <>
      <h2>Federation</h2>
      <div className="sub">
        {configured} of {rows.length} adapters configured · each speaks one departmental
        system and returns the same shape
      </div>
      {err && <div className="err">{err}</div>}
      {note && <div className="note">{note}</div>}

      <div className="panel">
        <h3>Registered adapters</h3>
        <table>
          <thead>
            <tr><th>Adapter</th><th>Vendor</th><th>Protocols</th><th>State</th><th></th></tr>
          </thead>
          <tbody>
            {rows.map((a) => (
              <tr key={a.key}>
                <td>
                  <strong>{a.label}</strong>
                  <div className="mono" style={{ fontSize: 11, color: 'var(--dim)' }}>{a.key}</div>
                </td>
                <td style={{ color: 'var(--dim)' }}>{a.vendor}</td>
                <td>
                  {a.protocols.map((p) => (
                    <span className="pill unknown" key={p} style={{ marginRight: 4 }}>{p}</span>
                  ))}
                </td>
                <td>
                  {a.configured
                    ? <span className="pill online">ready</span>
                    : <span className="pill unknown">not configured</span>}
                  <div style={{ fontSize: 11, color: 'var(--dim)', marginTop: 3 }}>{a.detail}</div>
                </td>
                <td style={{ textAlign: 'right', whiteSpace: 'nowrap' }}>
                  <button disabled={!a.configured || !!busy}
                          onClick={() => discover(a.key, false)}>
                    {busy === a.key ? 'Working…' : 'Discover'}
                  </button>
                  <button disabled={!a.configured || !!busy} style={{ marginLeft: 6 }}
                          onClick={() => discover(a.key, true)}>
                    Discover + probe
                  </button>
                  {can('admin') && (
                    <button className="primary" style={{ marginLeft: 6 }}
                            disabled={!a.configured || !!busy}
                            onClick={() => onboard(a.key)}>
                      Onboard
                    </button>
                  )}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      {open && (
        <div className="panel">
          <h3>Discovered via {open}</h3>
          {found.length === 0 ? (
            <div className="empty">Nothing discovered.</div>
          ) : (
            <div style={{ overflowX: 'auto' }}>
              <table>
                <thead>
                  <tr><th>External id</th><th>Name</th><th>Type</th><th>Department</th>
                      <th>Vendor</th><th>Reachable</th><th>Source URL</th></tr>
                </thead>
                <tbody>
                  {found.map((c) => (
                    <tr key={c.external_id}>
                      <td className="mono">{c.external_id}</td>
                      <td>{c.name}</td>
                      <td><span className="pill unknown">{c.camera_type}</span></td>
                      <td style={{ color: 'var(--dim)' }}>{c.department || '—'}</td>
                      <td style={{ color: 'var(--dim)', fontSize: 12 }}>{c.vendor || '—'}</td>
                      <td>
                        {c.reachable === true ? <span className="pill online">yes</span>
                          : c.reachable === false ? <span className="pill offline">no</span>
                          : <span className="pill unknown">unknown</span>}
                      </td>
                      <td className="mono" style={{ fontSize: 11, color: 'var(--dim)',
                                                    maxWidth: 320, overflow: 'hidden',
                                                    textOverflow: 'ellipsis' }}>
                        {c.rtsp_url || c.hls_url || '—'}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </div>
      )}
    </>
  )
}

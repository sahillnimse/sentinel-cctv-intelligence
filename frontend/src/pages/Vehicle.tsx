import { useCallback, useEffect, useState } from 'react'
import { useNavigate, useParams } from 'react-router-dom'
import { api, errorMessage } from '../api'
import type { VehicleTraceResult } from '../api'
import { ErrorBanner } from '../components/Notice'
import {
  AlertTriangleIcon,
  CarIcon,
  FileTextIcon,
  MapPinIcon,
  SearchIcon,
  ShieldIcon,
} from '../components/Icons'

function text(v: unknown, fallback = '—'): string {
  const s = String(v ?? '').trim()
  return s || fallback
}

function inr(n: unknown): string {
  const v = Number(n ?? 0)
  if (!Number.isFinite(v)) return '₹0'
  return '₹' + v.toLocaleString('en-IN', { maximumFractionDigits: 0 })
}

function fmtDate(v: unknown): string {
  const s = String(v ?? '').trim()
  if (!s || s.toLowerCase() === 'null') return '—'
  const d = new Date(s.length === 10 && /^\d{4}-\d{2}-\d{2}$/.test(s) ? s + 'T00:00:00' : s)
  if (Number.isNaN(d.getTime())) return s
  return d.toLocaleDateString('en-IN', { day: 'numeric', month: 'long', year: 'numeric' })
}

function fmtDateTime(v: unknown): string {
  const s = String(v ?? '').trim()
  if (!s) return '—'
  const d = new Date(s.replace(' ', 'T'))
  if (Number.isNaN(d.getTime())) return s
  return d.toLocaleString('en-IN', {
    day: '2-digit', month: 'short', year: 'numeric',
    hour: '2-digit', minute: '2-digit', hour12: false,
  })
}

function ownerLabel(v: unknown): string {
  const n = parseInt(String(v ?? ''), 10)
  if (!Number.isFinite(n) || n <= 0) return text(v)
  if (n === 1) return '1st Owner'
  if (n === 2) return '2nd Owner'
  if (n === 3) return '3rd Owner'
  return `${n}th Owner`
}

function rcBadgeClass(status: string): string {
  const s = status.toUpperCase()
  if (s === 'ACTIVE') return 'online'
  if (s.includes('EXPIRED') || s.includes('INACTIVE') || s.includes('SUSPEND') || s.includes('CANCEL')) return 'offline'
  return 'flag'
}

function challanBadgeClass(status: string): string {
  const s = status.toUpperCase()
  if (s === 'PENDING') return 'offline'
  return 'online'
}

function Skeleton({ height = 14 }: { height?: number }) {
  return <div className="skel" style={{ height }} />
}

export default function Vehicle() {
  const { plate_number } = useParams<{ plate_number: string }>()
  const navigate = useNavigate()
  const plate = (plate_number ?? '').toUpperCase()
  const [input, setInput] = useState(plate)
  const [data, setData] = useState<VehicleTraceResult | null>(null)
  const [loading, setLoading] = useState(false)
  const [err, setErr] = useState<string | null>(null)

  const run = useCallback(async (raw: string) => {
    const p = raw.trim().toUpperCase().replace(/[\s-]+/g, '')
    if (!p) return
    setLoading(true)
    setErr(null)
    setData(null)
    try {
      const res = await api.vehicleTrace(p)
      setData(res)
    } catch (e: unknown) {
      setErr(errorMessage(e))
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    setInput(plate)
    if (plate) run(plate)
  }, [plate, run])

  const submit = (e: React.FormEvent) => {
    e.preventDefault()
    const p = input.trim().toUpperCase().replace(/[\s-]+/g, '')
    if (p) navigate(`/vehicle/${encodeURIComponent(p)}`)
  }

  const rcPayload = (data?.rc.payload ?? {}) as Record<string, unknown>
  const rcData = (rcPayload.data ?? rcPayload.result ?? rcPayload.response ?? {}) as Record<string, unknown>
  const rcOk = !!data?.rc.ok
  const rcErr = data?.rc.error
  const ch = data?.challans
  const summary = ch?.summary ?? { pending_count: 0, pending_amount: 0, total_count: 0 }
  const items = ch?.items ?? []

  const rcStatus = String(rcData.rc_status ?? rcData.status ?? '').toUpperCase()
  const brand = (rcData.vehicle_info as Record<string, unknown> | undefined)?.brand_name

  return (
    <>
      <div className="page-header">
        <div>
          <div className="sub" style={{ marginBottom: 4 }}>
            <button type="button" className="chip" onClick={() => navigate('/detections')}>
              ← Back to Detections
            </button>
          </div>
          <h2 className="mono" style={{ fontSize: 30, letterSpacing: '.04em' }}>
            {plate || 'Vehicle Trace'}
          </h2>
          <div className="sub">RTO registry + traffic penalty intelligence, fetched in parallel</div>
        </div>
      </div>

      <div className="panel">
        <form className="row" onSubmit={submit}>
          <div style={{ position: 'relative' }}>
            <input
              className="mono"
              placeholder="e.g. UP16CD1996"
              value={input}
              style={{ width: 240, fontSize: 15, fontWeight: 700, paddingLeft: 34 }}
              onChange={(e) => setInput(e.target.value.toUpperCase())}
              aria-label="Vehicle registration number"
            />
            <SearchIcon
              size={16}
              style={{ position: 'absolute', left: 10, top: '50%', transform: 'translateY(-50%)', color: 'var(--text-dim)' }}
            />
          </div>
          <button className="primary" type="submit" disabled={loading || !input.trim()}>
            {loading ? 'Tracing…' : 'Trace Vehicle'}
          </button>
          {data?.meta.mocked && (
            <span className="pill flag" title="Keys or challan host missing — sample payload">Sample data</span>
          )}
          {data && !data.meta.mocked && (
            <span className="pill online" title={`Live lookup in ${data.meta.duration_ms} ms`}>Live</span>
          )}
        </form>
      </div>

      {err && <ErrorBanner error={new Error(err)} />}

      {loading && (
        <>
          <div className="panel">
            <h3><CarIcon size={14} /> RC details</h3>
            <Skeleton height={26} />
            <div style={{ height: 10 }} />
            <Skeleton /><div style={{ height: 8 }} /><Skeleton /><div style={{ height: 8 }} /><Skeleton />
          </div>
          <div className="panel">
            <h3><FileTextIcon size={14} /> Traffic penalties</h3>
            <Skeleton height={22} />
            <div style={{ height: 10 }} />
            <Skeleton /><div style={{ height: 8 }} /><Skeleton />
          </div>
        </>
      )}

      {!loading && data && !rcOk && (
        <div className="err">
          <AlertTriangleIcon size={18} />
          <div>
            <strong>RTO lookup failed.</strong>{' '}
            {rcErr ? rcErr.message : 'Vehicle not found in the RTO database.'}
          </div>
        </div>
      )}

      {!loading && data && rcOk && (
        <>
          <div className="panel panel-accent">
            <h3><CarIcon size={14} /> {text(rcData.maker_model, 'Vehicle RC Details')}</h3>
            <div className="def-grid">
              <div>
                <div className="def-k">Registration Number</div>
                <div className="def-v mono">{text(rcData.registration_no ?? data.plate)}</div>
              </div>
              <div>
                <div className="def-k">RC Status</div>
                <div className="def-v">
                  <span className={`pill ${rcBadgeClass(rcStatus || 'UNKNOWN')}`}>{rcStatus || 'UNKNOWN'}</span>
                </div>
              </div>
              <div>
                <div className="def-k">Vehicle Class &amp; Body</div>
                <div className="def-v">{text(rcData.body_type_desc)} / {text(rcData.vehicle_class)}</div>
              </div>
            </div>
          </div>

          <div className="split-even">
            <div className="panel">
              <h3><ShieldIcon size={14} /> Ownership &amp; Registration</h3>
              <div className="def-grid">
                <div>
                  <div className="def-k">Registered Owner</div>
                  <div className="def-v">{text(rcData.owner_name)}</div>
                </div>
                <div>
                  <div className="def-k">Ownership Serial</div>
                  <div className="def-v">{ownerLabel(rcData.ownership)}</div>
                </div>
                <div>
                  <div className="def-k">Registration Authority</div>
                  <div className="def-v">{text(rcData.registration_authority)}</div>
                </div>
                <div>
                  <div className="def-k">Registration Date</div>
                  <div className="def-v">{fmtDate(rcData.registration_date)}</div>
                </div>
                <div>
                  <div className="def-k">Chassis No</div>
                  <div className="def-v mono">{text(rcData.chassis_no)}</div>
                </div>
                <div>
                  <div className="def-k">Engine No</div>
                  <div className="def-v mono">{text(rcData.engine_no)}</div>
                </div>
              </div>
            </div>

            <div className="panel">
              <h3><CarIcon size={14} /> Specifications</h3>
              <div className="def-grid">
                <div>
                  <div className="def-k">Fuel &amp; Norms</div>
                  <div className="def-v">{text(rcData.fuel_type)} ({text(rcData.fuel_norms, '—')})</div>
                </div>
                <div>
                  <div className="def-k">Colour</div>
                  <div className="def-v">{text(rcData.vehicle_color)}</div>
                </div>
                <div>
                  <div className="def-k">Seating Capacity</div>
                  <div className="def-v">{text(rcData.seat_capacity)} Seats</div>
                </div>
                <div>
                  <div className="def-k">Unladen Weight</div>
                  <div className="def-v">{text(rcData.unload_weight)} kg</div>
                </div>
                <div>
                  <div className="def-k">Brand / Manufacturer</div>
                  <div className="def-v">{text(brand)}</div>
                </div>
              </div>
            </div>
          </div>

          <div className="panel">
            <h3><FileTextIcon size={14} /> Validity &amp; Compliance</h3>
            <div className="def-grid">
              <div>
                <div className="def-k">Fitness Valid Upto</div>
                <div className="def-v">{fmtDate(rcData.fitness_upto)}</div>
              </div>
              <div>
                <div className="def-k">Road Tax Paid Upto</div>
                <div className="def-v">{fmtDate(rcData.road_tax_paid_upto)}</div>
              </div>
              <div>
                <div className="def-k">Insurance Provider</div>
                <div className="def-v">{text(rcData.insurance_company, 'Not Available')}</div>
              </div>
              <div>
                <div className="def-k">Insurance Validity</div>
                <div className="def-v">
                  {rcData.insurance_upto ? fmtDate(rcData.insurance_upto)
                    : <span className="pill flag">Not Available / Check Policy</span>}
                </div>
              </div>
              <div>
                <div className="def-k">PUC Validity</div>
                <div className="def-v">
                  {rcData.puc_upto ? fmtDate(rcData.puc_upto)
                    : <span className="pill flag">Not Available</span>}
                </div>
              </div>
            </div>
          </div>
        </>
      )}

      {!loading && data && (
        <div className="panel">
          <h3><MapPinIcon size={14} /> Traffic Fines &amp; Penalties</h3>
          {!ch?.ok && (
            <div className="err">
              <AlertTriangleIcon size={18} />
              <div>
                <strong>Challan lookup failed.</strong>{' '}
                {ch?.error ? ch.error.message : 'Unknown vendor error.'}{' '}
                {ch?.error?.code === 'rate_limited' && 'Wait a minute and retry.'}
              </div>
            </div>
          )}
          {ch?.ok && ch.notice && <div className="note">{ch.notice}</div>}
          {ch?.ok && (
            summary.pending_count > 0 ? (
              <>
                <div className="challan-banner">
                  <strong>{summary.pending_count} Pending Challan{summary.pending_count === 1 ? '' : 's'}</strong>
                  <span> — {inr(summary.pending_amount)} Total Fine</span>
                </div>
                <div style={{ overflowX: 'auto' }}>
                <table>
                  <thead>
                    <tr>
                      <th>Challan Number</th>
                      <th>Offense</th>
                      <th>Date &amp; Time</th>
                      <th>Location</th>
                      <th>Amount</th>
                      <th>Status</th>
                    </tr>
                  </thead>
                  <tbody>
                    {items.map((c) => (
                      <tr key={c.challan_number}>
                        <td className="mono" style={{ fontSize: 12 }}>{c.challan_number}</td>
                        <td>{c.offense}</td>
                        <td className="mono" style={{ fontSize: 12, whiteSpace: 'nowrap' }}>{fmtDateTime(c.offense_date)}</td>
                        <td style={{ color: 'var(--text-muted)' }}>{c.location}</td>
                        <td className="mono" style={{ fontWeight: 700 }}>{inr(c.amount)}</td>
                        <td><span className={`pill ${challanBadgeClass(c.status)}`}>{c.status}</span></td>
                      </tr>
                    ))}
                  </tbody>
                </table>
                </div>
              </>
            ) : (
              <div className="note" style={{ marginBottom: 0 }}>
                No active traffic penalties recorded for this vehicle.
              </div>
            )
          )}
        </div>
      )}
    </>
  )
}

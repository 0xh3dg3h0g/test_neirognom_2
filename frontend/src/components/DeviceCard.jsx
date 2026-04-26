import GlassCard from './GlassCard'
import Toggle from './Toggle'

export default function DeviceCard({
  icon,
  title,
  subtitle,
  level,
  enabled,
  onToggle,
  accent,
  action,
  statusText,
  statusColor,
  showProgress = Number.isFinite(level),
  className = '',
}) {
  const detailText = statusText ?? subtitle

  return (
    <GlassCard soft className={`rounded-[24px] px-4 py-3 ${className}`}>
      <div className="flex flex-wrap items-center gap-x-3 gap-y-2">
        <div
          className="flex h-10 w-10 shrink-0 items-center justify-center rounded-[16px] border border-white/10"
          style={{ backgroundColor: `${accent}20`, color: accent, boxShadow: `inset 0 1px 0 rgba(255,255,255,0.12), 0 0 22px ${accent}18` }}
        >
          {icon}
        </div>
        <div className="order-3 shrink-0 lg:order-2 lg:ml-auto scale-95">
          {action ?? <Toggle checked={enabled} onChange={onToggle} />}
        </div>
        <div className="order-2 min-w-[100px] flex-1 lg:order-3 lg:mt-1 lg:w-full lg:flex-none">
          <h3 className="text-[16px] font-semibold leading-tight tracking-tight text-white">{title}</h3>
          {detailText ? (
            <p className="mt-0.5 text-[13px] font-medium text-white/68" style={statusColor ? { color: statusColor } : undefined}>
              {detailText}
            </p>
          ) : null}
        </div>
      </div>
      {showProgress ? (
        <div className="mt-3 h-[4px] rounded-full bg-white/8">
          <div
            className="h-full rounded-full transition-all duration-300"
            style={{
              width: `${level}%`,
              background: `linear-gradient(90deg, ${accent}, rgba(255,255,255,0.78))`,
              boxShadow: `0 0 16px ${accent}55`,
            }}
          />
        </div>
      ) : null}
    </GlassCard>
  )
}

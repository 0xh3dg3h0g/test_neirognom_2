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
  showProgress = true,
}) {
  return (
    <GlassCard soft className="max-w-full rounded-[24px] px-4 py-3">
      <div className="flex min-w-0 items-center gap-4">
        <div
          className="flex h-10 w-10 shrink-0 items-center justify-center rounded-[16px] border border-white/10"
          style={{ backgroundColor: `${accent}20`, color: accent, boxShadow: `inset 0 1px 0 rgba(255,255,255,0.12), 0 0 22px ${accent}18` }}
        >
          {icon}
        </div>
        <div className="min-w-0 flex-1">
          <h3 className="truncate text-[16px] font-semibold leading-tight tracking-tight text-white">{title}</h3>
          <p className="mt-0.5 text-[13px] text-white/68">
            {statusText ?? `${subtitle}: ${level}%`}
          </p>
        </div>
        <div className="shrink-0 scale-95">
          {action ?? <Toggle checked={enabled} onChange={onToggle} />}
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

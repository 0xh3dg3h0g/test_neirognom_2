import { useEffect, useMemo, useState } from 'react'
import ChatPanel from './components/ChatPanel'
import DeviceCard from './components/DeviceCard'
import GlassCard from './components/GlassCard'
import HeaderBar from './components/HeaderBar'
import LedTimeline from './components/LedTimeline'
import MetricCard from './components/MetricCard'
import ThoughtStream from './components/ThoughtStream'
import {
  ledStages,
  sparklineSeries,
} from './data/mock'
import {
  BrainIcon,
  DropletIcon,
  FanIcon,
  HumidityIcon,
  LightIcon,
  PumpIcon,
  SlidersIcon,
  ThermometerIcon,
} from './components/Icons'

const API_BASE_URL =
  window.location.hostname === 'localhost'
    ? 'http://localhost:8000'
    : `${window.location.protocol}//${window.location.hostname}:8000`
const TELEMETRY_POLL_INTERVAL_MS = 2000
const LOGS_POLL_INTERVAL_MS = 5000

const CHAT_THINKING_STEPS = [
  'Получен запрос пользователя',
  'Анализирую смысл сообщения',
  'Определяю нужный контекст',
  'Проверяю доступные данные фермы',
  'Сверяю показатели с нормами',
  'Формирую ответ Нейрогнома',
]

function makeId() {
  if (window.crypto && typeof window.crypto.randomUUID === 'function') {
    return window.crypto.randomUUID()
  }
  return `id-${Date.now()}-${Math.random().toString(16).slice(2)}`
}

function formatTime(date = new Date()) {
  return new Intl.DateTimeFormat('ru-RU', {
    hour: '2-digit',
    minute: '2-digit',
  }).format(date)
}

function formatDate(date = new Date()) {
  return new Intl.DateTimeFormat('ru-RU', {
    day: 'numeric',
    month: 'long',
    year: 'numeric',
  }).format(date)
}

function formatTimestampLabel(timestamp) {
  if (!timestamp || typeof timestamp !== 'string') {
    return formatTime()
  }

  if (timestamp.length >= 16) {
    return timestamp.slice(11, 16)
  }

  return timestamp
}

function toNumberOrFallback(value, fallback) {
  const parsed = Number(value)
  return Number.isFinite(parsed) ? parsed : fallback
}

function buildChatHistory(messages, userMessage) {
  return [...messages, userMessage].map((message) => ({
    role: message.from === 'assistant' ? 'assistant' : 'user',
    content: message.text,
  }))
}

async function requestJson(path, options = {}) {
  const response = await fetch(`${API_BASE_URL}${path}`, {
    headers: {
      'Content-Type': 'application/json',
      ...options.headers,
    },
    ...options,
  })

  if (!response.ok) {
    throw new Error(`Request failed with status ${response.status}`)
  }

  return response.json()
}

function parseLogMeta(entry) {
  try {
    if (!entry?.commands_json) return null

    if (typeof entry.commands_json === 'string') {
      return JSON.parse(entry.commands_json)
    }

    return entry.commands_json
  } catch {
    return null
  }
}

export default function App() {
  const [mode, setMode] = useState('monitoring')
  const [metrics, setMetrics] = useState({ waterTemp: 0, airHumidity: 0, airTemp: 0 })
  const [devices, setDevices] = useState({
    fans: { title: 'Вентиляция', subtitle: 'Обдув', level: 0, enabled: false },
    lights: { title: 'Освещение', subtitle: 'Фитолампы', level: 0, enabled: false },
    pumps: { title: 'Полив', subtitle: 'Насосы', level: 0, enabled: false },
    led: { title: 'LED', scenario: 'Ожидание' }
  })
  const [thoughts, setThoughts] = useState([])
  const [messages, setMessages] = useState([])
  const [chatInput, setChatInput] = useState('')
  const [isChatThinking, setIsChatThinking] = useState(false)
  const [currentTime, setCurrentTime] = useState(formatTime())
  const [currentDate, setCurrentDate] = useState(formatDate())
  const [activeLedStage, setActiveLedStage] = useState(5)
  const [isLedPlaying, setIsLedPlaying] = useState(false)

  const pushThought = (text) => {
    const item = {
      id: makeId(),
      text,
      time: formatTime(),
    }
    setThoughts((prev) => [item, ...prev].slice(0, 5))
  }

  const pushAssistantMessage = (text) => {
    setMessages((prev) => [
      ...prev,
      {
        id: makeId(),
        from: 'assistant',
        text,
        time: formatTime(),
      },
    ])
  }

  useEffect(() => {
    const timer = setInterval(() => {
      const now = new Date()
      setCurrentTime(formatTime(now))
      setCurrentDate(formatDate(now))
    }, 1000)

    return () => clearInterval(timer)
  }, [])

  useEffect(() => {
    let isMounted = true

    const loadTelemetry = async () => {
      try {
        const data = await requestJson('/api/telemetry')
        if (!isMounted) return

        setMetrics((prev) => ({
          waterTemp: toNumberOrFallback(data.water_temp, prev.waterTemp),
          airHumidity: toNumberOrFallback(data.humidity, prev.airHumidity),
          airTemp: toNumberOrFallback(data.air_temp, prev.airTemp),
        }))
      } catch (error) {
        console.error('Failed to load telemetry', error)
      }
    }

    loadTelemetry()
    const telemetryPoller = setInterval(loadTelemetry, TELEMETRY_POLL_INTERVAL_MS)

    return () => {
      isMounted = false
      clearInterval(telemetryPoller)
    }
  }, [])

  useEffect(() => {
    let isMounted = true

    const loadThoughts = async () => {
      try {
        const data = await requestJson('/api/logs?limit=5')
        if (!isMounted || !Array.isArray(data)) return

        setThoughts((prev) => {
          const serverLogs = data
            .filter((entry) => {
              const meta = parseLogMeta(entry)
              return meta?.type !== 'chat'
            })
            .map((entry) => ({
              id: `log-${entry.id ?? makeId()}`,
              text: entry.thought || 'Нет записанной мысли.',
              time: formatTimestampLabel(entry.timestamp),
            }))

          const serverIds = new Set(serverLogs.map((log) => log.id))

          const localLogs = prev.filter(
            (log) => !serverIds.has(log.id) && !log.id.startsWith('log-')
          )

          return [...localLogs, ...serverLogs].slice(0, 15)
        })
      } catch (error) {
        console.error('Failed to load AI logs', error)
      }
    }

    loadThoughts()
    const logsPoller = setInterval(loadThoughts, LOGS_POLL_INTERVAL_MS)

    return () => {
      isMounted = false
      clearInterval(logsPoller)
    }
  }, [])

  useEffect(() => {
    if (!isLedPlaying) return undefined

    const interval = setInterval(() => {
      setActiveLedStage((prev) => {
        const next = prev + 1 > ledStages.length - 1 ? 0 : prev + 1
        setDevices((current) => ({
          ...current,
          led: {
            ...current.led,
            scenario: ledStages[next].label,
          },
        }))
        pushThought(`LED сценарий перешёл на ${ledStages[next].id} — ${ledStages[next].label.toLowerCase()}.`)
        return next
      })
    }, 850)

    const stop = setTimeout(() => setIsLedPlaying(false), 850 * ledStages.length + 250)

    return () => {
      clearInterval(interval)
      clearTimeout(stop)
    }
  }, [isLedPlaying])

  const metricsList = useMemo(
    () => [
      {
        title: 'Температура воды',
        value: metrics.waterTemp,
        unit: '°C',
        norm: '18 – 22 °C',
        color: '#2CB4FF',
        values: sparklineSeries.waterTemp,
        icon: <DropletIcon className="h-6 w-6" />,
      },
      {
        title: 'Влажность воздуха',
        value: metrics.airHumidity,
        unit: '%',
        norm: '52 – 60 %',
        color: '#71F16A',
        values: sparklineSeries.airHumidity,
        icon: <HumidityIcon className="h-6 w-6" />,
      },
      {
        title: 'Температура воздуха',
        value: metrics.airTemp,
        unit: '°C',
        norm: '20 – 25 °C',
        color: '#C668FF',
        values: sparklineSeries.airTemp,
        icon: <ThermometerIcon className="h-6 w-6" />,
      },
    ],
    [metrics],
  )

  const handleToggle = (key) => async (enabled) => {
    const deviceType = {
      fans: 'fan',
      lights: 'light',
      pumps: 'pump',
    }[key]

    const deviceLabel = {
      fans: 'вентиляторы',
      lights: 'освещение',
      pumps: 'насосы',
    }[key]

    setDevices((prev) => ({
      ...prev,
      [key]: {
        ...prev[key],
        enabled,
      },
    }))

    try {
      await requestJson('/api/device/control', {
        method: 'POST',
        body: JSON.stringify({
          target_id: 'tray_1',
          device_type: deviceType,
          state: enabled ? 'ON' : 'OFF',
        }),
      })
      pushThought(`${enabled ? 'Включаю' : 'Выключаю'} ${deviceLabel}.`)
    } catch (error) {
      console.error(`Failed to toggle ${deviceType}`, error)
      setDevices((prev) => ({
        ...prev,
        [key]: {
          ...prev[key],
          enabled: !enabled,
        },
      }))
      pushThought(`Не удалось отправить команду на ${deviceLabel}.`)
    }
  }

  const handleSendMessage = async () => {
    const text = chatInput.trim()
    if (!text || isChatThinking) return

    const userMessage = {
      id: makeId(),
      from: 'user',
      text,
      time: formatTime(),
    }

    setMessages((prev) => [...prev, userMessage])
    setChatInput('')
    setIsChatThinking(true)

    try {
      const data = await requestJson('/api/chat', {
        method: 'POST',
        body: JSON.stringify({
          messages: buildChatHistory(messages, userMessage),
        }),
      })

      pushAssistantMessage(data.reply || 'Недостаточно данных для ответа.')
    } catch (error) {
      console.error('Failed to send chat message', error)

      pushThought('Не удалось получить ответ от backend.')
      pushAssistantMessage('Не удалось подключиться к ассистенту. Проверьте backend.')
    } finally {
      setIsChatThinking(false)
    }
  }

  const renderMonitoring = () => (
    <div className="flex h-full min-h-0 flex-col gap-4">
      <GlassCard className="rounded-[28px] shrink-0">
        <div className="flex items-center justify-between gap-4">
          <div>
            <div className="text-[22px] font-semibold tracking-tight md:text-[24px]">Мониторинг</div>
            <p className="mt-1.5 text-sm text-white/62">Основные параметры фермы в реальном времени.</p>
          </div>
        </div>
        <div className="mt-4 grid grid-cols-1 gap-4 md:grid-cols-2 xl:grid-cols-3">
          {metricsList.map((item) => (
            <MetricCard key={item.title} {...item} />
          ))}
        </div>
      </GlassCard>

      <div className="grid min-h-0 flex-1 grid-cols-1 gap-4 xl:grid-cols-[minmax(0,1fr)_320px]">
        <GlassCard className="flex min-h-0 flex-col overflow-hidden rounded-[28px]">
          <div className="flex shrink-0 items-center gap-3">
            <div className="flex h-11 w-11 items-center justify-center rounded-2xl border border-white/10 bg-white/8 text-white/90">
              <SlidersIcon className="h-5 w-5" />
            </div>
            <div>
              <div className="text-[22px] font-semibold tracking-tight md:text-[24px] xl:text-[22px] 2xl:text-[24px]">Состояние фермы</div>
              <p className="mt-1.5 text-sm text-white/62 xl:mt-1 xl:text-[13px] 2xl:mt-1.5 2xl:text-sm">Сводка системы и текущий статус.</p>
            </div>
          </div>
          <div className="mt-6 grid grid-cols-[repeat(auto-fit,minmax(190px,1fr))] gap-3 overflow-hidden xl:mt-5 2xl:mt-6">
            {[
              {
                title: 'Полив',
                status: 'Работает штатно',
                description: 'Система полива функционирует в автоматическом режиме.',
                icon: <PumpIcon className="h-10 w-10" />,
                accent: '#2CB4FF',
              },
              {
                title: 'Освещение',
                status: 'Дневной режим активен',
                description: 'LED-освещение работает по дневному сценарию.',
                icon: <LightIcon className="h-10 w-10" />,
                accent: '#FFD667',
              },
              {
                title: 'Вентиляция',
                status: 'Стабильная работа',
                description: 'Параметры воздуха в пределах нормы.',
                icon: <FanIcon className="h-10 w-10" />,
                accent: '#75F08D',
              },
              {
                title: 'Совет Нейрогнома',
                status: 'Параметры в пределах нормы',
                description: 'Продолжайте текущий режим. Отличная работа!',
                icon: <BrainIcon className="h-10 w-10" />,
                accent: '#C668FF',
              },
            ].map((item) => (
              <GlassCard key={item.title} soft className="flex min-h-[260px] flex-col items-center rounded-[24px] px-4 py-6 text-center">
                <div className="text-[17px] font-semibold text-white">{item.title}</div>
                <div
                  className="mt-7 flex h-20 w-20 items-center justify-center rounded-full border"
                  style={{
                    borderColor: `${item.accent}80`,
                    color: item.accent,
                    backgroundColor: `${item.accent}18`,
                    boxShadow: `0 0 26px ${item.accent}30`,
                  }}
                >
                  {item.icon}
                </div>
                <div className="mt-7 text-[14px] font-semibold" style={{ color: item.accent }}>
                  {item.status}
                </div>
                <p className="mt-4 flex-1 text-[13px] leading-relaxed text-white/62">{item.description}</p>
                <div className="mt-5 h-[3px] w-full rounded-full" style={{ backgroundColor: item.accent, boxShadow: `0 0 14px ${item.accent}70` }} />
              </GlassCard>
            ))}
          </div>
        </GlassCard>

        <div className="min-h-0">
          <ThoughtStream thoughts={thoughts} className="h-full" />
        </div>
      </div>
    </div>
  )

  const renderManual = () => (
    <div className="grid h-full min-h-0 gap-4 xl:grid-rows-[auto_minmax(0,1fr)]">
      <GlassCard className="rounded-[28px]">
        <div className="flex items-center gap-3">
          <div className="flex h-11 w-11 items-center justify-center rounded-2xl border border-white/10 bg-white/8 text-white/90">
            <SlidersIcon className="h-5 w-5" />
          </div>
          <div>
            <div className="text-[22px] font-semibold tracking-tight md:text-[24px]">Ручное управление</div>
          </div>
        </div>

        <div className="mt-7 grid gap-4 lg:grid-cols-3">
          <DeviceCard
            title={devices.fans.title}
            statusText={`Состояние: ${devices.fans.enabled ? 'включено' : 'выключено'}`}
            statusColor={devices.fans.enabled ? '#53E78A' : undefined}
            enabled={devices.fans.enabled}
            onToggle={handleToggle('fans')}
            icon={<FanIcon className="h-7 w-7" />}
            accent="#75F08D"
            showProgress={false}
            className="min-h-[150px] lg:min-h-[176px]"
          />
          <DeviceCard
            title={devices.lights.title}
            statusText={`Состояние: ${devices.lights.enabled ? 'включено' : 'выключено'}`}
            statusColor={devices.lights.enabled ? '#53E78A' : undefined}
            enabled={devices.lights.enabled}
            onToggle={handleToggle('lights')}
            icon={<LightIcon className="h-7 w-7" />}
            accent="#FFD667"
            showProgress={false}
            className="min-h-[150px] lg:min-h-[176px]"
          />
          <DeviceCard
            title={devices.pumps.title}
            statusText={`Состояние: ${devices.pumps.enabled ? 'включено' : 'выключено'}`}
            statusColor={devices.pumps.enabled ? '#53E78A' : undefined}
            enabled={devices.pumps.enabled}
            onToggle={handleToggle('pumps')}
            icon={<PumpIcon className="h-7 w-7" />}
            accent="#8EC8FF"
            showProgress={false}
            className="min-h-[150px] lg:min-h-[176px]"
          />
        </div>
      </GlassCard>

      <LedTimeline
        stages={ledStages}
        activeIndex={activeLedStage}
        isPlaying={isLedPlaying}
        onPlay={() => {
          setActiveLedStage(0)
          setIsLedPlaying(true)
        }}
        compact
      />
    </div>
  )

  return (
    <div className="farm-shell relative min-h-screen overflow-x-hidden px-3 py-3 md:px-4 md:py-4 xl:h-screen xl:overflow-hidden xl:px-6 xl:py-6">
      <div className="mx-auto flex h-full w-full max-w-[1800px] flex-col gap-4">
        <HeaderBar
          mode={mode}
          setMode={setMode}
          currentTime={currentTime}
          currentDate={currentDate}
        />

        <main className="grid flex-1 min-h-0 gap-4 xl:grid-cols-[minmax(0,1fr)_320px]">
          <div className="flex h-full min-h-0 flex-col">{mode === 'monitoring' ? renderMonitoring() : renderManual()}</div>

          <aside className="flex h-full min-h-0 flex-col">
            <ChatPanel
              messages={messages}
              input={chatInput}
              onInput={setChatInput}
              onSend={handleSendMessage}
              isThinking={isChatThinking}
              thinkingSteps={CHAT_THINKING_STEPS}
              className="flex-1"
            />
          </aside>
        </main>
      </div>
    </div>
  )
}

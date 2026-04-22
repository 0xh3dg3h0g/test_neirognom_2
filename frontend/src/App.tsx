import { type CSSProperties, useEffect, useMemo, useRef, useState } from 'react'
import mqtt, { type MqttClient } from 'mqtt'
import {
  CartesianGrid,
  Line,
  LineChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from 'recharts'

const IS_LOCAL =
  window.location.hostname === 'localhost' || window.location.hostname === '127.0.0.1'
const MQTT_WS_URL = 'ws://31.56.208.196:9001'
const API_BASE_URL = IS_LOCAL ? 'http://127.0.0.1:8000/api' : 'http://31.56.208.196:8000/api'
const DEVICE_CONTROL_URL = `${API_BASE_URL}/device/control`
const AI_LOGS_URL = `${API_BASE_URL}/logs?limit=20`
const SENSORS_TOPIC = 'farm/tray_1/sensors/#'
const HISTORY_LIMIT = 36

type ActiveTab = 'monitor' | 'control'
type CommandState = 'ON' | 'OFF' | 'TIMER'
type DeviceType = 'pump' | 'light' | 'fan'
type ChartMetric = 'temperature' | 'humidity' | 'light'

type ClimateMessage = {
  air_temp?: number
  humidity?: number
}

type AiCommand = {
  device_type: DeviceType
  state: CommandState
  duration?: number
}

type AiLog = {
  id: number
  timestamp: string
  thought: string
  commands_json: string
}

type TelemetryPoint = {
  time: string
  temperature: number
  humidity: number
  light: number
}

type GaugeCardProps = {
  label: string
  value: number
  suffix: string
  min: number
  max: number
  color: string
}

type DeviceCardProps = {
  title: string
  deviceType: DeviceType
  timerValue: string
  onTimerChange: (value: string) => void
  onSendCommand: (deviceType: DeviceType, state: CommandState, duration?: number) => void
}

const TEXT = {
  appName: 'Нейроагроном',
  title: 'Продвинутый мониторинг городской фермы',
  subtitle:
    'Темная стеклянная панель с живыми датчиками, рельефной историей показаний и отдельной вкладкой ручного управления.',
  tabs: {
    monitor: 'Мониторинг',
    control: 'Ручное управление',
  },
  sensors: {
    temperature: 'Температура',
    humidity: 'Влажность',
    light: 'Освещение',
  },
  sections: {
    telemetry: 'Датчики',
    history: 'Горы и равнины',
    thoughts: 'Поток мыслей ИИ',
    control: 'Реле и LED',
    simulation: 'Симуляция',
  },
  devices: {
    pump: 'Насос',
    light: 'LED / Свет',
    fan: 'Вентилятор',
  },
  actions: {
    on: 'Включить',
    off: 'Выключить',
    timed: 'На время',
    heat: 'Имитировать жару',
    cold: 'Имитировать холод',
    normal: 'Вернуть норму',
  },
  status: {
    ready: 'Система готова.',
    loadingLogs: 'Не удалось загрузить лог мыслей ИИ',
    mqttError: 'Ошибка MQTT-подключения',
    mqttMessage: 'Не удалось обработать MQTT-сообщение',
    commandError: 'Не удалось отправить команду',
    simulationError: 'MQTT недоступен для симуляции',
    simulationSent: 'Команда симуляции отправлена',
    noThoughts: 'Логи ИИ пока не пришли.',
  },
  chart: {
    temperature: 'Температура',
    humidity: 'Влажность',
    light: 'Освещение',
  },
} as const

const glassCardClassName = 'bg-white/5 backdrop-blur-md border border-white/10 rounded-2xl text-white'

const glassCardStyle: CSSProperties = {
  background: 'rgba(255, 255, 255, 0.05)',
  backdropFilter: 'blur(16px)',
  WebkitBackdropFilter: 'blur(16px)',
  border: '1px solid rgba(255, 255, 255, 0.1)',
  borderRadius: 24,
  color: '#ffffff',
  boxShadow:
    'inset 0 1px 0 rgba(255,255,255,0.12), 0 20px 44px rgba(2,6,20,0.32), 0 0 24px rgba(96,165,250,0.08)',
}

const panelButtonStyle: CSSProperties = {
  border: '1px solid rgba(255,255,255,0.12)',
  borderRadius: 16,
  background: 'rgba(255,255,255,0.06)',
  color: '#fff',
  padding: '12px 16px',
  cursor: 'pointer',
  transition: 'all 0.25s ease',
  boxShadow: '0 12px 24px rgba(2,6,20,0.18), inset 0 1px 0 rgba(255,255,255,0.1)',
}

const activeTabButtonStyle: CSSProperties = {
  ...panelButtonStyle,
  background: 'rgba(96, 165, 250, 0.18)',
  border: '1px solid rgba(147, 197, 253, 0.28)',
}

const inputStyle: CSSProperties = {
  width: '100%',
  minHeight: 46,
  borderRadius: 14,
  border: '1px solid rgba(255,255,255,0.1)',
  background: 'rgba(255,255,255,0.05)',
  color: '#fff',
  padding: '0 14px',
  outline: 'none',
}

const chartMeta: Record<ChartMetric, { dataKey: ChartMetric; color: string; suffix: string }> = {
  temperature: { dataKey: 'temperature', color: '#34d399', suffix: '°C' },
  humidity: { dataKey: 'humidity', color: '#60a5fa', suffix: '%' },
  light: { dataKey: 'light', color: '#fbbf24', suffix: '%' },
}

function formatTimeLabel(date = new Date()) {
  return date.toLocaleTimeString('ru-RU', {
    hour: '2-digit',
    minute: '2-digit',
    second: '2-digit',
  })
}

function parseCommands(commandsJson: string): AiCommand[] {
  try {
    const parsed = JSON.parse(commandsJson) as unknown
    return Array.isArray(parsed) ? (parsed as AiCommand[]) : []
  } catch {
    return []
  }
}

function formatCommand(command: AiCommand) {
  if (command.state === 'TIMER' && typeof command.duration === 'number') {
    return `${command.device_type}: TIMER ${command.duration} sec`
  }

  return `${command.device_type}: ${command.state}`
}

function GaugeCard({ label, value, suffix, min, max, color }: GaugeCardProps) {
  const normalized = Math.min(Math.max((value - min) / (max - min), 0), 1)
  const radius = 54
  const stroke = 12
  const circumference = 2 * Math.PI * radius
  const dashOffset = circumference * (1 - normalized)

  return (
    <article
      className={glassCardClassName}
      style={{
        ...glassCardStyle,
        padding: 24,
        display: 'grid',
        gap: 18,
      }}
    >
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', gap: 12 }}>
        <h3 style={{ margin: 0, fontSize: '1rem', fontWeight: 700 }}>{label}</h3>
        <span style={{ color: 'rgba(226,232,240,0.78)', fontSize: '0.85rem' }}>
          {min}–{max}
          {suffix}
        </span>
      </div>

      <div style={{ display: 'grid', placeItems: 'center' }}>
        <svg width="150" height="150" viewBox="0 0 150 150" role="img" aria-label={label}>
          <circle
            cx="75"
            cy="75"
            r={radius}
            fill="none"
            stroke="rgba(255,255,255,0.12)"
            strokeWidth={stroke}
          />
          <circle
            cx="75"
            cy="75"
            r={radius}
            fill="none"
            stroke={color}
            strokeWidth={stroke}
            strokeLinecap="round"
            strokeDasharray={circumference}
            strokeDashoffset={dashOffset}
            transform="rotate(-90 75 75)"
            style={{ transition: 'stroke-dashoffset 320ms ease' }}
          />
          <text
            x="75"
            y="70"
            textAnchor="middle"
            fill="#ffffff"
            fontSize="28"
            fontWeight="700"
          >
            {Math.round(value)}
          </text>
          <text x="75" y="94" textAnchor="middle" fill="rgba(191,219,254,0.9)" fontSize="14">
            {suffix}
          </text>
        </svg>
      </div>
    </article>
  )
}

function DeviceCard({
  title,
  deviceType,
  timerValue,
  onTimerChange,
  onSendCommand,
}: DeviceCardProps) {
  const handleTimer = () => {
    const duration = Number(timerValue)

    if (!Number.isFinite(duration) || duration <= 0) {
      return
    }

    onSendCommand(deviceType, 'TIMER', duration)
  }

  return (
    <article
      className={glassCardClassName}
      style={{
        ...glassCardStyle,
        padding: 20,
        display: 'grid',
        gap: 16,
      }}
    >
      <div style={{ display: 'flex', justifyContent: 'space-between', gap: 12, alignItems: 'center' }}>
        <h3 style={{ margin: 0 }}>{title}</h3>
        <span style={{ color: 'rgba(148,163,184,0.9)', fontSize: '0.8rem', textTransform: 'uppercase' }}>
          {deviceType}
        </span>
      </div>

      <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 12 }}>
        <button type="button" style={panelButtonStyle} onClick={() => onSendCommand(deviceType, 'ON')}>
          {TEXT.actions.on}
        </button>
        <button type="button" style={panelButtonStyle} onClick={() => onSendCommand(deviceType, 'OFF')}>
          {TEXT.actions.off}
        </button>
      </div>

      <div style={{ display: 'grid', gridTemplateColumns: '1fr auto', gap: 12 }}>
        <input
          type="number"
          min="1"
          step="1"
          value={timerValue}
          onChange={(event) => onTimerChange(event.target.value)}
          style={inputStyle}
          placeholder="5"
        />
        <button type="button" style={panelButtonStyle} onClick={handleTimer}>
          {TEXT.actions.timed}
        </button>
      </div>
    </article>
  )
}

function App() {
  const [activeTab, setActiveTab] = useState<ActiveTab>('monitor')
  const [selectedMetric, setSelectedMetric] = useState<ChartMetric>('temperature')
  const [temperature, setTemperature] = useState(0)
  const [humidity, setHumidity] = useState(0)
  const [light, setLight] = useState(0)
  const [telemetryHistory, setTelemetryHistory] = useState<TelemetryPoint[]>([])
  const [aiLogs, setAiLogs] = useState<AiLog[]>([])
  const [requestState, setRequestState] = useState<string>(TEXT.status.ready)
  const [timerValues, setTimerValues] = useState<Record<DeviceType, string>>({
    pump: '5',
    light: '5',
    fan: '5',
  })

  const mqttClientRef = useRef<MqttClient | null>(null)
  const thoughtsRef = useRef<HTMLDivElement | null>(null)
  const lightTimerRef = useRef<number | null>(null)
  const lastHistorySignatureRef = useRef('')

  const currentChartMeta = chartMeta[selectedMetric]

  const thoughtLines = useMemo(
    () =>
      aiLogs.map((log) => {
        const commands = parseCommands(log.commands_json)
        const commandText =
          commands.length > 0 ? commands.map((command) => formatCommand(command)).join(' | ') : 'no-actions'

        return `[${log.timestamp}] ${log.thought || 'AI обновил состояние без пояснения.'} :: ${commandText}`
      }),
    [aiLogs],
  )

  useEffect(() => {
    const loadAiLogs = async () => {
      try {
        const response = await fetch(AI_LOGS_URL)
        if (!response.ok) {
          throw new Error(`HTTP ${response.status}`)
        }

        const payload = (await response.json()) as AiLog[]
        setAiLogs(Array.isArray(payload) ? [...payload].reverse() : [])
      } catch (error) {
        console.error(TEXT.status.loadingLogs, error)
      }
    }

    void loadAiLogs()
    const intervalId = window.setInterval(() => {
      void loadAiLogs()
    }, 15000)

    return () => {
      window.clearInterval(intervalId)
    }
  }, [])

  useEffect(() => {
    const client = mqtt.connect(MQTT_WS_URL)
    mqttClientRef.current = client

    const handleMessage = (topic: string, message: Buffer<ArrayBufferLike>) => {
      try {
        const payload = JSON.parse(message.toString()) as ClimateMessage

        if (topic.endsWith('/climate')) {
          if (typeof payload.air_temp === 'number') {
            setTemperature(payload.air_temp)
          }

          if (typeof payload.humidity === 'number') {
            setHumidity(payload.humidity)
          }
        }
      } catch (error) {
        console.error(TEXT.status.mqttMessage, error)
      }
    }

    client.on('connect', () => {
      client.subscribe(SENSORS_TOPIC)
    })

    client.on('message', handleMessage)
    client.on('error', (error) => {
      console.error(TEXT.status.mqttError, error)
    })

    return () => {
      mqttClientRef.current = null
      client.end(true)
    }
  }, [])

  useEffect(() => {
    const signature = `${temperature.toFixed(2)}|${humidity.toFixed(2)}|${light.toFixed(2)}`

    if (lastHistorySignatureRef.current === signature) {
      return
    }

    lastHistorySignatureRef.current = signature

    setTelemetryHistory((current) => [
      ...current.slice(-(HISTORY_LIMIT - 1)),
      {
        time: formatTimeLabel(),
        temperature,
        humidity,
        light,
      },
    ])
  }, [temperature, humidity, light])

  useEffect(() => {
    if (!thoughtsRef.current) {
      return
    }

    thoughtsRef.current.scrollTop = thoughtsRef.current.scrollHeight
  }, [thoughtLines])

  useEffect(() => {
    return () => {
      if (lightTimerRef.current !== null) {
        window.clearTimeout(lightTimerRef.current)
      }
    }
  }, [])

  const sendCommand = async (deviceType: DeviceType, state: CommandState, duration?: number) => {
    setRequestState(`Отправка ${state} для ${deviceType}`)

    if (deviceType === 'light') {
      if (lightTimerRef.current !== null) {
        window.clearTimeout(lightTimerRef.current)
        lightTimerRef.current = null
      }

      if (state === 'ON') {
        setLight(100)
      } else if (state === 'OFF') {
        setLight(0)
      } else if (state === 'TIMER' && typeof duration === 'number') {
        setLight(100)
        lightTimerRef.current = window.setTimeout(() => {
          setLight(0)
          lightTimerRef.current = null
        }, duration * 1000)
      }
    }

    try {
      const response = await fetch(DEVICE_CONTROL_URL, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
        },
        body: JSON.stringify({
          target_id: 'tray_1',
          device_type: deviceType,
          state,
          ...(state === 'TIMER' && typeof duration === 'number' ? { duration } : {}),
        }),
      })

      if (!response.ok) {
        throw new Error(`HTTP ${response.status}`)
      }

      setRequestState(`Команда ${state} для ${deviceType} отправлена`)
    } catch (error) {
      console.error(TEXT.status.commandError, error)
      setRequestState(TEXT.status.commandError)
    }
  }

  const publishSimulationMode = (mode: 'HEAT' | 'COLD' | 'NORMAL') => {
    const client = mqttClientRef.current

    if (!client || !client.connected) {
      setRequestState(TEXT.status.simulationError)
      return
    }

    client.publish('farm/sim/control', mode)
    setRequestState(`${TEXT.status.simulationSent}: ${mode}`)
  }

  const setTimerValue = (deviceType: DeviceType, nextValue: string) => {
    setTimerValues((current) => ({
      ...current,
      [deviceType]: nextValue,
    }))
  }

  return (
    <main
      style={{
        minHeight: '100vh',
        background: '#0a0e22',
        color: '#fff',
        padding: '32px 20px 48px',
      }}
    >
      <div style={{ width: 'min(1280px, 100%)', margin: '0 auto', display: 'grid', gap: 24 }}>
        <header style={{ display: 'grid', gap: 10 }}>
          <p
            style={{
              margin: 0,
              fontSize: 12,
              letterSpacing: '0.14em',
              textTransform: 'uppercase',
              color: '#34d399',
              fontWeight: 700,
            }}
          >
            {TEXT.appName}
          </p>
          <h1 style={{ margin: 0, fontSize: 'clamp(2.1rem, 4vw, 3.6rem)', lineHeight: 1.05 }}>
            {TEXT.title}
          </h1>
          <p style={{ margin: 0, color: '#b8c6db', maxWidth: 760, lineHeight: 1.65 }}>
            {TEXT.subtitle}
          </p>
        </header>

        <section
          className={glassCardClassName}
          style={{
            ...glassCardStyle,
            padding: 12,
            display: 'flex',
            gap: 12,
            flexWrap: 'wrap',
          }}
        >
          <button
            type="button"
            style={activeTab === 'monitor' ? activeTabButtonStyle : panelButtonStyle}
            onClick={() => setActiveTab('monitor')}
          >
            {TEXT.tabs.monitor}
          </button>
          <button
            type="button"
            style={activeTab === 'control' ? activeTabButtonStyle : panelButtonStyle}
            onClick={() => setActiveTab('control')}
          >
            {TEXT.tabs.control}
          </button>
        </section>

        {activeTab === 'monitor' ? (
          <>
            <section style={{ display: 'grid', gap: 16 }}>
              <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', gap: 12 }}>
                <h2 style={{ margin: 0, fontSize: '1.15rem' }}>{TEXT.sections.telemetry}</h2>
                <span style={{ color: '#94a3b8' }}>{requestState}</span>
              </div>

              <div
                style={{
                  display: 'grid',
                  gridTemplateColumns: 'repeat(auto-fit, minmax(240px, 1fr))',
                  gap: 20,
                }}
              >
                <GaugeCard
                  label={TEXT.sensors.temperature}
                  value={temperature}
                  suffix="°C"
                  min={0}
                  max={40}
                  color="#34d399"
                />
                <GaugeCard
                  label={TEXT.sensors.humidity}
                  value={humidity}
                  suffix="%"
                  min={0}
                  max={100}
                  color="#60a5fa"
                />
                <GaugeCard
                  label={TEXT.sensors.light}
                  value={light}
                  suffix="%"
                  min={0}
                  max={100}
                  color="#fbbf24"
                />
              </div>
            </section>

            <section
              className={glassCardClassName}
              style={{
                ...glassCardStyle,
                padding: 24,
                display: 'grid',
                gap: 18,
              }}
            >
              <div
                style={{
                  display: 'flex',
                  justifyContent: 'space-between',
                  alignItems: 'center',
                  gap: 12,
                  flexWrap: 'wrap',
                }}
              >
                <h2 style={{ margin: 0, fontSize: '1.15rem' }}>{TEXT.sections.history}</h2>
                <div style={{ display: 'flex', gap: 10, flexWrap: 'wrap' }}>
                  {(['temperature', 'humidity', 'light'] as ChartMetric[]).map((metric) => (
                    <button
                      key={metric}
                      type="button"
                      style={selectedMetric === metric ? activeTabButtonStyle : panelButtonStyle}
                      onClick={() => setSelectedMetric(metric)}
                    >
                      {TEXT.chart[metric]}
                    </button>
                  ))}
                </div>
              </div>

              <div style={{ width: '100%', height: 320 }}>
                <ResponsiveContainer>
                  <LineChart data={telemetryHistory}>
                    <CartesianGrid stroke="rgba(255,255,255,0.08)" strokeDasharray="4 4" />
                    <XAxis dataKey="time" stroke="#94a3b8" tick={{ fill: '#94a3b8', fontSize: 12 }} />
                    <YAxis
                      domain={['auto', 'auto']}
                      stroke="#94a3b8"
                      tick={{ fill: '#94a3b8', fontSize: 12 }}
                    />
                    <Tooltip
                      contentStyle={{
                        background: 'rgba(15, 23, 42, 0.92)',
                        border: '1px solid rgba(255,255,255,0.1)',
                        borderRadius: 14,
                        color: '#fff',
                      }}
                      labelStyle={{ color: '#cbd5e1' }}
                    />
                    <Line
                      type="monotone"
                      dataKey={currentChartMeta.dataKey}
                      stroke={currentChartMeta.color}
                      strokeWidth={3}
                      dot={false}
                      activeDot={{ r: 5, fill: currentChartMeta.color }}
                    />
                  </LineChart>
                </ResponsiveContainer>
              </div>
            </section>

            <section
              className={glassCardClassName}
              style={{
                ...glassCardStyle,
                padding: 24,
                display: 'grid',
                gap: 16,
              }}
            >
              <div style={{ display: 'grid', gap: 6 }}>
                <h2 style={{ margin: 0, fontSize: '1.15rem' }}>{TEXT.sections.thoughts}</h2>
                <p style={{ margin: 0, color: '#9fb0c6', lineHeight: 1.6 }}>
                  Автообновляемый поток логов от бэкенда. Кнопка «Запросить решение» удалена.
                </p>
              </div>

              <div
                ref={thoughtsRef}
                className={glassCardClassName}
                style={{
                  ...glassCardStyle,
                  padding: 16,
                  maxHeight: 320,
                  overflowY: 'auto',
                  background: 'rgba(7, 10, 22, 0.58)',
                }}
              >
                {thoughtLines.length === 0 ? (
                  <div
                    className="font-mono text-sm text-green-400"
                    style={{
                      fontFamily: 'Consolas, Menlo, Monaco, monospace',
                      fontSize: 14,
                      color: '#4ade80',
                    }}
                  >
                    {TEXT.status.noThoughts}
                  </div>
                ) : (
                  <div style={{ display: 'grid', gap: 10 }}>
                    {thoughtLines.map((line, index) => (
                      <div
                        key={`${index}-${line}`}
                        className="font-mono text-sm text-green-400"
                        style={{
                          fontFamily: 'Consolas, Menlo, Monaco, monospace',
                          fontSize: 14,
                          color: '#4ade80',
                          lineHeight: 1.6,
                          whiteSpace: 'pre-wrap',
                          wordBreak: 'break-word',
                        }}
                      >
                        {line}
                      </div>
                    ))}
                  </div>
                )}
              </div>
            </section>
          </>
        ) : (
          <>
            <section style={{ display: 'grid', gap: 16 }}>
              <h2 style={{ margin: 0, fontSize: '1.15rem' }}>{TEXT.sections.control}</h2>

              <div
                style={{
                  display: 'grid',
                  gridTemplateColumns: 'repeat(auto-fit, minmax(260px, 1fr))',
                  gap: 20,
                }}
              >
                <DeviceCard
                  title={TEXT.devices.pump}
                  deviceType="pump"
                  timerValue={timerValues.pump}
                  onTimerChange={(value) => setTimerValue('pump', value)}
                  onSendCommand={sendCommand}
                />
                <DeviceCard
                  title={TEXT.devices.light}
                  deviceType="light"
                  timerValue={timerValues.light}
                  onTimerChange={(value) => setTimerValue('light', value)}
                  onSendCommand={sendCommand}
                />
                <DeviceCard
                  title={TEXT.devices.fan}
                  deviceType="fan"
                  timerValue={timerValues.fan}
                  onTimerChange={(value) => setTimerValue('fan', value)}
                  onSendCommand={sendCommand}
                />
              </div>
            </section>

            <section
              className={glassCardClassName}
              style={{
                ...glassCardStyle,
                padding: 24,
                display: 'grid',
                gap: 16,
              }}
            >
              <div style={{ display: 'grid', gap: 6 }}>
                <h2 style={{ margin: 0, fontSize: '1.15rem' }}>{TEXT.sections.simulation}</h2>
                <p style={{ margin: 0, color: '#9fb0c6', lineHeight: 1.6 }}>
                  Быстрые тестовые переключатели режима симулятора через MQTT.
                </p>
              </div>

              <div
                style={{
                  display: 'grid',
                  gridTemplateColumns: 'repeat(auto-fit, minmax(220px, 1fr))',
                  gap: 12,
                }}
              >
                <button type="button" style={panelButtonStyle} onClick={() => publishSimulationMode('HEAT')}>
                  {TEXT.actions.heat}
                </button>
                <button type="button" style={panelButtonStyle} onClick={() => publishSimulationMode('COLD')}>
                  {TEXT.actions.cold}
                </button>
                <button type="button" style={panelButtonStyle} onClick={() => publishSimulationMode('NORMAL')}>
                  {TEXT.actions.normal}
                </button>
              </div>
            </section>
          </>
        )}
      </div>
    </main>
  )
}

export default App

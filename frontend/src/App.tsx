import { type KeyboardEvent, useEffect, useRef, useState } from 'react'
import mqtt, { type MqttClient } from 'mqtt'

const IS_LOCAL =
  window.location.hostname === 'localhost' || window.location.hostname === '127.0.0.1'
const MQTT_WS_URL = 'ws://31.56.208.196:9001'
const API_BASE_URL = IS_LOCAL ? 'http://127.0.0.1:8000/api' : 'http://31.56.208.196:8000/api'
const DEVICE_CONTROL_URL = `${API_BASE_URL}/device/control`
const AI_DECIDE_URL = `${API_BASE_URL}/ai/decide`
const AI_LOGS_URL = `${API_BASE_URL}/logs?limit=20`
const CHAT_URL = `${API_BASE_URL}/chat`
const SENSORS_TOPIC = 'farm/tray_1/sensors/#'

const TEXT = {
  emptyValue: '\u2014',
  appName: '\u041d\u0435\u0439\u0440\u043e\u0430\u0433\u0440\u043e\u043d\u043e\u043c',
  dashboardTitle: '\u041f\u0430\u043d\u0435\u043b\u044c \u0443\u043f\u0440\u0430\u0432\u043b\u0435\u043d\u0438\u044f \u0433\u043e\u0440\u043e\u0434\u0441\u043a\u043e\u0439 \u0444\u0435\u0440\u043c\u043e\u0439',
  dashboardSubtitle:
    '\u041c\u043e\u043d\u0438\u0442\u043e\u0440\u0438\u043d\u0433 \u0434\u0430\u0442\u0447\u0438\u043a\u043e\u0432, \u0436\u0443\u0440\u043d\u0430\u043b \u0440\u0435\u0448\u0435\u043d\u0438\u0439 \u0418\u0418 \u0438 \u0440\u0443\u0447\u043d\u043e\u0435 \u0443\u043f\u0440\u0430\u0432\u043b\u0435\u043d\u0438\u0435 \u0438\u0441\u043f\u043e\u043b\u043d\u0438\u0442\u0435\u043b\u044c\u043d\u044b\u043c\u0438 \u0443\u0441\u0442\u0440\u043e\u0439\u0441\u0442\u0432\u0430\u043c\u0438.',
  systemReady: '\u0421\u0438\u0441\u0442\u0435\u043c\u0430 \u0433\u043e\u0442\u043e\u0432\u0430 \u043a \u0443\u043f\u0440\u0430\u0432\u043b\u0435\u043d\u0438\u044e',
  chatIntro:
    '\u041d\u0435\u0439\u0440\u043e\u0433\u043d\u043e\u043c \u043d\u0430 \u0441\u0432\u044f\u0437\u0438. \u0417\u0430\u0434\u0430\u0439\u0442\u0435 \u0432\u043e\u043f\u0440\u043e\u0441 \u043f\u043e \u0441\u043e\u0441\u0442\u043e\u044f\u043d\u0438\u044e \u0444\u0435\u0440\u043c\u044b \u0438\u043b\u0438 \u043f\u043e \u043c\u043e\u0438\u043c \u043f\u0440\u0435\u0434\u044b\u0434\u0443\u0449\u0438\u043c \u0440\u0435\u0448\u0435\u043d\u0438\u044f\u043c.',
  tabs: {
    monitoringAi: '\u041c\u043e\u043d\u0438\u0442\u043e\u0440\u0438\u043d\u0433 \u0438 \u0418\u0418',
    manualControl: '\u0420\u0443\u0447\u043d\u043e\u0435 \u0443\u043f\u0440\u0430\u0432\u043b\u0435\u043d\u0438\u0435',
  },
  sections: {
    sensors: '\u041f\u043e\u043a\u0430\u0437\u0430\u043d\u0438\u044f \u0434\u0430\u0442\u0447\u0438\u043a\u043e\u0432',
    thoughts: '\u041c\u044b\u0441\u043b\u0438 \u041d\u0435\u0439\u0440\u043e\u0433\u043d\u043e\u043c\u0430',
    ask: '\u0421\u043f\u0440\u043e\u0441\u0438\u0442\u044c \u041d\u0435\u0439\u0440\u043e\u0433\u043d\u043e\u043c\u0430',
    manual: '\u0420\u0443\u0447\u043d\u043e\u0435 \u0443\u043f\u0440\u0430\u0432\u043b\u0435\u043d\u0438\u0435',
    simulation: '\u041e\u0442\u043b\u0430\u0434\u043a\u0430 \u0441\u0438\u043c\u0443\u043b\u044f\u0446\u0438\u0438',
  },
  sensorLabels: {
    airTemp: '\u0422\u0435\u043c\u043f\u0435\u0440\u0430\u0442\u0443\u0440\u0430 \u0432\u043e\u0437\u0434\u0443\u0445\u0430',
    humidity: '\u0412\u043b\u0430\u0436\u043d\u043e\u0441\u0442\u044c \u0432\u043e\u0437\u0434\u0443\u0445\u0430',
    waterTemp: '\u0422\u0435\u043c\u043f\u0435\u0440\u0430\u0442\u0443\u0440\u0430 \u0432\u043e\u0434\u044b',
  },
  deviceTitles: {
    pump: '\u041d\u0430\u0441\u043e\u0441',
    light: '\u0421\u0432\u0435\u0442',
    fan: '\u0412\u0435\u043d\u0442\u0438\u043b\u044f\u0442\u043e\u0440',
  },
  deviceActions: {
    on: '\u0412\u043a\u043b\u044e\u0447\u0438\u0442\u044c',
    off: '\u0412\u044b\u043a\u043b\u044e\u0447\u0438\u0442\u044c',
    timed: '\u0412\u043a\u043b\u044e\u0447\u0438\u0442\u044c \u043d\u0430 \u0432\u0440\u0435\u043c\u044f',
  },
  terminal: {
    title: '\u0422\u0435\u0440\u043c\u0438\u043d\u0430\u043b \u0440\u0435\u0448\u0435\u043d\u0438\u0439',
    subtitle:
      '\u041f\u043e\u0441\u043b\u0435\u0434\u043d\u0438\u0435 \u0440\u0435\u0448\u0435\u043d\u0438\u044f \u041d\u0435\u0439\u0440\u043e\u0433\u043d\u043e\u043c\u0430 \u0437\u0430\u0433\u0440\u0443\u0436\u0430\u044e\u0442\u0441\u044f \u0430\u0432\u0442\u043e\u043c\u0430\u0442\u0438\u0447\u0435\u0441\u043a\u0438 \u043a\u0430\u0436\u0434\u044b\u0435 15 \u0441\u0435\u043a\u0443\u043d\u0434.',
    askNow: '\u0417\u0430\u043f\u0440\u043e\u0441\u0438\u0442\u044c \u0440\u0435\u0448\u0435\u043d\u0438\u0435 \u0441\u0435\u0439\u0447\u0430\u0441',
    thinking: '\u041d\u0435\u0439\u0440\u043e\u0433\u043d\u043e\u043c \u0434\u0443\u043c\u0430\u0435\u0442...',
    empty: '> \u0416\u0443\u0440\u043d\u0430\u043b \u0440\u0435\u0448\u0435\u043d\u0438\u0439 \u043f\u043e\u043a\u0430 \u043f\u0443\u0441\u0442.',
    thoughtPrefix: '\u041c\u044b\u0441\u043b\u044c',
    noThought: '\u041d\u0435\u0442 \u043f\u043e\u044f\u0441\u043d\u0435\u043d\u0438\u044f.',
    commands: '\u041a\u043e\u043c\u0430\u043d\u0434\u044b',
    noActions: '\u0434\u0435\u0439\u0441\u0442\u0432\u0438\u044f \u043d\u0435 \u0442\u0440\u0435\u0431\u0443\u044e\u0442\u0441\u044f',
    analyzing: '\u041d\u0435\u0439\u0440\u043e\u0433\u043d\u043e\u043c \u0430\u043d\u0430\u043b\u0438\u0437\u0438\u0440\u0443\u0435\u0442 \u0434\u0430\u043d\u043d\u044b\u0435...',
  },
  chat: {
    askPlaceholder:
      '\u041d\u0430\u043f\u0440\u0438\u043c\u0435\u0440: \u041f\u043e\u0447\u0435\u043c\u0443 \u0442\u044b \u043d\u0438\u0447\u0435\u0433\u043e \u043d\u0435 \u0432\u043a\u043b\u044e\u0447\u0438\u043b?',
    you: '\u0412\u044b',
    assistant: '\u041d\u0435\u0439\u0440\u043e\u0433\u043d\u043e\u043c',
    sendAria: '\u041e\u0442\u043f\u0440\u0430\u0432\u0438\u0442\u044c \u0441\u043e\u043e\u0431\u0449\u0435\u043d\u0438\u0435',
    sendIcon: '\u2192',
  },
  simulation: {
    description:
      '\u041f\u0430\u043d\u0435\u043b\u044c \u0434\u043b\u044f \u043f\u0435\u0440\u0435\u043a\u043b\u044e\u0447\u0435\u043d\u0438\u044f \u0442\u0435\u0441\u0442\u043e\u0432\u044b\u0445 \u0440\u0435\u0436\u0438\u043c\u043e\u0432 ESP32-\u0441\u0438\u043c\u0443\u043b\u044f\u0442\u043e\u0440\u0430 \u0447\u0435\u0440\u0435\u0437 MQTT.',
    heat: '\u0418\u043c\u0438\u0442\u0438\u0440\u043e\u0432\u0430\u0442\u044c \u0436\u0430\u0440\u0443',
    cold: '\u0418\u043c\u0438\u0442\u0438\u0440\u043e\u0432\u0430\u0442\u044c \u0445\u043e\u043b\u043e\u0434',
    normal: '\u0412\u0435\u0440\u043d\u0443\u0442\u044c \u0432 \u043d\u043e\u0440\u043c\u0443',
  },
  statuses: {
    loadingLogs: '\u041d\u0435 \u0443\u0434\u0430\u043b\u043e\u0441\u044c \u0437\u0430\u0433\u0440\u0443\u0437\u0438\u0442\u044c \u0436\u0443\u0440\u043d\u0430\u043b \u041d\u0435\u0439\u0440\u043e\u0433\u043d\u043e\u043c\u0430',
    mqttMessage: '\u041d\u0435 \u0443\u0434\u0430\u043b\u043e\u0441\u044c \u043e\u0431\u0440\u0430\u0431\u043e\u0442\u0430\u0442\u044c MQTT-\u0441\u043e\u043e\u0431\u0449\u0435\u043d\u0438\u0435',
    mqttError: '\u041e\u0448\u0438\u0431\u043a\u0430 MQTT-\u043f\u043e\u0434\u043a\u043b\u044e\u0447\u0435\u043d\u0438\u044f',
    sendCommand: '\u041e\u0442\u043f\u0440\u0430\u0432\u043a\u0430 \u043a\u043e\u043c\u0430\u043d\u0434\u044b',
    sentCommand: '\u041a\u043e\u043c\u0430\u043d\u0434\u0430',
    commandError: '\u041e\u0448\u0438\u0431\u043a\u0430 \u043e\u0442\u043f\u0440\u0430\u0432\u043a\u0438 \u043a\u043e\u043c\u0430\u043d\u0434\u044b',
    deviceSuffix: '\u0434\u043b\u044f \u0443\u0441\u0442\u0440\u043e\u0439\u0441\u0442\u0432\u0430',
    sendCommandLog: '\u041d\u0435 \u0443\u0434\u0430\u043b\u043e\u0441\u044c \u043e\u0442\u043f\u0440\u0430\u0432\u0438\u0442\u044c \u043a\u043e\u043c\u0430\u043d\u0434\u0443 \u0443\u0441\u0442\u0440\u043e\u0439\u0441\u0442\u0432\u0443',
    aiDecisionLog: '\u041d\u0435 \u0443\u0434\u0430\u043b\u043e\u0441\u044c \u0437\u0430\u043f\u0440\u043e\u0441\u0438\u0442\u044c \u0440\u0435\u0448\u0435\u043d\u0438\u0435 \u041d\u0435\u0439\u0440\u043e\u0433\u043d\u043e\u043c\u0430',
    aiDecisionPrefix: '\u041d\u0435\u0439\u0440\u043e\u0433\u043d\u043e\u043c \u043f\u0440\u0438\u043d\u044f\u043b \u0440\u0435\u0448\u0435\u043d\u0438\u0435',
    aiDecisionFallback: '\u041d\u0435\u0439\u0440\u043e\u0433\u043d\u043e\u043c \u0432\u044b\u043f\u043e\u043b\u043d\u0438\u043b \u0437\u0430\u043f\u0440\u043e\u0441 \u0431\u0435\u0437 \u043f\u043e\u044f\u0441\u043d\u0435\u043d\u0438\u044f.',
    aiDecisionError: '\u041e\u0448\u0438\u0431\u043a\u0430 \u0437\u0430\u043f\u0440\u043e\u0441\u0430 \u0440\u0435\u0448\u0435\u043d\u0438\u044f \u041d\u0435\u0439\u0440\u043e\u0433\u043d\u043e\u043c\u0430',
    chatFallback: '\u041d\u0435\u0439\u0440\u043e\u0433\u043d\u043e\u043c \u043d\u0435 \u0441\u043c\u043e\u0433 \u0441\u0444\u043e\u0440\u043c\u0438\u0440\u043e\u0432\u0430\u0442\u044c \u043e\u0442\u0432\u0435\u0442.',
    chatError: '\u041e\u0448\u0438\u0431\u043a\u0430 \u0441\u0432\u044f\u0437\u0438 \u0441 \u041d\u0435\u0439\u0440\u043e\u0433\u043d\u043e\u043c\u043e\u043c',
    simulationUnavailable:
      '\u041e\u0448\u0438\u0431\u043a\u0430: MQTT-\u0441\u043e\u0435\u0434\u0438\u043d\u0435\u043d\u0438\u0435 \u043d\u0435\u0434\u043e\u0441\u0442\u0443\u043f\u043d\u043e \u0434\u043b\u044f \u043e\u0442\u043b\u0430\u0434\u043a\u0438 \u0441\u0438\u043c\u0443\u043b\u044f\u0446\u0438\u0438',
    simulationSent: '\u041a\u043e\u043c\u0430\u043d\u0434\u0430 \u043e\u0442\u043b\u0430\u0434\u043a\u0438 \u043e\u0442\u043f\u0440\u0430\u0432\u043b\u0435\u043d\u0430',
    modeLabels: {
      HEAT: '\u0436\u0430\u0440\u0430',
      COLD: '\u0445\u043e\u043b\u043e\u0434',
      NORMAL: '\u043d\u043e\u0440\u043c\u0430\u043b\u044c\u043d\u044b\u0439 \u0440\u0435\u0436\u0438\u043c',
    },
  },
} as const

type CommandState = 'ON' | 'OFF' | 'TIMER'
type ActiveTab = 'monitoring-ai' | 'manual-control'
type DeviceType = 'pump' | 'light' | 'fan'

type ClimateData = {
  air_temp: number
  humidity: number
}

type WaterData = {
  water_temp: number
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

type ChatMessage = {
  role: 'user' | 'assistant'
  text: string
}

type AiDecisionResponse = {
  logs?: string[]
  thought?: string
  commands?: AiCommand[]
}

type ChatResponse = {
  reply?: string
}

type DeviceCardProps = {
  title: string
  deviceType: DeviceType
  timerValue: string
  onTimerChange: (value: string) => void
  onCommand: (deviceType: DeviceType, state: CommandState, duration?: number) => void
}

function metricValue(value: number | null, unit: string) {
  return value === null ? TEXT.emptyValue : `${value} ${unit}`
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
  const deviceTitle: Record<DeviceType, string> = {
    pump: TEXT.deviceTitles.pump,
    light: TEXT.deviceTitles.light,
    fan: TEXT.deviceTitles.fan,
  }

  if (command.state === 'TIMER' && typeof command.duration === 'number') {
    return `${deviceTitle[command.device_type]}: TIMER ${command.duration} \u0441\u0435\u043a.`
  }

  return `${deviceTitle[command.device_type]}: ${command.state}`
}

function DeviceCard({
  title,
  deviceType,
  timerValue,
  onTimerChange,
  onCommand,
}: DeviceCardProps) {
  const handleTimerStart = () => {
    const duration = Number(timerValue)

    if (!Number.isFinite(duration) || duration <= 0) {
      return
    }

    onCommand(deviceType, 'TIMER', duration)
  }

  return (
    <article className="device-card">
      <div className="device-card__header">
        <h3>{title}</h3>
        <span className="device-card__type">{deviceType}</span>
      </div>

      <div className="device-card__actions">
        <button
          className="control-button control-button--primary"
          onClick={() => onCommand(deviceType, 'ON')}
        >
          {TEXT.deviceActions.on}
        </button>
        <button
          className="control-button control-button--secondary"
          onClick={() => onCommand(deviceType, 'OFF')}
        >
          {TEXT.deviceActions.off}
        </button>
      </div>

      <div className="timer-control">
        <input
          className="timer-control__input"
          type="number"
          step="1"
          min="1"
          value={timerValue}
          onChange={(event) => onTimerChange(event.target.value)}
          placeholder="5"
        />
        <button className="timer-control__button" onClick={handleTimerStart}>
          {TEXT.deviceActions.timed}
        </button>
      </div>
    </article>
  )
}

function App() {
  const [activeTab, setActiveTab] = useState<ActiveTab>('monitoring-ai')
  const [climateData, setClimateData] = useState<ClimateData | null>(null)
  const [waterData, setWaterData] = useState<WaterData | null>(null)
  const [requestState, setRequestState] = useState<string>(TEXT.systemReady)
  const [aiLogs, setAiLogs] = useState<AiLog[]>([])
  const [isAiThinking, setIsAiThinking] = useState(false)
  const [chatMessages, setChatMessages] = useState<ChatMessage[]>([
    {
      role: 'assistant',
      text: TEXT.chatIntro,
    },
  ])
  const [chatInput, setChatInput] = useState('')
  const [isChatLoading, setIsChatLoading] = useState(false)
  const [timerValues, setTimerValues] = useState<Record<DeviceType, string>>({
    light: '5',
    fan: '5',
    pump: '5',
  })
  const terminalRef = useRef<HTMLDivElement | null>(null)
  const messagesEndRef = useRef<HTMLDivElement>(null)
  const mqttClientRef = useRef<MqttClient | null>(null)

  const loadAiLogs = async () => {
    try {
      const response = await fetch(AI_LOGS_URL)
      if (!response.ok) {
        throw new Error(`HTTP ${response.status}`)
      }

      const data = (await response.json()) as AiLog[]
      const normalizedLogs = Array.isArray(data) ? [...data].reverse() : []
      setAiLogs(normalizedLogs)
    } catch (error) {
      console.error(TEXT.statuses.loadingLogs, error)
    }
  }

  useEffect(() => {
    const client = mqtt.connect(MQTT_WS_URL)
    mqttClientRef.current = client

    const onMessageArrived = (topic: string, message: Buffer<ArrayBufferLike>) => {
      try {
        const data = JSON.parse(message.toString()) as ClimateData | WaterData

        if (topic.endsWith('/climate')) {
          setClimateData(data as ClimateData)
        } else if (topic.endsWith('/water')) {
          setWaterData(data as WaterData)
        }
      } catch (error) {
        console.error(TEXT.statuses.mqttMessage, error)
      }
    }

    client.on('connect', () => {
      client.subscribe(SENSORS_TOPIC)
    })

    client.on('message', onMessageArrived)
    client.on('error', (error) => {
      console.error(TEXT.statuses.mqttError, error)
    })

    return () => {
      mqttClientRef.current = null
      client.end(true)
    }
  }, [])

  useEffect(() => {
    const handleBodyClick = (event: MouseEvent) => {
      const target = event.target

      if (!(target instanceof HTMLElement)) {
        return
      }

      if (target.closest('button, input, textarea')) {
        return
      }

      const leavesCount = Math.floor(Math.random() * 2) + 3

      for (let index = 0; index < leavesCount; index += 1) {
        const leaf = document.createElement('div')
        const size = 10 + Math.random() * 10
        const offsetX = (Math.random() - 0.5) * 36
        const duration = 1600 + Math.random() * 900
        const drift = `${(Math.random() - 0.5) * 90}px`
        const rotation = `${(Math.random() - 0.5) * 120}deg`

        leaf.className = 'leaf'
        leaf.style.left = `${event.clientX + offsetX}px`
        leaf.style.top = `${event.clientY - 8}px`
        leaf.style.width = `${size}px`
        leaf.style.height = `${size * 0.72}px`
        leaf.style.setProperty('--leaf-drift', drift)
        leaf.style.setProperty('--leaf-rotate', rotation)
        leaf.style.setProperty('--leaf-duration', `${duration}ms`)

        leaf.addEventListener('animationend', () => {
          leaf.remove()
        })

        document.body.appendChild(leaf)
      }
    }

    document.body.addEventListener('click', handleBodyClick)

    return () => {
      document.body.removeEventListener('click', handleBodyClick)
      document.querySelectorAll('.leaf').forEach((leaf) => leaf.remove())
    }
  }, [])

  useEffect(() => {
    void loadAiLogs()

    const intervalId = window.setInterval(() => {
      void loadAiLogs()
    }, 15000)

    return () => {
      window.clearInterval(intervalId)
    }
  }, [])

  useEffect(() => {
    if (!terminalRef.current) {
      return
    }

    terminalRef.current.scrollTop = terminalRef.current.scrollHeight
  }, [aiLogs, isAiThinking])

  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [chatMessages])

  const sendCommand = async (deviceType: DeviceType, state: CommandState, duration?: number) => {
    setRequestState(`${TEXT.statuses.sendCommand} ${state} ${TEXT.statuses.deviceSuffix} ${deviceType}`)

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
          ...(state === 'TIMER' && duration !== undefined
            ? { duration: Number(duration) }
            : {}),
        }),
      })

      if (!response.ok) {
        throw new Error(`HTTP ${response.status}`)
      }

      setRequestState(`${TEXT.statuses.sentCommand} ${state} ${TEXT.statuses.deviceSuffix} ${deviceType} \u043e\u0442\u043f\u0440\u0430\u0432\u043b\u0435\u043d\u0430`)
    } catch (error) {
      console.error(TEXT.statuses.sendCommandLog, error)
      setRequestState(`${TEXT.statuses.commandError} ${state} ${TEXT.statuses.deviceSuffix} ${deviceType}`)
    }
  }

  const requestAiDecision = async () => {
    setIsAiThinking(true)

    try {
      const response = await fetch(AI_DECIDE_URL, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
        },
      })

      if (!response.ok) {
        throw new Error(`HTTP ${response.status}`)
      }

      const data = (await response.json()) as AiDecisionResponse
      const summary =
        data.thought && data.thought.length > 0
          ? `${TEXT.statuses.aiDecisionPrefix}: ${data.thought}`
          : TEXT.statuses.aiDecisionFallback
      setRequestState(summary)
      await loadAiLogs()
    } catch (error) {
      console.error(TEXT.statuses.aiDecisionLog, error)
      const message = error instanceof Error ? error.message : String(error)
      setRequestState(`${TEXT.statuses.aiDecisionError}: ${message}`)
    } finally {
      setIsAiThinking(false)
    }
  }

  const askChatQuestion = async (message: string) => {
    const trimmedMessage = message.trim()
    if (!trimmedMessage) {
      return
    }

    setChatMessages((current) => [...current, { role: 'user', text: trimmedMessage }])
    setChatInput('')
    setIsChatLoading(true)

    try {
      const response = await fetch(CHAT_URL, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
        },
        body: JSON.stringify({ message: trimmedMessage }),
      })

      if (!response.ok) {
        throw new Error(`HTTP ${response.status}`)
      }

      const data = (await response.json()) as ChatResponse
      const reply = data.reply?.trim() || TEXT.statuses.chatFallback
      setChatMessages((current) => [...current, { role: 'assistant', text: reply }])
    } catch (error) {
      const messageText = error instanceof Error ? error.message : String(error)
      setChatMessages((current) => [
        ...current,
        { role: 'assistant', text: `${TEXT.statuses.chatError}: ${messageText}` },
      ])
    } finally {
      setIsChatLoading(false)
    }
  }

  const setTimerValue = (deviceType: DeviceType, value: string) => {
    setTimerValues((current) => ({
      ...current,
      [deviceType]: value,
    }))
  }

  const handleChatInputKeyDown = (event: KeyboardEvent<HTMLInputElement>) => {
    if (event.key !== 'Enter' || event.shiftKey) {
      return
    }

    event.preventDefault()
    void askChatQuestion(chatInput)
  }

  const publishSimulationMode = (mode: 'HEAT' | 'COLD' | 'NORMAL') => {
    const client = mqttClientRef.current

    if (!client || !client.connected) {
      setRequestState(TEXT.statuses.simulationUnavailable)
      return
    }

    client.publish('farm/sim/control', mode)

    setRequestState(`${TEXT.statuses.simulationSent}: ${TEXT.statuses.modeLabels[mode]}`)
  }

  return (
    <main className="dashboard">
      <section className="dashboard__shell">
        <header className="dashboard__header">
          <p className="dashboard__eyebrow">{TEXT.appName}</p>
          <h1>{TEXT.dashboardTitle}</h1>
          <p className="dashboard__subtitle">{TEXT.dashboardSubtitle}</p>
        </header>

        <section className="dashboard__section dashboard__section--compact">
          <div className="dashboard__tabs">
            <button
              type="button"
              className={`control-button control-button--tab${
                activeTab === 'monitoring-ai' ? ' control-button--tab-active' : ''
              }`}
              onClick={() => setActiveTab('monitoring-ai')}
            >
              {TEXT.tabs.monitoringAi}
            </button>
            <button
              type="button"
              className={`control-button control-button--tab${
                activeTab === 'manual-control' ? ' control-button--tab-active' : ''
              }`}
              onClick={() => setActiveTab('manual-control')}
            >
              {TEXT.tabs.manualControl}
            </button>
          </div>
        </section>

        {activeTab === 'monitoring-ai' ? (
          <>
            <section className="dashboard__section">
              <div className="section-heading">
                <h2>{TEXT.sections.sensors}</h2>
              </div>

              <div className="telemetry-grid telemetry-grid--metrics">
                <article className="sensor-card">
                  <h3>{TEXT.sensorLabels.airTemp}</h3>
                  <p className="sensor-card__metric">{metricValue(climateData?.air_temp ?? null, '\u00B0C')}</p>
                </article>

                <article className="sensor-card">
                  <h3>{TEXT.sensorLabels.humidity}</h3>
                  <p className="sensor-card__metric">{metricValue(climateData?.humidity ?? null, '%')}</p>
                </article>

                <article className="sensor-card">
                  <h3>{TEXT.sensorLabels.waterTemp}</h3>
                  <p className="sensor-card__metric">{metricValue(waterData?.water_temp ?? null, '\u00B0C')}</p>
                </article>
              </div>
            </section>

            <section className="dashboard__section">
              <div className="section-heading">
                <h2>{TEXT.sections.thoughts}</h2>
              </div>

              <div className="sensor-card sensor-card--terminal">
                <div className="panel-header">
                  <div className="panel-copy">
                    <h3 className="panel-title">{TEXT.terminal.title}</h3>
                    <p className="panel-subtitle">{TEXT.terminal.subtitle}</p>
                  </div>

                  <button
                    type="button"
                    className="control-button control-button--primary control-button--wide"
                    onClick={requestAiDecision}
                    disabled={isAiThinking}
                  >
                    {isAiThinking ? TEXT.terminal.thinking : TEXT.terminal.askNow}
                  </button>
                </div>

                <div ref={terminalRef} className="terminal-window">
                  {aiLogs.length === 0 ? (
                    <div className="terminal-window__empty">{TEXT.terminal.empty}</div>
                  ) : null}

                  {aiLogs.map((log) => {
                    const commands = parseCommands(log.commands_json)
                    return (
                      <div key={log.id} className="terminal-log">
                        <div className="terminal-log__timestamp">&gt; [{log.timestamp}]</div>
                        <div>
                          {TEXT.terminal.thoughtPrefix}: {log.thought || TEXT.terminal.noThought}
                        </div>
                        <div>
                          {TEXT.terminal.commands}:{' '}
                          {commands.length > 0
                            ? commands.map((command) => formatCommand(command)).join(' | ')
                            : TEXT.terminal.noActions}
                        </div>
                      </div>
                    )
                  })}

                  {isAiThinking ? (
                    <div className="terminal-status">
                      <span className="terminal-status__dot" />
                      <span>{TEXT.terminal.analyzing}</span>
                    </div>
                  ) : null}
                </div>
              </div>
            </section>

            <section className="dashboard__section">
              <div className="section-heading">
                <h2>{TEXT.sections.ask}</h2>
              </div>

              <div className="sensor-card sensor-card--chat">
                <div className="chat-thread">
                  {chatMessages.map((message, index) => (
                    <div
                      key={`${message.role}-${index}`}
                      className={`chat-bubble ${
                        message.role === 'user' ? 'chat-bubble--user' : 'chat-bubble--assistant'
                      }`}
                    >
                      <strong className="chat-bubble__author">
                        {message.role === 'user' ? TEXT.chat.you : TEXT.chat.assistant}
                      </strong>
                      <span>{message.text}</span>
                    </div>
                  ))}
                  <div ref={messagesEndRef} />
                </div>

                <div className="chat-compose">
                  <input
                    className="glass-input"
                    value={chatInput}
                    onChange={(event) => setChatInput(event.target.value)}
                    onKeyDown={handleChatInputKeyDown}
                    placeholder={TEXT.chat.askPlaceholder}
                  />
                  <button
                    type="button"
                    className="control-button control-button--primary control-button--icon"
                    onClick={() => void askChatQuestion(chatInput)}
                    disabled={isChatLoading}
                    aria-label={TEXT.chat.sendAria}
                  >
                    {isChatLoading ? '...' : TEXT.chat.sendIcon}
                  </button>
                </div>
              </div>
            </section>
          </>
        ) : (
          <>
            <section className="dashboard__section">
              <div className="section-heading">
                <h2>{TEXT.sections.manual}</h2>
              </div>

              <div className="devices-grid">
                <DeviceCard
                  title={TEXT.deviceTitles.pump}
                  deviceType="pump"
                  timerValue={timerValues.pump}
                  onTimerChange={(value) => setTimerValue('pump', value)}
                  onCommand={sendCommand}
                />
                <DeviceCard
                  title={TEXT.deviceTitles.light}
                  deviceType="light"
                  timerValue={timerValues.light}
                  onTimerChange={(value) => setTimerValue('light', value)}
                  onCommand={sendCommand}
                />
                <DeviceCard
                  title={TEXT.deviceTitles.fan}
                  deviceType="fan"
                  timerValue={timerValues.fan}
                  onTimerChange={(value) => setTimerValue('fan', value)}
                  onCommand={sendCommand}
                />
              </div>
            </section>

            <section className="dashboard__section">
              <div className="section-heading">
                <h2>{TEXT.sections.simulation}</h2>
              </div>

              <div className="sensor-card sensor-card--warm">
                <p className="sensor-card__description sensor-card__description--warm">
                  {TEXT.simulation.description}
                </p>

                <div className="button-row">
                  <button
                    type="button"
                    className="control-button control-button--warm"
                    onClick={() => publishSimulationMode('HEAT')}
                  >
                    {TEXT.simulation.heat}
                  </button>

                  <button
                    type="button"
                    className="control-button control-button--cool"
                    onClick={() => publishSimulationMode('COLD')}
                  >
                    {TEXT.simulation.cold}
                  </button>

                  <button
                    type="button"
                    className="control-button control-button--success"
                    onClick={() => publishSimulationMode('NORMAL')}
                  >
                    {TEXT.simulation.normal}
                  </button>
                </div>
              </div>
            </section>
          </>
        )}

        <footer className="dashboard__footer">{requestState}</footer>
      </section>
    </main>
  )
}

export default App

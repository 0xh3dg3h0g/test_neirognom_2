import { useEffect, useState } from 'react'
import mqtt from 'mqtt'

const SENSOR_TOPIC = 'farm/tray_1/sensors'
const API_URL = 'http://127.0.0.1:8000/api/device/control'

function App() {
  const [temperature, setTemperature] = useState('Ожидание данных...')
  const [requestState, setRequestState] = useState('Готово к управлению вентилятором')

  useEffect(() => {
    const client = mqtt.connect('ws://localhost:9001')

    client.on('connect', () => {
      client.subscribe(SENSOR_TOPIC)
    })

    client.on('message', (topic, message) => {
      if (topic !== SENSOR_TOPIC) {
        return
      }

      try {
        const data = JSON.parse(message.toString()) as { temperature?: number }

        if (typeof data.temperature === 'number') {
          setTemperature(`Температура: ${data.temperature} °C`)
        }
      } catch (error) {
        console.error('Не удалось обработать MQTT-сообщение', error)
      }
    })

    client.on('error', (error) => {
      console.error('Ошибка MQTT-подключения', error)
    })

    return () => {
      client.end(true)
    }
  }, [])

  const sendFanCommand = async (state: 'ON' | 'OFF') => {
    setRequestState(`Отправка команды ${state}...`)

    try {
      const response = await fetch(API_URL, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
        },
        body: JSON.stringify({
          target_id: 'tray_1',
          device_type: 'fan',
          state,
        }),
      })

      if (!response.ok) {
        throw new Error(`HTTP ${response.status}`)
      }

      setRequestState(`Команда ${state} отправлена`)
    } catch (error) {
      console.error('Не удалось отправить команду вентилятору', error)
      setRequestState(`Ошибка отправки команды ${state}`)
    }
  }

  return (
    <main className="dashboard">
      <section className="dashboard__panel">
        <p className="dashboard__eyebrow">IoT Dashboard</p>
        <h1>Панель управления Neuroagronom</h1>
        <div className="dashboard__temperature">{temperature}</div>

        <div
          style={{
            display: 'grid',
            gap: '14px',
          }}
        >
          <button
            className="dashboard__button"
            style={{
              background: 'linear-gradient(135deg, #1d6f42 0%, #2f8f73 100%)',
              boxShadow: '0 18px 30px rgba(29, 111, 66, 0.28)',
            }}
            onClick={() => sendFanCommand('ON')}
          >
            Включить вентилятор (ON)
          </button>

          <button
            className="dashboard__button"
            style={{
              background: 'linear-gradient(135deg, #a72d2d 0%, #d94e4e 100%)',
              boxShadow: '0 18px 30px rgba(167, 45, 45, 0.26)',
            }}
            onClick={() => sendFanCommand('OFF')}
          >
            Выключить вентилятор (OFF)
          </button>
        </div>

        <p className="dashboard__status">{requestState}</p>
      </section>
    </main>
  )
}

export default App

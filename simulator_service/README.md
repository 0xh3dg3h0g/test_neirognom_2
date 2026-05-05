# Neurognome MQTT Simulator Service

Standalone web simulator for the firmware MQTT contract.

## Run

```powershell
venv\Scripts\activate
python -m uvicorn simulator_service.main:app --reload --host 0.0.0.0 --port 8090
```

Then open:

```text
http://localhost:8090/
```

Or use:

```powershell
start_simulator_service.bat
```

## Runtime MQTT Settings

Broker settings are changed from the web panel without restarting the service:

- host
- port
- username
- password
- client id
- target id, for example `tray_1`
- TLS on/off

The service subscribes to:

```text
farm/+/cmd/#
farm/+/status/#
farm/+/sensors/#
farm/sim/#
```

It publishes firmware-compatible messages:

```text
farm/{target_id}/sensors/climate
farm/{target_id}/sensors/water
farm/{target_id}/status/devices
farm/{target_id}/status/availability
```

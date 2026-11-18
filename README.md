# PolluSense Raspberry Pi (RPi) Software & Services

This directory contains all the backend services, dynamic calibration logic, 15-minute rolling mean aggregator, Mosquitto broker configurations, and systemd automation timers for the Raspberry Pi.

---

## Directory Structure

```
rpi/
├── README.md                          # This manual
├── install.sh                         # One-click deployment script
├── config/
│   ├── hardware.json                  # Load resistor values (RL) for MQ-135 & MQ-7
│   ├── calibration.json               # Baseline R0, curve slopes, intercepts (b = -1.6500)
│   └── pollusense.conf                # Mosquitto listener configuration (Port 1883)
├── scripts/
│   ├── ingest.py                      # Background MQTT consumer saving raw packets to data.db
│   ├── calibrate.py                   # Math engine (divider compensation, Rs, T/RH, ppm -> CPCB)
│   ├── aggregate.py                   # 15-minute basic mean aggregator -> records_15min.csv
│   ├── r0.py                          # Clean-air R0 baseline calculation tool (--last1h)
│   ├── live_calibrated.py             # Live terminal monitoring dashboard (DUE!!!) 
│   ├── export_csv.py                  # CSV exporter for raw or 15-minute records over time ranges
│   └── setup_dedicated_access.sh      # mDNS & static IP alias (192.168.1.50) setup script
└── systemd/
    ├── ps-ingest.service              # Ingest service unit
    ├── ps-aggregate.service           # 15-minute aggregation service unit
    ├── ps-aggregate.timer             # Aggregation timer (:01, :16, :31, :46 past every hour)
    └── permanent-ip-alias.service     # Permanent 192.168.1.50 network alias unit
```

---

## Automated Quick Deployment on Raspberry Pi

To deploy everything automatically on the Raspberry Pi:

```bash
# Clone or copy the repository onto the Raspberry Pi:
cd ~/pollusense-repo/rpi
chmod +x install.sh
./install.sh
```

---

## Manual Execution & Diagnostic Tools

All diagnostic and maintenance tools run using the virtual environment at `~/venv`:

### 1. Live Real-Time Dashboard
View incoming 1-minute measurements with on-the-fly calibration and CPCB AQI:
```bash
~/venv/bin/python ~/pollusense/live_calibrated.py
```

### 2. Recalculate Sensor Baselines ($R_0$)
Calculate $R_0$ from clean air over the last hour:
```bash
~/venv/bin/python ~/pollusense/r0.py --last1h
```

Or over a specific UTC time range:
```bash
~/venv/bin/python ~/pollusense/r0.py "2026-11-20 00:00" "2026-11-20 01:00"
```

### 3. Export Data for Research & Analysis
Export 15-minute records for a specific date range:
```bash
~/venv/bin/python ~/pollusense/export_csv.py --start "2026-11-20" --end "2026-11-27" --out weekly_report.csv
```

Export raw 1-minute data for a specific day:
```bash
~/venv/bin/python ~/pollusense/export_csv.py --table raw --start "2026-11-20 00:00:00" --end "2026-11-20 23:59:59" --out raw_day1.csv
```

---

## Reboot & Power Outage Behavior

All vital gateway functions are managed by systemd:
* **`ps-ingest.service`**: Automatically starts on boot. Recovers immediately if the Pi is restarted or power is restored.
* **`ps-aggregate.timer`**: Automatically active across reboots. Because `Persistent=true` is set, any 15-minute window missed during a power outage or reboot is triggered immediately upon startup.
* **`mosquitto.service`**: Starts automatically on boot.
* **`permanent-ip-alias.service`**: Binds `192.168.1.50` on boot for emergency or lab access.

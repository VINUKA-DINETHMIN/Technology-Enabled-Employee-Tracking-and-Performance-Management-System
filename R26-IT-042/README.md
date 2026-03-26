# R26-IT-042 — Employee Activity Monitoring System

A Python desktop application for ethical employee activity monitoring, built with CustomTkinter.

## Project Structure

```
R26-IT-042/
├── main.py                  # Application entry point
├── requirements.txt         # All dependencies
├── setup.bat / setup.sh     # Platform setup scripts
├── build.bat / build.sh     # PyInstaller build scripts
├── .env                     # Environment variables (NOT committed)
├── common/                  # Shared utilities (DB, encryption, logging, alerts)
├── config/                  # App-wide settings
├── C1_user_interaction/     # Component 1: User Interaction Pattern Analysis
├── C2_facial_liveness/      # Component 2: Facial Liveness Detection
├── C3_activity_monitoring/  # Component 3: Activity Monitoring & Anomaly Detection
├── C4_productivity_prediction/ # Component 4: Productivity Prediction
├── dashboard/               # Web dashboard (Flask/FastAPI)
└── assets/                  # App icons and images
```

## Quick Start

### Windows
```bat
setup.bat
```

### Mac / Linux
```bash
chmod +x setup.sh && ./setup.sh
```

## Environment Setup

Copy `.env` and fill in your values:
```
MONGO_URI=mongodb+srv://<user>:<pass>@cluster.mongodb.net/employee_monitor
AES_KEY=<32-byte-hex-key>
WEBSOCKET_URL=ws://localhost:8765
APP_NAME=Employee Monitor
VERSION=1.0.0
```

## Build Standalone Executable

### Windows
```bat
build.bat
```

### Mac
```bash
./build.sh
```

## Team Components

| ID  | Component                     | Owner       |
|-----|-------------------------------|-------------|
| C1  | User Interaction Monitoring   | Team Member 1 |
| C2  | Facial Liveness Detection     | Team Member 2 |
| C3  | Activity Monitoring & Anomaly | Team Member 3 |
| C4  | Productivity Prediction       | Team Member 4 |

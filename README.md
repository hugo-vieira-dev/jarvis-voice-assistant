# 🤖 JARVIS - Interactive AI Desktop Assistant

An interactive, voice-driven desktop assistant for Windows built with Python, featuring real-time speech recognition, custom Digital Signal Processing (DSP) audio pipelines, and a hardware-accelerated video interface.

---

## ✨ Features

- **Voice-to-Voice Interaction:** Real-time speech recognition with automated neural Text-to-Speech (TTS) synthesis.
- **LLM API Integration:** Asynchronous communication with large language models for fast conversational responses.
- **Cinematic Audio Processing:** Custom Digital Signal Processing (DSP) pipeline built with `pedalboard` (pitch shifting, delay, and reverb) to dynamically process synthesized voice output.
- **Full-Screen Video UI:** Frameless `PyQt5` interface with hardware-accelerated video rendering via OpenCV and multithreaded event handling.

---

## 🛠️ Tech Stack

- **Language:** Python 3.13
- **GUI & Video Rendering:** `PyQt5`, `OpenCV`
- **Audio Engineering:** `edge-tts`, `pedalboard`, `pygame`
- **Speech Recognition:** `SpeechRecognition`
- **Architecture:** Multithreading, Asynchronous I/O, REST API Integration

---

## 🚀 Getting Started

### Prerequisites

- Windows OS
- Python 3.13+
- LLM API Key

### Installation

1. Clone the repository:
   ```bash
   git clone [https://github.com/hugo-vieira-dev/jarvis-voice-assistant.git](https://github.com/hugo-vieira-dev/jarvis-voice-assistant.git)
   cd jarvis-voice-assistant
   ```

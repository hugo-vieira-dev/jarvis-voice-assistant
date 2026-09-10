import sys
import asyncio
import os
from dotenv import load_dotenv

load_dotenv()

import cv2
import threading
import pygame
import edge_tts
import anthropic
import speech_recognition as sr
from pedalboard import Pedalboard, Delay, PitchShift, Reverb
from pedalboard.io import AudioFile
from PyQt5.QtWidgets import QApplication, QWidget, QLabel
from PyQt5.QtCore import Qt, QTimer
from PyQt5.QtGui import QImage, QPixmap, QKeyEvent

# --- CONFIGURAÇÕES ---
ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY")
NOME_USUARIO = "Hugo"
VIDEO_AVATAR = "jarvis_avatar.mp4"

try:
    client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
except Exception:
    client = None

pygame.mixer.init()

# --- MOTOR DE ÁUDIO ---
def aplicar_efeito_jarvis(arquivo_entrada, arquivo_saida):
    board = Pedalboard([
        PitchShift(semitones=-1.5),
        Delay(delay_seconds=0.035, feedback=0.2, mix=0.3),
        Reverb(room_size=0.15, wet_level=0.2)
    ])
    
    with AudioFile(arquivo_entrada) as f:
        audio = f.read(f.frames)
        sr_rate = f.samplerate
        
    effected = board(audio, sr_rate)
    
    with AudioFile(arquivo_saida, 'w', sr_rate, effected.shape[0]) as f:
        f.write(effected)

def falar(texto):
    print(f"\nJARVIS: {texto}\n")
    VOICE = "pt-BR-AntonioNeural"
    TEMP_FILE = "temp.mp3"
    FINAL_FILE = "jarvis_voice.wav"
    
    async def _generate():
        communicate = edge_tts.Communicate(texto, VOICE, rate="+0%")
        await communicate.save(TEMP_FILE)
        
    asyncio.run(_generate())
    
    try:
        aplicar_efeito_jarvis(TEMP_FILE, FINAL_FILE)
        play_file = FINAL_FILE
    except Exception:
        play_file = TEMP_FILE

    pygame.mixer.music.load(play_file)
    pygame.mixer.music.play()
    while pygame.mixer.music.get_busy():
        pygame.time.Clock().tick(10)
        
    pygame.mixer.music.unload()
    
    for f in [TEMP_FILE, FINAL_FILE]:
        if os.path.exists(f):
            try: os.remove(f)
            except: pass

# --- INTELIGÊNCIA ---
def obter_resposta_claude(pergunta):
    if not client:
        return "Chave de API não configurada corretamente, senhor."

    prompt_sistema = (
        f"Você é o JARVIS, assistente pessoal de {NOME_USUARIO}. "
        "Responda de forma extremamente útil, direta, elegante e concisa."
    )
    
    try:
        resposta = client.messages.create(
            model="claude-3-5-sonnet-20241022",
            max_tokens=300,
            system=prompt_sistema,
            messages=[{"role": "user", "content": pergunta}]
        )
        return resposta.content[0].text
    except Exception as e:
        return f"Erro no processamento, senhor: {e}"

# --- ESCUTA POR VOZ (MICROFONE) ---
def ouvir_microfone():
    recognizer = sr.Recognizer()
    with sr.Microphone() as source:
        print("Ajustando para o ruído de fundo... Aguarde um segundo.")
        recognizer.adjust_for_ambient_noise(source, duration=1)
        print("Escutando... Fale algo:")
        try:
            audio = recognizer.listen(source, timeout=5, phrase_time_limit=10)
            texto = recognizer.recognize_google(audio, language="pt-BR")
            print(f"Você disse: {texto}")
            return texto
        except sr.WaitTimeoutError:
            return ""
        except sr.UnknownValueError:
            return ""
        except sr.RequestError as e:
            print(f"Erro no serviço de reconhecimento de voz: {e}")
            return ""

def loop_conversacao():
    falar(f"Microfone ativo e inteligência conectada senhor {NOME_USUARIO}.")
    while True:
        try:
            pergunta = ouvir_microfone()
            
            if pergunta:
                if pergunta.lower() in ["sair", "desligar", "fechar", "encerrar"]:
                    falar("Encerrando sistemas. Até logo senhor.")
                    os._exit(0)
                
                resposta = obter_resposta_claude(pergunta)
                falar(resposta)
        except Exception as e:
            print(f"Erro no loop de conversação: {e}")

# --- AVATAR EM VÍDEO ANIMADO (TELA CHEIA) ---
class JarvisVideoAvatar(QWidget):
    def __init__(self):
        super().__init__()
        self.initUI()

    def initUI(self):
        self.setWindowFlags(Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.SubWindow)
        self.setAttribute(Qt.WA_TranslucentBackground)
        
        screen_geometry = QApplication.desktop().screenGeometry()
        width, height = screen_geometry.width(), screen_geometry.height()

        self.label = QLabel(self)
        self.resize(width, height)
        self.label.resize(width, height)
        
        self.cap = cv2.VideoCapture(VIDEO_AVATAR)
        
        self.timer = QTimer(self)
        self.timer.timeout.connect(self.update_frame)
        self.timer.start(33)
        self.showFullScreen()

    def keyPressEvent(self, event: QKeyEvent):
        if event.key() == Qt.Key_Escape:
            falar(f"Encerrando Interface visual senhor {NOME_USUARIO}")
            os._exit(0)

    def update_frame(self):
        ret, frame = self.cap.read()
        if not ret:
            self.cap.set(cv2.CAP_PROP_POS_FRAMES, 0)
            ret, frame = self.cap.read()

        if ret:
            frame = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
            h, w, ch = frame.shape
            bytes_per_line = ch * w
            q_img = QImage(frame.data, w, h, bytes_per_line, QImage.Format_RGB888)
            pixmap = QPixmap.fromImage(q_img)
            self.label.setPixmap(pixmap.scaled(self.width(), self.height(), Qt.IgnoreAspectRatio, Qt.SmoothTransformation))

if __name__ == "__main__":
    app = QApplication(sys.argv)
    avatar = JarvisVideoAvatar()
    
    threading.Thread(target=loop_conversacao, daemon=True).start()
    sys.exit(app.exec_())
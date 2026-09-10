import sys
import asyncio
import os
import traceback
from dotenv import load_dotenv

load_dotenv()

import cv2
import threading
import pygame
import edge_tts
import requests
import time
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
avatar_window = None

URL_API = "https://api.anthropic.com/v1/messages"
HEADERS_API = {
    "x-api-key": ANTHROPIC_API_KEY,
    "anthropic-version": "2023-06-01",
    "content-type": "application/json"
}

pygame.mixer.init()

# --- MOTOR DE ÁUDIO ---
def _ler_audio_com_retentativa(arquivo, tentativas=3, espera=0.1):
    """Abre o arquivo de áudio com pedalboard.io.AudioFile (que decodifica MP3
    nativamente, sem depender do binário do ffmpeg). Faz algumas retentativas
    curtas para cobrir o caso raro em que o arquivo ainda não foi totalmente
    liberado pelo processo que o gravou (edge-tts), o que fazia o AudioFile
    retornar None e o 'with' quebrar com um erro de 'NoneType'."""
    ultimo_erro = None
    for _ in range(tentativas):
        audio_file = AudioFile(arquivo)
        if audio_file is not None:
            with audio_file as f:
                audio = f.read(f.frames)
                sr_rate = f.samplerate
            return audio, sr_rate
        ultimo_erro = RuntimeError(f"Não foi possível abrir o áudio: {arquivo}")
        time.sleep(espera)
    raise ultimo_erro

def aplicar_efeito_jarvis(arquivo_entrada, arquivo_saida):
    board = Pedalboard([
        PitchShift(semitones=-1.5),
        Delay(delay_seconds=0.035, feedback=0.2, mix=0.3),
        Reverb(room_size=0.15, wet_level=0.2)
    ])

    audio, sr_rate = _ler_audio_com_retentativa(arquivo_entrada)
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

    try:
        asyncio.run(_generate())
    except Exception as e:
        print(f"Erro ao gerar áudio: {e}")
        return

    play_file = TEMP_FILE
    try:
        aplicar_efeito_jarvis(TEMP_FILE, FINAL_FILE)
        if os.path.exists(FINAL_FILE):
            play_file = FINAL_FILE
    except Exception as e:
        print(f"Erro no efeito de áudio: {e}")

    try:
        pygame.mixer.music.load(play_file)
        pygame.mixer.music.play()
        while pygame.mixer.music.get_busy():
            pygame.time.Clock().tick(10)
    except Exception as e:
        print(f"Erro ao reproduzir áudio: {e}")
    finally:
        pygame.mixer.music.stop()
        pygame.mixer.music.unload()
        for f in [TEMP_FILE, FINAL_FILE]:
            if os.path.exists(f):
                try:
                    os.remove(f)
                except Exception as e:
                    print(f"Erro ao remover arquivo temporário {f}: {e}")

# --- INTELIGÊNCIA ---
def obter_resposta_claude(pergunta):
    if not HEADERS_API.get("x-api-key"):
        return "Chave de API não configurada corretamente, senhor."

    prompt_sistema = (
        f"Você é o JARVIS, assistente pessoal de {NOME_USUARIO}. "
        "Responda de forma extremamente útil, direta, elegante e concisa. "
        "Você é o JARVIS, um assistente de IA conversando por voz em tempo real. "
        "Responda sempre em português do Brasil de forma natural, direta, concisa e fluida, "
        "como em um diálogo falado. Nunca mencione que está lendo texto ou que é um modelo de linguagem."
    )

    data = {
        "model": "claude-sonnet-4-5-20250929",
        "max_tokens": 300,
        "system": prompt_sistema,
        "messages": [{"role": "user", "content": pergunta}]
    }

    try:
        response = requests.post(URL_API, json=data, headers=HEADERS_API, timeout=15)
        if response.status_code == 200:
            return response.json()["content"][0]["text"]
        else:
            print(f"Erro na API ({response.status_code}):", response.text)
            return "Desculpe, ocorreu um erro na resposta do Claude, senhor."
    except Exception as e:
        print("Erro de conexão:", e)
        return f"Erro no processamento, senhor: {e}"


# --- ESCUTA POR VOZ (MICROFONE) ---
def ouvir_microfone(recognizer, source):
    recognizer.pause_threshold = 0.8
    print("Escutando... Fale algo:")
    try:
        audio = recognizer.listen(source, timeout=3, phrase_time_limit=3)
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

def detectar_wake_word(recognizer, source):
    """Escuta um trecho curto de áudio e verifica se a palavra de ativação
    ('jarvis'/'jávis') foi dita, para sair do modo de espera."""
    palavras_ativacao = ["jarvis", "jávis"]
    texto = ouvir_microfone(recognizer, source)
    if not texto:
        return False
    return any(palavra in texto.lower() for palavra in palavras_ativacao)

def _fechar_interface_visual():
    try:
        cv2.destroyAllWindows()
    except Exception:
        pass

    if avatar_window is not None:
        try:
            avatar_window.desativar()
        except Exception:
            pass

def loop_conversacao(recognizer, source):
    falar("Sistemas ativos, senhor.")
    while True:
        try:
            pergunta = ouvir_microfone(recognizer, source)

            if pergunta:
                pergunta_lower = pergunta.lower()

                if "desligar processo" in pergunta_lower or "encerrar python" in pergunta_lower:
                    falar("Encerrando o processo por completo, senhor.")
                    _fechar_interface_visual()
                    try:
                        pygame.quit()
                    except Exception:
                        pass
                    os._exit(0)

                palavras_encerramento = ["desativar", "desligar", "encerrar", "até amanhã", "ate amanha"]
                if any(palavra in pergunta_lower for palavra in palavras_encerramento):
                    falar("Entendido, senhor. Colocando sistemas em modo de espera.")
                    _fechar_interface_visual()
                    return

                resposta = obter_resposta_claude(pergunta)
                falar(resposta)
        except Exception as e:
            print(f"Erro no loop de conversação: {e}")
            traceback.print_exc()

def main():
    recognizer = sr.Recognizer()
    with sr.Microphone(device_index=None) as source:
        print("Ajustando para o ruído de fundo... Aguarde um segundo.")
        recognizer.adjust_for_ambient_noise(source, duration=0.5)

        print(f"JARVIS em modo de espera, senhor {NOME_USUARIO}. Diga 'Jarvis' para ativar.")
        while True:
            try:
                if detectar_wake_word(recognizer, source):
                    if avatar_window is not None:
                        try:
                            avatar_window.ativar()
                        except Exception:
                            pass
                    loop_conversacao(recognizer, source)
                    print(f"JARVIS em modo de espera, senhor {NOME_USUARIO}. Diga 'Jarvis' para ativar.")
            except Exception as e:
                print(f"Erro no loop de espera: {e}")
                traceback.print_exc()

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

    def ativar(self):
        self.timer.start(33)
        self.showFullScreen()

    def desativar(self):
        self.timer.stop()
        self.close()

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
    app.setQuitOnLastWindowClosed(False)
    avatar = JarvisVideoAvatar()
    avatar_window = avatar

    threading.Thread(target=main, daemon=True).start()
    sys.exit(app.exec_())
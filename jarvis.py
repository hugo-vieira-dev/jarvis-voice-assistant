import sys
import socket

# --- TRAVA DE INSTÂNCIA ÚNICA ---
# Uma segunda instância falha ao dar bind nessa porta local (já ocupada pela
# instância em execução) e encerra silenciosamente, sem duplicar áudio/GUI.
_instance_lock_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
try:
    _instance_lock_socket.bind(("127.0.0.1", 47823))
except OSError:
    sys.exit(0)

import asyncio
import audioop
import os
import re
import traceback
from dotenv import load_dotenv

load_dotenv()

import cv2
import platform
import psutil
import subprocess
import threading
import webbrowser
import pyautogui
import win32gui
import win32process
import pygame
import edge_tts
import requests
import time
import speech_recognition as sr
from pedalboard import Pedalboard, Delay, PitchShift, Reverb
from pedalboard.io import AudioFile
from PyQt5.QtWidgets import QApplication, QWidget, QLabel
from PyQt5.QtCore import Qt, QTimer, pyqtSignal
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

def _usuario_comecou_a_falar(recognizer, source):
    """Lê um pequeno pedaço bruto do microfone (sem reconhecimento de fala,
    que seria lento demais) e verifica se o nível de energia está acima do
    ruído de fundo calibrado, permitindo interromper (barge-in) a fala do
    JARVIS assim que o usuário começa a falar por cima."""
    try:
        dados = source.stream.read(source.CHUNK)
    except Exception:
        return False
    energia = audioop.rms(dados, source.SAMPLE_WIDTH)
    return energia > recognizer.energy_threshold

def _limpar_markdown(texto):
    """Remove marcações comuns de Markdown (negrito, itálico, código, cabeçalhos,
    marcadores de lista) para o TTS não ler símbolos como 'asterisco' em voz alta."""
    texto = re.sub(r"```.*?```", "", texto, flags=re.DOTALL)
    texto = re.sub(r"`([^`]*)`", r"\1", texto)
    texto = re.sub(r"\*\*([^*]*)\*\*", r"\1", texto)
    texto = re.sub(r"\*([^*]*)\*", r"\1", texto)
    texto = re.sub(r"__([^_]*)__", r"\1", texto)
    texto = re.sub(r"_([^_]*)_", r"\1", texto)
    texto = re.sub(r"^\s{0,3}#{1,6}\s*", "", texto, flags=re.MULTILINE)
    texto = re.sub(r"^\s*[-*+]\s+", "", texto, flags=re.MULTILINE)
    texto = re.sub(r"^\s*\d+\.\s+", "", texto, flags=re.MULTILINE)
    return texto.strip()

def falar(texto, recognizer=None, source=None):
    texto = _limpar_markdown(texto)
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
            if recognizer is not None and source is not None and _usuario_comecou_a_falar(recognizer, source):
                print("Interrupção detectada: cortando a fala do JARVIS.")
                pygame.mixer.music.stop()
                break
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

# --- CONTROLE DO SISTEMA (SITES, APLICATIVOS, INFORMAÇÕES) ---
# Somente comandos fixos e conhecidos são executados: a fala do usuário nunca
# é passada diretamente para o shell/navegador, evitando injeção de comandos.
SITES_CONHECIDOS = {
    "linkedin": "https://www.linkedin.com",
    "youtube": "https://www.youtube.com",
    "google": "https://www.google.com",
    "gmail": "https://mail.google.com",
    "github": "https://github.com",
    "whatsapp": "https://web.whatsapp.com",
}

APLICATIVOS_CONHECIDOS = {
    "bloco de notas": "notepad.exe",
    "notepad": "notepad.exe",
    "calculadora": "calc.exe",
    "chrome": "chrome.exe",
    "google chrome": "chrome.exe",
    "paint": "mspaint.exe",
    "explorador de arquivos": "explorer.exe",
}

CORRECOES_FONETICAS = {
    "linkdin": "linkedin", "linkin": "linkedin", "lingdin": "linkedin",
    "link din": "linkedin", "linked in": "linkedin",
    "yutube": "youtube", "iutube": "youtube",
    "guitrub": "github", "guitebe": "github",
}

def _normalizar_termos_foneticos(texto):
    """Corrige erros comuns de reconhecimento de voz para nomes próprios
    (ex.: 'linkdin' -> 'linkedin') antes de enviar o texto para o Claude."""
    texto_normalizado = texto
    for errado, correto in CORRECOES_FONETICAS.items():
        texto_normalizado = re.sub(re.escape(errado), correto, texto_normalizado, flags=re.IGNORECASE)
    return texto_normalizado

def abrir_site(nome):
    chave = nome.strip().lower()
    url = SITES_CONHECIDOS.get(chave)
    if url is None:
        if chave.startswith("http://") or chave.startswith("https://"):
            url = chave
        else:
            url = f"https://www.google.com/search?q={chave.replace(' ', '+')}"
    webbrowser.open(url)
    return f"Abrindo {nome}, senhor."

def abrir_aplicativo(nome):
    chave = nome.strip().lower()
    executavel = APLICATIVOS_CONHECIDOS.get(chave)
    if executavel is None:
        return f"Não conheço o aplicativo '{nome}', senhor."
    subprocess.Popen(executavel, shell=True)
    return f"Abrindo {nome}, senhor."

def obter_info_sistema():
    info = f"Sistema {platform.system()} {platform.release()}."
    try:
        cpu = psutil.cpu_percent(interval=0.5)
        ram = psutil.virtual_memory()
        info += f" Uso de CPU em {cpu:.0f} por cento. Memória RAM em {ram.percent:.0f} por cento de uso."
    except Exception as e:
        print(f"Erro ao coletar informações do sistema: {e}")
    return info

def fechar_programa(nome):
    chave = nome.strip().lower()
    executavel = APLICATIVOS_CONHECIDOS.get(chave)
    if executavel is None:
        return f"Não conheço o aplicativo '{nome}', senhor."

    encerrados = 0
    for processo in psutil.process_iter(["name"]):
        try:
            if (processo.info["name"] or "").lower() == executavel.lower():
                processo.terminate()
                encerrados += 1
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            continue

    if encerrados == 0:
        return f"Não encontrei o {nome} em execução, senhor."
    return f"Encerrando {nome}, senhor."

NAVEGADORES_CONHECIDOS = {"chrome.exe", "msedge.exe", "firefox.exe", "brave.exe", "opera.exe"}

def _processo_em_foco():
    """Identifica o executável da janela atualmente em foco, para evitar que
    um atalho de teclado global (Ctrl+W) seja disparado sobre o app errado."""
    try:
        hwnd = win32gui.GetForegroundWindow()
        _, pid = win32process.GetWindowThreadProcessId(hwnd)
        return psutil.Process(pid).name().lower()
    except Exception:
        return None

def fechar_aba():
    if _processo_em_foco() not in NAVEGADORES_CONHECIDOS:
        return "O navegador não parece estar em foco no momento, senhor."
    pyautogui.hotkey("ctrl", "w")
    return "Fechando a aba atual, senhor."

def proxima_aba():
    pyautogui.hotkey("ctrl", "tab")
    return "Indo para a próxima aba, senhor."

def aba_anterior():
    pyautogui.hotkey("ctrl", "shift", "tab")
    return "Voltando para a aba anterior, senhor."

FERRAMENTAS = [
    {
        "name": "abrir_site",
        "description": "Abre um site conhecido (LinkedIn, YouTube, Google, Gmail, GitHub, WhatsApp, etc.) no navegador padrão do usuário.",
        "input_schema": {
            "type": "object",
            "properties": {
                "nome": {"type": "string", "description": "Nome do site a abrir, ex.: 'linkedin', 'youtube'."}
            },
            "required": ["nome"]
        }
    },
    {
        "name": "abrir_aplicativo",
        "description": "Abre um aplicativo local do Windows (bloco de notas, calculadora, chrome, paint, explorador de arquivos).",
        "input_schema": {
            "type": "object",
            "properties": {
                "nome": {"type": "string", "description": "Nome do aplicativo a abrir."}
            },
            "required": ["nome"]
        }
    },
    {
        "name": "obter_info_sistema",
        "description": "Retorna informações do sistema operacional, uso de CPU e memória RAM.",
        "input_schema": {"type": "object", "properties": {}}
    },
    {
        "name": "fechar_programa",
        "description": "Encerra um aplicativo em execução (bloco de notas, calculadora, chrome, paint, explorador de arquivos) pelo nome.",
        "input_schema": {
            "type": "object",
            "properties": {
                "nome": {"type": "string", "description": "Nome do aplicativo a fechar."}
            },
            "required": ["nome"]
        }
    },
    {
        "name": "fechar_aba",
        "description": "Fecha a aba atualmente ativa no navegador em foco (equivalente a Ctrl+W).",
        "input_schema": {"type": "object", "properties": {}}
    },
    {
        "name": "proxima_aba",
        "description": "Alterna para a próxima aba do navegador em foco (equivalente a Ctrl+Tab).",
        "input_schema": {"type": "object", "properties": {}}
    },
    {
        "name": "aba_anterior",
        "description": "Alterna para a aba anterior do navegador em foco (equivalente a Ctrl+Shift+Tab).",
        "input_schema": {"type": "object", "properties": {}}
    }
]

def _executar_ferramenta(nome_ferramenta, entrada):
    try:
        if nome_ferramenta == "abrir_site":
            return abrir_site(entrada.get("nome", ""))
        if nome_ferramenta == "abrir_aplicativo":
            return abrir_aplicativo(entrada.get("nome", ""))
        if nome_ferramenta == "obter_info_sistema":
            return obter_info_sistema()
        if nome_ferramenta == "fechar_programa":
            return fechar_programa(entrada.get("nome", ""))
        if nome_ferramenta == "fechar_aba":
            return fechar_aba()
        if nome_ferramenta == "proxima_aba":
            return proxima_aba()
        if nome_ferramenta == "aba_anterior":
            return aba_anterior()
        return "Não reconheci essa ação, senhor."
    except Exception as e:
        print(f"Erro ao executar ferramenta '{nome_ferramenta}': {e}")
        return "Não consegui concluir essa ação, senhor."

# --- INTELIGÊNCIA ---
def obter_resposta_claude(pergunta):
    if not HEADERS_API.get("x-api-key"):
        return "Chave de API não configurada corretamente, senhor."

    pergunta = _normalizar_termos_foneticos(pergunta)

    prompt_sistema = (
        f"Você é o JARVIS, assistente pessoal de {NOME_USUARIO}, conversando por voz em tempo real. "
        "Responda de forma extremamente direta, concisa, elegante e natural, como em um diálogo falado, "
        "sempre em português do Brasil. Nunca mencione que está lendo texto ou que é um modelo de linguagem. "
        "NUNCA use marcadores, listas com asteriscos ou formatação Markdown. "
        "Responda em texto puro, pronto para leitura em voz alta. "
        f"Você tem acesso e permissão para executar comandos no sistema do usuário {NOME_USUARIO}. "
        "Quando o usuário pedir para abrir, fechar um site, aplicativo ou aba, confirme a ação de forma breve e execute-a "
        "usando as ferramentas 'abrir_site', 'abrir_aplicativo', 'fechar_programa', 'fechar_aba', 'proxima_aba' ou 'aba_anterior'. "
        "Se o usuário pedir para fechar uma aba específica e você não souber qual está ativa, "
        "você pode alternar de aba ou fechar a aba atual com o comando correspondente."
    )

    data = {
        "model": "claude-sonnet-4-5-20250929",
        "max_tokens": 300,
        "system": prompt_sistema,
        "messages": [{"role": "user", "content": pergunta}],
        "tools": FERRAMENTAS
    }

    try:
        response = requests.post(URL_API, json=data, headers=HEADERS_API, timeout=15)
        if response.status_code != 200:
            print(f"Erro na API ({response.status_code}):", response.text)
            return "Desculpe, ocorreu um erro na resposta do Claude, senhor."

        blocos = response.json().get("content", [])

        for bloco in blocos:
            if bloco.get("type") == "tool_use":
                return _executar_ferramenta(bloco["name"], bloco.get("input", {}))

        textos = [bloco["text"] for bloco in blocos if bloco.get("type") == "text"]
        return " ".join(textos) if textos else "Não consegui gerar uma resposta, senhor."
    except Exception as e:
        print("Erro de conexão:", e)
        return f"Erro no processamento, senhor: {e}"


# --- ESCUTA POR VOZ (MICROFONE) ---
def ouvir_microfone(recognizer, source):
    recognizer.pause_threshold = 0.6
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
    (ou uma variação fonética dela) foi dita, para sair do modo de espera."""
    palavras_ativacao = [
        "jarvis", "jávis", "javes", "jarves", "jabes",
        "chamar jarvis", "hey jarvis"
    ]
    texto = ouvir_microfone(recognizer, source)
    if not texto:
        return False

    texto_limpo = re.sub(r"[^\w\s]", "", texto.lower())
    return any(palavra in texto_limpo for palavra in palavras_ativacao)

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
    primeira_interacao = True
    while True:
        try:
            if primeira_interacao:
                falar("Sistemas ativos, senhor. Como posso ajudá-lo hoje?", recognizer, source)
                primeira_interacao = False

            pergunta = ouvir_microfone(recognizer, source)

            if pergunta:
                pergunta_lower = pergunta.lower()

                if "desligar processo" in pergunta_lower or "encerrar python" in pergunta_lower:
                    falar("Encerrando o processo por completo, senhor.", recognizer, source)
                    _fechar_interface_visual()
                    try:
                        pygame.quit()
                    except Exception:
                        pass
                    os._exit(0)

                palavras_encerramento = ["desativar", "desligar", "encerrar", "até amanhã", "ate amanha"]
                if any(palavra in pergunta_lower for palavra in palavras_encerramento):
                    falar("Entendido, senhor.", recognizer, source)
                    _fechar_interface_visual()
                    return

                resposta = obter_resposta_claude(pergunta)
                falar(resposta, recognizer, source)
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
                    print("Wake word detectada!")

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
    # 'ativar()'/'desativar()' são chamados pela thread de voz (main()/loop_conversacao()).
    # Manipular um QWidget/QTimer diretamente de outra thread não é seguro no Qt, então
    # essas chamadas apenas emitem um sinal (thread-safe) — o Qt entrega automaticamente
    # via fila para a thread da GUI, onde os slots abaixo de fato mostram/escondem a janela.
    _solicitar_ativacao = pyqtSignal()
    _solicitar_desativacao = pyqtSignal()

    def __init__(self):
        super().__init__()
        self.initUI()
        self._solicitar_ativacao.connect(self._ativar_na_thread_da_gui)
        self._solicitar_desativacao.connect(self._desativar_na_thread_da_gui)

    def initUI(self):
        self.setWindowFlags(Qt.Window | Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint)
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
        self._solicitar_ativacao.emit()

    def desativar(self):
        self._solicitar_desativacao.emit()

    def _ativar_na_thread_da_gui(self):
        self.timer.start(33)
        self.setWindowFlags(Qt.Window | Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint)
        self.showFullScreen()
        self.raise_()
        self.activateWindow()

    def _desativar_na_thread_da_gui(self):
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
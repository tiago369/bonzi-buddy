"""
Bonzi Buddy Animado - lê animações compostas por PASSOS
==========================================================
Cada animação no animations.json (gerado pelo organizador_sprites.py v3)
é uma lista de "passos". Cada passo é um dos dois casos:

- {"modo": "sozinho", "arquivo": "corpo.png"}
    -> mostra esse frame isolado, sem nada sobreposto.

- {"modo": "combinado", "arquivo": "corpo.png", "arquivo_extra": "boca.png",
   "offset_x": 120, "offset_y": 80}
    -> mostra "arquivo" (a base) com "arquivo_extra" (ex: a boca) desenhado
       por cima, na posição definida pelo offset.

Isso permite misturar, numa mesma animação, momentos em que o corpo fica
sozinho parado (pausas) com momentos em que o corpo aparece combinado com
uma boca sobreposta (falando) - sem precisar duplicar o corpo inteiro em
cada frame de fala.

Cada animação também carrega uma "descricao" (texto livre) vinda do JSON,
usada aqui só para exibir no console ao trocar de animação - útil pra
depurar/entender o que cada estado representa, e você pode reaproveitar
esse texto em outras partes do seu assistente (ex: logging).
"""
import sys
import os
import json
import random
import signal
import time
import numpy as np
from PyQt5.QtCore import Qt, QPoint, QTimer, QThread, pyqtSignal
from PyQt5.QtGui import QPixmap, QImage, QPainter, QFontMetrics
from PyQt5.QtWidgets import QApplication, QLabel, QMainWindow, QLineEdit, QMenu

import states
from brain import OllamaBrain
from voice import VoiceAssistant

PASTA_IMAGENS = "imgs"
ARQUIVO_ANIMACOES = os.path.join(PASTA_IMAGENS, "animations.json")

# Cor de fundo a remover (ajuste se necessário) e tolerância (0-255)
COR_FUNDO = (0, 255, 255)  # ciano
TOLERANCIA = 40

# Duracao (em segundos) da transicao suave ao trocar de animacao/pose
DURACAO_TRANSICAO_TROCA = 0.22

# Area reservada (dentro da propria janela do macaco) pra bolha de fala.
# A altura e a base (curta); pra respostas longas ela cresce ate o maximo.
LARGURA_BOLHA = 260
ALTURA_BOLHA = 70
ALTURA_BOLHA_MAXIMA = 280


def remover_fundo(caminho_imagem, cor_fundo=COR_FUNDO, tolerancia=TOLERANCIA):
    """Carrega uma imagem e devolve um QPixmap com o fundo tornado transparente,
    usando uma faixa de tolerância em vez de mascara binária exata.
    Vetorizado com numpy - a versão pixel a pixel em Python puro levava
    minutos para preparar todos os frames das ~50 animações."""
    imagem = QImage(caminho_imagem)
    if imagem.isNull():
        return None
    imagem = imagem.convertToFormat(QImage.Format_ARGB32)

    largura, altura = imagem.width(), imagem.height()
    bytes_por_linha = imagem.bytesPerLine()
    ponteiro = imagem.bits()
    ponteiro.setsize(bytes_por_linha * altura)
    bruto = np.frombuffer(ponteiro, dtype=np.uint8).reshape((altura, bytes_por_linha))
    pixels = bruto[:, : largura * 4].reshape((altura, largura, 4)).copy()

    # Format_ARGB32 guarda cada pixel em memoria (little-endian) como B, G, R, A
    b, g, r = pixels[..., 0].astype(np.int16), pixels[..., 1].astype(np.int16), pixels[..., 2].astype(np.int16)
    r0, g0, b0 = cor_fundo
    mascara = (
        (np.abs(r - r0) <= tolerancia)
        & (np.abs(g - g0) <= tolerancia)
        & (np.abs(b - b0) <= tolerancia)
    )
    pixels[mascara] = 0

    resultado = QImage(pixels.tobytes(), largura, altura, largura * 4, QImage.Format_ARGB32)
    return QPixmap.fromImage(resultado.copy())


class AskWorker(QThread):
    """Roda OllamaBrain.ask() fora da thread da UI para nao travar as
    animacoes enquanto o modelo pensa."""
    resultado = pyqtSignal(str)
    erro = pyqtSignal(str)

    def __init__(self, brain, texto):
        super().__init__()
        self.brain = brain
        self.texto = texto

    def run(self):
        try:
            resposta = self.brain.ask(self.texto)
            self.resultado.emit(resposta)
        except Exception as erro:
            self.erro.emit(str(erro))


class BonziBuddyAnimado(QMainWindow):
    def __init__(self):
        super().__init__()

        self.setWindowFlags(Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.SubWindow)
        self.setAttribute(Qt.WA_TranslucentBackground)

        self.label = QLabel(self)

        self.definicoes_animacoes = self.carregar_definicoes()
        self.cache_pixmaps_arquivo = {}   # nome_arquivo -> QPixmap com fundo removido
        self.frames_prontos = {}          # nome_animacao -> [QPixmap, QPixmap, ...]

        self.preparar_todos_os_frames()

        self.animacao_atual = None
        self.indice_frame = 0
        self.proxima_animacao_apos_terminar = None
        self.forcar_uma_vez = False
        self._ao_terminar_chamar = None

        self._pm_anterior = None
        self._pm_seguinte = None
        self._inicio_segmento = 0.0
        self._duracao_segmento = 0.0

        self.timer = QTimer(self)
        self.timer.timeout.connect(self._tick_render)
        self.timer.start(30)  # ~33fps de interpolacao, independente do fps de cada animacao

        self.tamanho_canvas = self.calcular_tamanho_canvas()
        largura_sprite, altura_sprite = self.tamanho_canvas
        self._largura_janela = max(largura_sprite, LARGURA_BOLHA)
        self._altura_bolha_atual = ALTURA_BOLHA
        altura_janela = altura_sprite + ALTURA_BOLHA
        self.setGeometry(100, 100, self._largura_janela, altura_janela)

        x_sprite = (self._largura_janela - largura_sprite) // 2
        self.label.setGeometry(x_sprite, ALTURA_BOLHA, largura_sprite, altura_sprite)

        # Bolha de fala: widgets filhos da MESMA janela do macaco (em vez de
        # uma janela top-level separada) - um QWidget frameless+translucido
        # independente se mostrou pouco confiavel pra compositar nesta
        # maquina (as vezes simplesmente nao pintava na tela).
        estilo_bolha = (
            "background-color: rgba(255, 255, 255, 235); border-radius: 10px;"
            "padding: 8px; font-size: 13px; color: #222;"
        )

        self.label_bolha = QLabel(self)
        self.label_bolha.setGeometry(0, 0, self._largura_janela, ALTURA_BOLHA - 12)
        self.label_bolha.setWordWrap(True)
        self.label_bolha.setAlignment(Qt.AlignCenter)
        self.label_bolha.setStyleSheet(estilo_bolha)
        self.label_bolha.hide()

        self.campo_bolha = QLineEdit(self)
        self.campo_bolha.setGeometry(0, 0, self._largura_janela, ALTURA_BOLHA - 12)
        self.campo_bolha.setPlaceholderText("Fala com o macaco...")
        self.campo_bolha.setStyleSheet(estilo_bolha)
        self.campo_bolha.returnPressed.connect(self._enviar_do_campo)
        self.campo_bolha.hide()

        self.drag_position = QPoint()
        self._arrastou = False

        # ---------------- Comportamento de assistente ----------------
        self.estado_atual = "IDLE"
        self._worker = None

        self.brain = OllamaBrain()
        self.voice = VoiceAssistant()

        self.voice.gravacao_iniciada.connect(lambda: self.entrar_estado("LISTENING"))
        self.voice.transcricao_pronta.connect(self._ao_transcricao)
        self.voice.fala_finalizada.connect(self._ao_fala_finalizada)

        if not self.frames_prontos:
            print(f"Nenhuma animação encontrada em {ARQUIVO_ANIMACOES}. "
                  f"Gere esse arquivo com organizador_sprites.py.")
        else:
            self.voice.iniciar()
            self.entrar_estado("GREETING")

    # ------------------------------------------------------------------
    # Controle do assistente (estados <-> animacoes)
    # ------------------------------------------------------------------
    def _tocar_estado(self, nome):
        if nome in self.frames_prontos:
            self.tocar_animacao(nome, ao_terminar_ir_para=nome)

    def _agendar_proximo_gesto_idle(self):
        intervalo_ms = random.randint(4000, 9000)
        QTimer.singleShot(intervalo_ms, self._tick_gesto_idle)

    def _tick_gesto_idle(self):
        if self.estado_atual != "IDLE":
            return
        gesto = random.choice(states.IDLE_GESTOS)
        self.tocar_animacao(
            gesto,
            ao_terminar_ir_para=states.IDLE_BASE,
            uma_vez=True,
            ao_terminar_chamar=self._agendar_proximo_gesto_idle,
        )

    def entrar_estado(self, estado, texto=None):
        self.estado_atual = estado

        if estado == "IDLE":
            self._esconder_bolha()
            self._tocar_estado(states.IDLE_BASE)
            self._agendar_proximo_gesto_idle()

        elif estado == "GREETING":
            self._tocar_estado(random.choice(states.GREETING_POOL))
            QTimer.singleShot(3000, self._ao_greeting_terminar)

        elif estado == "LISTENING":
            self._esconder_bolha()
            self._tocar_estado(random.choice(states.LISTENING_POOL))

        elif estado == "THINKING":
            self._tocar_estado(random.choice(states.THINKING_POOL))

        elif estado == "FALANDO":
            pool = states.escolher_pool_para_resposta(texto)
            self._tocar_estado(random.choice(pool))
            self._mostrar_texto_bolha(texto)
            if self.voice.mudo:
                duracao_ms = max(1500, int(len(texto or "") * 55))
                QTimer.singleShot(duracao_ms, self._ao_fala_finalizada)
            else:
                self.voice.falar(texto)

    def processar_pergunta(self, texto):
        texto = (texto or "").strip()
        if not texto:
            return
        self.entrar_estado("THINKING")
        self._worker = AskWorker(self.brain, texto)
        self._worker.resultado.connect(lambda r: self.entrar_estado("FALANDO", texto=r))
        self._worker.erro.connect(self._ao_resposta_com_erro)
        self._worker.start()

    def _ao_resposta_com_erro(self, mensagem_tecnica):
        print(f"[erro ao falar com a IA] {mensagem_tecnica}")
        self.entrar_estado("FALANDO", texto="Deu erro ao pensar - o Ollama tá rodando? (veja o console)")

    def _ao_transcricao(self, texto):
        texto = (texto or "").strip()
        if not texto:
            self.entrar_estado("FALANDO", texto="Não te ouvi direito, tenta de novo?")
            return
        self.processar_pergunta(texto)

    def _ao_greeting_terminar(self):
        if self.estado_atual == "GREETING":
            self.entrar_estado("IDLE")

    def _ao_fala_finalizada(self):
        if self.estado_atual == "FALANDO":
            self.entrar_estado("IDLE")

    # ------------------------------------------------------------------
    # Bolha de fala (widgets dentro da propria janela do macaco)
    # ------------------------------------------------------------------
    def _altura_necessaria_para_texto(self, texto, largura):
        margem_padding = 20  # ~ padding do stylesheet (8px de cada lado) + folga
        fm = QFontMetrics(self.label_bolha.font())
        rect = fm.boundingRect(0, 0, largura - margem_padding, 0, Qt.TextWordWrap, texto)
        return rect.height() + margem_padding

    def _ajustar_altura_bolha(self, altura_bolha_nova):
        """Redimensiona a area da bolha (e a janela toda) mantendo o macaco
        ancorado no mesmo lugar da tela - a janela cresce pra CIMA."""
        delta = altura_bolha_nova - self._altura_bolha_atual
        if delta == 0:
            return
        largura_sprite, altura_sprite = self.tamanho_canvas
        x_sprite = (self._largura_janela - largura_sprite) // 2

        self.setGeometry(self.x(), self.y() - delta, self._largura_janela, altura_sprite + altura_bolha_nova)
        self.label.setGeometry(x_sprite, altura_bolha_nova, largura_sprite, altura_sprite)
        self.label_bolha.setGeometry(0, 0, self._largura_janela, altura_bolha_nova - 12)
        self.campo_bolha.setGeometry(0, 0, self._largura_janela, altura_bolha_nova - 12)
        self._altura_bolha_atual = altura_bolha_nova

    def _mostrar_texto_bolha(self, texto):
        self.campo_bolha.hide()
        altura_necessaria = self._altura_necessaria_para_texto(texto, self._largura_janela)
        altura_bolha = max(ALTURA_BOLHA, min(altura_necessaria + 12, ALTURA_BOLHA_MAXIMA))
        self._ajustar_altura_bolha(altura_bolha)
        self.label_bolha.setText(texto)
        self.label_bolha.show()

    def _esconder_bolha(self):
        self.label_bolha.hide()
        self.campo_bolha.hide()
        self._ajustar_altura_bolha(ALTURA_BOLHA)

    def _alternar_campo_bolha(self):
        if self.campo_bolha.isVisible():
            self._esconder_bolha()
        else:
            self.label_bolha.hide()
            self._ajustar_altura_bolha(ALTURA_BOLHA)
            self.campo_bolha.show()
            self.campo_bolha.setFocus()

    def _enviar_do_campo(self):
        texto = self.campo_bolha.text().strip()
        self.campo_bolha.clear()
        self.campo_bolha.hide()
        if texto:
            self.processar_pergunta(texto)

    # ------------------------------------------------------------------
    # Carregamento e pré-processamento
    # ------------------------------------------------------------------
    def carregar_definicoes(self):
        if not os.path.exists(ARQUIVO_ANIMACOES):
            print(f"Aviso: {ARQUIVO_ANIMACOES} não encontrado.")
            return {}
        with open(ARQUIVO_ANIMACOES, "r", encoding="utf-8") as f:
            return json.load(f)

    def obter_pixmap_arquivo(self, nome_arquivo):
        if nome_arquivo in self.cache_pixmaps_arquivo:
            return self.cache_pixmaps_arquivo[nome_arquivo]
        caminho = os.path.join(PASTA_IMAGENS, nome_arquivo)
        if not os.path.exists(caminho):
            print(f"Erro: não encontrei o arquivo {caminho}")
            return None
        pm = remover_fundo(caminho)
        self.cache_pixmaps_arquivo[nome_arquivo] = pm
        return pm

    def compor_passo(self, passo):
        """Converte um passo do JSON ('sozinho' ou 'combinado') num único
        QPixmap já pronto pra exibir, suportando até 3 camadas."""
        if passo["modo"] == "sozinho":
            return self.obter_pixmap_arquivo(passo["arquivo"])

        base_pm = self.obter_pixmap_arquivo(passo["arquivo"])
        if base_pm is None:
            return None
        composto = QPixmap(base_pm.size())
        composto.fill(Qt.transparent)
        pintor = QPainter(composto)
        pintor.drawPixmap(0, 0, base_pm)
        
        # Camada 2 (ex: Caixa de Correio)
        overlay_pm = self.obter_pixmap_arquivo(passo.get("arquivo_extra"))
        if overlay_pm is not None:
            pintor.drawPixmap(passo.get("offset_x", 0), passo.get("offset_y", 0), overlay_pm)
            
        # Camada 3 (ex: Recorte dos olhos/olhadinha)
        if "arquivo_extra2" in passo:
            overlay_pm2 = self.obter_pixmap_arquivo(passo.get("arquivo_extra2"))
            if overlay_pm2 is not None:
                pintor.drawPixmap(passo.get("offset_x2", 0), passo.get("offset_y2", 0), overlay_pm2)
                
        pintor.end()
        return composto

    def preparar_todos_os_frames(self):
        for nome, dados in self.definicoes_animacoes.items():
            descricao = dados.get("descricao", "")
            if descricao:
                print(f"[animação '{nome}'] {descricao}")

            frames = []
            for passo in dados.get("passos", []):
                pm = self.compor_passo(passo)
                if pm is not None:
                    frames.append(pm)
            self.frames_prontos[nome] = frames

    def calcular_tamanho_canvas(self):
        maior_largura, maior_altura = 100, 100
        for frames in self.frames_prontos.values():
            for pm in frames:
                maior_largura = max(maior_largura, pm.width())
                maior_altura = max(maior_altura, pm.height())
        return maior_largura, maior_altura

    # ------------------------------------------------------------------
    # Reprodução (com transicoes suaves entre frames/animacoes)
    # ------------------------------------------------------------------
    def _pixmap_no_canvas(self, pixmap_sprite):
        canvas = QPixmap(*self.tamanho_canvas)
        canvas.fill(Qt.transparent)
        pintor = QPainter(canvas)
        x = (self.tamanho_canvas[0] - pixmap_sprite.width()) // 2
        y = self.tamanho_canvas[1] - pixmap_sprite.height()
        pintor.drawPixmap(x, max(y, 0), pixmap_sprite)
        pintor.end()
        return canvas

    def _misturar_pixmaps(self, pm_de, pm_para, fracao_para):
        """Combina dois frames (ja no tamanho do canvas) por opacidade, pra
        criar uma transicao suave em vez de um corte seco entre poses."""
        if pm_de is None:
            return pm_para
        resultado = QPixmap(pm_para.size())
        resultado.fill(Qt.transparent)
        pintor = QPainter(resultado)
        pintor.drawPixmap(0, 0, pm_de)
        pintor.setOpacity(max(0.0, min(1.0, fracao_para)))
        pintor.drawPixmap(0, 0, pm_para)
        pintor.end()
        return resultado

    def tocar_animacao(self, nome, ao_terminar_ir_para=None, uma_vez=False, ao_terminar_chamar=None):
        """Troca a animação em exibição, sempre com uma transição curta a
        partir do que estava na tela (evita o "pulo" seco entre poses).
        Com uma_vez=True, toca so uma passada (ignorando o loop do JSON) e
        segue pra ao_terminar_ir_para - usado pra gestos pontuais (piscar,
        bocejar) que nao devem ficar se repetindo sem parar. ao_terminar_chamar
        e um callback opcional disparado quando essa passada termina de fato
        (util pra so agendar o proximo gesto depois que o atual realmente
        acabou, em vez de num intervalo fixo que pode interromper no meio)."""
        if nome not in self.frames_prontos or not self.frames_prontos[nome]:
            print(f"Animação '{nome}' não existe (ou está vazia) no {ARQUIVO_ANIMACOES}.")
            return

        alvo = self._pixmap_no_canvas(self.frames_prontos[nome][0])

        self.animacao_atual = nome
        self.indice_frame = 0
        self.proxima_animacao_apos_terminar = ao_terminar_ir_para
        self.forcar_uma_vez = uma_vez
        self._ao_terminar_chamar = ao_terminar_chamar

        if self._pm_seguinte is not None:
            self._pm_anterior = self._pm_seguinte
            self._duracao_segmento = DURACAO_TRANSICAO_TROCA
        else:
            self._pm_anterior = alvo
            self._duracao_segmento = 0.0
        self._pm_seguinte = alvo
        self._inicio_segmento = time.monotonic()

    def descricao_animacao_atual(self):
        """Devolve o texto de descrição da animação em andamento (útil se você
        quiser exibir/logar o que o bonzi está fazendo no momento)."""
        if not self.animacao_atual:
            return ""
        return self.definicoes_animacoes.get(self.animacao_atual, {}).get("descricao", "")

    def _tick_render(self):
        """Roda em ~30fps, independente do fps de cada animação: interpola
        entre o frame anterior e o próximo pra suavizar o movimento."""
        if self._pm_seguinte is None:
            return
        agora = time.monotonic()
        fracao = 1.0 if self._duracao_segmento <= 0 else (agora - self._inicio_segmento) / self._duracao_segmento

        if fracao >= 1.0:
            self.label.setPixmap(self._pm_seguinte)
            self._avancar_frame()
        else:
            self.label.setPixmap(self._misturar_pixmaps(self._pm_anterior, self._pm_seguinte, fracao))

    def _avancar_frame(self):
        dados = self.definicoes_animacoes[self.animacao_atual]
        frames = self.frames_prontos[self.animacao_atual]
        total_frames = len(frames)
        fps = dados.get("fps", 8)
        proximo_indice = self.indice_frame + 1

        if proximo_indice >= total_frames:
            if dados.get("loop", True) and not self.forcar_uma_vez:
                proximo_indice = 0
            else:
                proxima = self.proxima_animacao_apos_terminar
                callback = self._ao_terminar_chamar
                self._ao_terminar_chamar = None
                if proxima and proxima in self.frames_prontos:
                    self.tocar_animacao(proxima)
                if callback:
                    callback()
                return

        self.indice_frame = proximo_indice
        self._pm_anterior = self._pm_seguinte
        self._pm_seguinte = self._pixmap_no_canvas(frames[self.indice_frame])
        self._duracao_segmento = 1.0 / fps
        self._inicio_segmento = time.monotonic()

    # ------------------------------------------------------------------
    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            self.drag_position = event.globalPos() - self.frameGeometry().topLeft()
            self._arrastou = False
            event.accept()

    def mouseMoveEvent(self, event):
        if event.buttons() == Qt.LeftButton:
            self._arrastou = True
            self.move(event.globalPos() - self.drag_position)
            event.accept()

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.LeftButton and not self._arrastou:
            self._alternar_campo_bolha()
        event.accept()

    def mouseDoubleClickEvent(self, event):
        """Dois cliques faz o macaco dar um oi manualmente."""
        self.entrar_estado("GREETING")

    def contextMenuEvent(self, event):
        menu = QMenu(self)
        acao_mudo = menu.addAction("Silenciar voz")
        acao_mudo.setCheckable(True)
        acao_mudo.setChecked(self.voice.mudo)
        menu.addAction("Push-to-talk: segure F9 para falar").setEnabled(False)
        menu.addSeparator()
        acao_sair = menu.addAction("Sair")

        escolhida = menu.exec_(event.globalPos())
        if escolhida == acao_mudo:
            self.voice.mudo = not self.voice.mudo
        elif escolhida == acao_sair:
            QApplication.instance().quit()


if __name__ == "__main__":
    app = QApplication(sys.argv)
    
    # 1. Configura o tratamento do Ctrl+C AQUI (antes de rodar o app)
    signal.signal(signal.SIGINT, signal.SIG_DFL)
    
    buddy = BonziBuddyAnimado()
    buddy.show()
    app.aboutToQuit.connect(buddy.voice.parar)

    # 2. Inicia o loop da interface gráfica
    sys.exit(app.exec_())
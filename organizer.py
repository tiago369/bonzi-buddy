"""
Organizador de Sprites - Bonzi Buddy (v3)
===========================================
Cada animação agora é uma lista de PASSOS, e cada passo pode ser de dois
tipos (isso resolve a mistura "algumas sprites mexem só a boca, outras
devem permanecer de fundo"):

1) "Sozinho": um único frame exibido isoladamente naquele instante
   (ex: o corpo parado, uma pose de cabeça, um frame de transição).

2) "Combinado": um frame BASE (o corpo/fundo) desenhado junto com o
   PRÓXIMO frame escolhido (tipicamente uma boca), sobrepostos num
   deslocamento (offset X/Y) que você ajusta vendo o resultado ao vivo.
   Isso simula a fala: o corpo fica parado no fundo e só a boca muda.

Como os passos são independentes, dá pra misturar livremente numa mesma
animação: alguns instantes com o corpo sozinho (pausas na fala) e outros
com corpo + boca combinados (sílabas), tudo numa única sequência.

FLUXO DE USO
------------
1. "Escolher pasta de imagens".
2. Pra um passo simples: selecione o frame na lista da esquerda e clique
   em "Adicionar SOZINHO".
3. Pra um passo combinado:
   a. Selecione o frame do corpo/fundo e clique em "Marcar como BASE".
   b. Selecione o frame da boca (ou outro overlay) na lista da esquerda.
   c. Ajuste "Deslocamento X/Y" olhando a prévia de montagem ao vivo.
   d. Clique em "Adicionar COMBINADO (base + selecionado)".
4. Repita os passos 2/3 na ordem em que a animação deve tocar.
5. Clique em "Reproduzir prévia" pra ver a sequência inteira rodando.
6. Preencha nome, descrição, loop e FPS, e clique em "Salvar animação".
7. No final, "Exportar JSON" gera o animations.json.
"""
import sys
import os
import json
from PyQt5.QtCore import Qt, QSize, QTimer
from PyQt5.QtGui import QIcon, QPixmap, QPainter, QColor
from PyQt5.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QListWidget, QListWidgetItem, QPushButton, QLabel, QLineEdit,
    QTextEdit, QSpinBox, QCheckBox, QFileDialog, QMessageBox, QGroupBox
)

EXTENSOES_VALIDAS = (".png", ".jpg", ".jpeg", ".bmp", ".gif")

# Mesma cor/tolerância usada no app final - ajuste se seu fundo não for ciano
COR_FUNDO = QColor(0, 255, 255)


def carregar_pixmap_sem_fundo(caminho, cor_fundo=COR_FUNDO):
    """Versão rápida (mascara binária) só para a prévia dentro do organizador.
    O app final (bonzi_animado.py) usa uma versão com tolerância de cor,
    melhor pra qualidade; aqui priorizamos velocidade pro preview fluido."""
    pm = QPixmap(caminho)
    if pm.isNull():
        return None
    mask = pm.createMaskFromColor(cor_fundo, Qt.MaskInColor)
    pm.setMask(mask)
    return pm


def texto_do_passo(passo):
    if passo["modo"] == "sozinho":
        return f"[sozinho] {passo['arquivo']}"
    return f"[combinado] {passo['arquivo']} + {passo['arquivo_extra']} (offset {passo['offset_x']},{passo['offset_y']})"


class OrganizadorSprites(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Organizador de Sprites - Bonzi Buddy")
        self.resize(1200, 720)

        self.pasta_imagens = ""
        self.animacoes = {}  # nome -> {"descricao", "loop", "fps", "passos": [...]}
        self.cache_pixmaps = {}  # nome_arquivo -> QPixmap já com fundo removido

        self.base_atual = None  # nome do arquivo marcado como base p/ o próximo "combinado"

        self.timer_preview = QTimer(self)
        self.timer_preview.timeout.connect(self._avancar_preview)
        self.indice_preview = 0

        central = QWidget()
        self.setCentralWidget(central)
        layout_principal = QHBoxLayout(central)

        # ---------------- Coluna esquerda: banco de frames ----------------
        col_esquerda = QVBoxLayout()
        self.btn_escolher_pasta = QPushButton("Escolher pasta de imagens")
        self.btn_escolher_pasta.clicked.connect(self.escolher_pasta)
        col_esquerda.addWidget(self.btn_escolher_pasta)

        self.label_pasta = QLabel("Nenhuma pasta selecionada")
        self.label_pasta.setWordWrap(True)
        col_esquerda.addWidget(self.label_pasta)

        col_esquerda.addWidget(QLabel("Todos os frames encontrados (selecione, depois use os botões à direita):"))
        self.lista_frames = QListWidget()
        self.lista_frames.setViewMode(QListWidget.IconMode)
        self.lista_frames.setIconSize(QSize(80, 80))
        self.lista_frames.setResizeMode(QListWidget.Adjust)
        self.lista_frames.currentItemChanged.connect(self.atualizar_preview_montagem)
        col_esquerda.addWidget(self.lista_frames)

        layout_principal.addLayout(col_esquerda, 3)

        # ---------------- Coluna central: montagem do passo ----------------
        col_central = QVBoxLayout()

        grupo_passo = QGroupBox("Montar próximo passo")
        layout_passo = QVBoxLayout(grupo_passo)

        self.btn_adicionar_sozinho = QPushButton("Adicionar SOZINHO (frame selecionado à esquerda)")
        self.btn_adicionar_sozinho.clicked.connect(self.adicionar_passo_sozinho)
        layout_passo.addWidget(self.btn_adicionar_sozinho)

        linha_base = QHBoxLayout()
        self.btn_marcar_base = QPushButton("Marcar selecionado como BASE")
        self.btn_marcar_base.clicked.connect(self.marcar_base)
        linha_base.addWidget(self.btn_marcar_base)
        self.label_base_atual = QLabel("Base: (nenhuma)")
        linha_base.addWidget(self.label_base_atual)
        layout_passo.addLayout(linha_base)

        linha_offset = QHBoxLayout()
        linha_offset.addWidget(QLabel("Deslocamento X:"))
        self.spin_offset_x = QSpinBox()
        self.spin_offset_x.setRange(-2000, 2000)
        self.spin_offset_x.valueChanged.connect(self.atualizar_preview_montagem)
        linha_offset.addWidget(self.spin_offset_x)
        linha_offset.addWidget(QLabel("Y:"))
        self.spin_offset_y = QSpinBox()
        self.spin_offset_y.setRange(-2000, 2000)
        self.spin_offset_y.valueChanged.connect(self.atualizar_preview_montagem)
        linha_offset.addWidget(self.spin_offset_y)
        layout_passo.addLayout(linha_offset)

        self.btn_adicionar_combinado = QPushButton("Adicionar COMBINADO (base + selecionado à esquerda)")
        self.btn_adicionar_combinado.clicked.connect(self.adicionar_passo_combinado)
        layout_passo.addWidget(self.btn_adicionar_combinado)

        col_central.addWidget(grupo_passo)

        col_central.addWidget(QLabel("Sequência de passos (ordem de reprodução; duplo-clique remove):"))
        self.lista_sequencia = QListWidget()
        self.lista_sequencia.itemDoubleClicked.connect(self.remover_passo)
        self.lista_sequencia.currentItemChanged.connect(self.atualizar_preview_passo_selecionado)
        col_central.addWidget(self.lista_sequencia)

        self.btn_limpar_seq = QPushButton("Limpar sequência")
        self.btn_limpar_seq.clicked.connect(self.limpar_sequencia)
        col_central.addWidget(self.btn_limpar_seq)

        grupo_config = QGroupBox("Dados da animação")
        form = QVBoxLayout(grupo_config)

        linha_nome = QHBoxLayout()
        linha_nome.addWidget(QLabel("Nome:"))
        self.input_nome = QLineEdit()
        self.input_nome.setPlaceholderText("ex: idle, falando, saudacao...")
        linha_nome.addWidget(self.input_nome)
        form.addLayout(linha_nome)

        form.addWidget(QLabel("Descrição (o que essa ação representa):"))
        self.input_descricao = QTextEdit()
        self.input_descricao.setPlaceholderText(
            "ex: Bonzi parado respirando levemente, usado quando a IA está ociosa."
        )
        self.input_descricao.setFixedHeight(60)
        form.addWidget(self.input_descricao)

        linha_opcoes = QHBoxLayout()
        self.check_loop = QCheckBox("Repetir em loop")
        self.check_loop.setChecked(True)
        linha_opcoes.addWidget(self.check_loop)
        linha_opcoes.addWidget(QLabel("FPS:"))
        self.spin_fps = QSpinBox()
        self.spin_fps.setRange(1, 60)
        self.spin_fps.setValue(8)
        self.spin_fps.valueChanged.connect(self._reiniciar_timer_preview_se_ativo)
        linha_opcoes.addWidget(self.spin_fps)
        form.addLayout(linha_opcoes)
        col_central.addWidget(grupo_config)

        self.btn_salvar_animacao = QPushButton("Salvar animação")
        self.btn_salvar_animacao.clicked.connect(self.salvar_animacao)
        col_central.addWidget(self.btn_salvar_animacao)

        layout_principal.addLayout(col_central, 3)

        # ---------------- Coluna direita: prévia + animações salvas ----------------
        col_direita = QVBoxLayout()

        col_direita.addWidget(QLabel("Prévia:"))
        self.label_preview = QLabel()
        self.label_preview.setFixedSize(260, 260)
        self.label_preview.setStyleSheet("background-color: #444; border: 1px solid #888;")
        self.label_preview.setAlignment(Qt.AlignCenter)
        col_direita.addWidget(self.label_preview)

        botoes_preview = QHBoxLayout()
        self.btn_play = QPushButton("▶ Reproduzir prévia")
        self.btn_play.clicked.connect(self.tocar_preview)
        botoes_preview.addWidget(self.btn_play)
        self.btn_stop = QPushButton("⏸ Parar")
        self.btn_stop.clicked.connect(self.parar_preview)
        botoes_preview.addWidget(self.btn_stop)
        col_direita.addLayout(botoes_preview)

        col_direita.addWidget(QLabel("Animações já salvas:"))
        self.lista_animacoes_salvas = QListWidget()
        col_direita.addWidget(self.lista_animacoes_salvas)

        self.btn_exportar = QPushButton("Exportar JSON (animations.json)")
        self.btn_exportar.clicked.connect(self.exportar_json)
        col_direita.addWidget(self.btn_exportar)

        layout_principal.addLayout(col_direita, 2)

    # ------------------------------------------------------------------
    # Carregamento de pasta / cache
    # ------------------------------------------------------------------
    def escolher_pasta(self):
        pasta = QFileDialog.getExistingDirectory(self, "Escolha a pasta com os frames")
        if not pasta:
            return
        self.pasta_imagens = pasta
        self.label_pasta.setText(pasta)
        self.lista_frames.clear()
        self.cache_pixmaps.clear()

        arquivos = sorted(
            f for f in os.listdir(pasta)
            if f.lower().endswith(EXTENSOES_VALIDAS)
        )
        for nome_arquivo in arquivos:
            caminho = os.path.join(pasta, nome_arquivo)
            item = QListWidgetItem(QIcon(caminho), nome_arquivo)
            item.setData(Qt.UserRole, nome_arquivo)
            self.lista_frames.addItem(item)

        if not arquivos:
            QMessageBox.warning(self, "Aviso", "Nenhuma imagem encontrada nessa pasta.")

    def obter_pixmap(self, nome_arquivo):
        if nome_arquivo in self.cache_pixmaps:
            return self.cache_pixmaps[nome_arquivo]
        caminho = os.path.join(self.pasta_imagens, nome_arquivo)
        pm = carregar_pixmap_sem_fundo(caminho)
        self.cache_pixmaps[nome_arquivo] = pm
        return pm

    # ------------------------------------------------------------------
    # Construção dos passos
    # ------------------------------------------------------------------
    def marcar_base(self):
        item = self.lista_frames.currentItem()
        if item is None:
            QMessageBox.warning(self, "Aviso", "Selecione um frame na lista da esquerda primeiro.")
            return
        self.base_atual = item.data(Qt.UserRole)
        self.label_base_atual.setText(f"Base: {self.base_atual}")
        self.atualizar_preview_montagem()

    def adicionar_passo_sozinho(self):
        item = self.lista_frames.currentItem()
        if item is None:
            QMessageBox.warning(self, "Aviso", "Selecione um frame na lista da esquerda primeiro.")
            return
        passo = {"modo": "sozinho", "arquivo": item.data(Qt.UserRole)}
        self._adicionar_passo_na_lista(passo)

    def adicionar_passo_combinado(self):
        item = self.lista_frames.currentItem()
        if item is None:
            QMessageBox.warning(self, "Aviso", "Selecione o frame de boca/overlay na lista da esquerda.")
            return
        if not self.base_atual:
            QMessageBox.warning(self, "Aviso", "Marque um frame como BASE primeiro.")
            return
        passo = {
            "modo": "combinado",
            "arquivo": self.base_atual,
            "arquivo_extra": item.data(Qt.UserRole),
            "offset_x": self.spin_offset_x.value(),
            "offset_y": self.spin_offset_y.value(),
        }
        self._adicionar_passo_na_lista(passo)

    def _adicionar_passo_na_lista(self, passo):
        item = QListWidgetItem(texto_do_passo(passo))
        item.setData(Qt.UserRole, passo)
        pm = self.compor_passo(passo)
        if pm is not None:
            item.setIcon(QIcon(pm))
        self.lista_sequencia.addItem(item)

    def remover_passo(self, item):
        self.lista_sequencia.takeItem(self.lista_sequencia.row(item))

    def limpar_sequencia(self):
        self.lista_sequencia.clear()

    def _passos_atuais(self):
        return [self.lista_sequencia.item(i).data(Qt.UserRole)
                for i in range(self.lista_sequencia.count())]

    # ------------------------------------------------------------------
    # Composição / prévia
    # ------------------------------------------------------------------
    def compor_passo(self, passo):
        if passo is None:
            return None
        if passo["modo"] == "sozinho":
            return self.obter_pixmap(passo["arquivo"])

        base_pm = self.obter_pixmap(passo["arquivo"])
        if base_pm is None:
            return None
        resultado = QPixmap(base_pm.size())
        resultado.fill(Qt.transparent)
        pintor = QPainter(resultado)
        pintor.drawPixmap(0, 0, base_pm)
        overlay_pm = self.obter_pixmap(passo["arquivo_extra"])
        if overlay_pm is not None:
            pintor.drawPixmap(passo["offset_x"], passo["offset_y"], overlay_pm)
        pintor.end()
        return resultado

    def atualizar_preview_montagem(self):
        """Prévia ao vivo do passo que está sendo montado (antes de adicionar):
        se houver uma base marcada, mostra base + frame selecionado à esquerda
        no offset atual; senão mostra só o frame selecionado."""
        if self.timer_preview.isActive():
            return
        item = self.lista_frames.currentItem()
        if item is None:
            return
        nome_selecionado = item.data(Qt.UserRole)
        if self.base_atual:
            passo_tentativa = {
                "modo": "combinado",
                "arquivo": self.base_atual,
                "arquivo_extra": nome_selecionado,
                "offset_x": self.spin_offset_x.value(),
                "offset_y": self.spin_offset_y.value(),
            }
        else:
            passo_tentativa = {"modo": "sozinho", "arquivo": nome_selecionado}
        self._mostrar_no_preview(self.compor_passo(passo_tentativa))

    def atualizar_preview_passo_selecionado(self):
        if self.timer_preview.isActive():
            return
        item = self.lista_sequencia.currentItem()
        if item is None:
            return
        self._mostrar_no_preview(self.compor_passo(item.data(Qt.UserRole)))

    def _mostrar_no_preview(self, pixmap):
        if pixmap is None:
            self.label_preview.clear()
            return
        escalado = pixmap.scaled(self.label_preview.size(), Qt.KeepAspectRatio, Qt.SmoothTransformation)
        self.label_preview.setPixmap(escalado)

    # ------------------------------------------------------------------
    # Reprodução da prévia animada
    # ------------------------------------------------------------------
    def tocar_preview(self):
        passos = self._passos_atuais()
        if not passos:
            QMessageBox.warning(self, "Aviso", "A sequência está vazia.")
            return
        self.indice_preview = 0
        self.timer_preview.start(int(1000 / self.spin_fps.value()))

    def parar_preview(self):
        self.timer_preview.stop()
        self.atualizar_preview_passo_selecionado()

    def _reiniciar_timer_preview_se_ativo(self):
        if self.timer_preview.isActive():
            self.timer_preview.start(int(1000 / self.spin_fps.value()))

    def _avancar_preview(self):
        passos = self._passos_atuais()
        if not passos:
            self.parar_preview()
            return
        passo = passos[self.indice_preview % len(passos)]
        self._mostrar_no_preview(self.compor_passo(passo))
        self.indice_preview += 1
        if self.indice_preview >= len(passos) and not self.check_loop.isChecked():
            self.parar_preview()

    # ------------------------------------------------------------------
    # Salvar / exportar
    # ------------------------------------------------------------------
    def salvar_animacao(self):
        nome = self.input_nome.text().strip()
        if not nome:
            QMessageBox.warning(self, "Aviso", "Dê um nome para a animação.")
            return
        passos = self._passos_atuais()
        if not passos:
            QMessageBox.warning(self, "Aviso", "A sequência está vazia.")
            return

        self.animacoes[nome] = {
            "descricao": self.input_descricao.toPlainText().strip(),
            "loop": self.check_loop.isChecked(),
            "fps": self.spin_fps.value(),
            "passos": passos,
        }

        self.atualizar_lista_animacoes_salvas()
        QMessageBox.information(self, "OK", f"Animação '{nome}' salva com {len(passos)} passo(s).")
        self.lista_sequencia.clear()
        self.input_nome.clear()
        self.input_descricao.clear()
        self.parar_preview()

    def atualizar_lista_animacoes_salvas(self):
        self.lista_animacoes_salvas.clear()
        for nome, dados in self.animacoes.items():
            descricao = dados.get("descricao") or "(sem descrição)"
            texto = f"{nome} — {descricao}  [{len(dados['passos'])} passo(s), {dados['fps']} fps, loop={dados['loop']}]"
            self.lista_animacoes_salvas.addItem(texto)

    def exportar_json(self):
        if not self.animacoes:
            QMessageBox.warning(self, "Aviso", "Nenhuma animação salva ainda.")
            return
        destino, _ = QFileDialog.getSaveFileName(
            self, "Salvar JSON", os.path.join(self.pasta_imagens or ".", "animations.json"),
            "JSON (*.json)"
        )
        if not destino:
            return
        with open(destino, "w", encoding="utf-8") as f:
            json.dump(self.animacoes, f, ensure_ascii=False, indent=2)
        QMessageBox.information(self, "OK", f"Exportado em:\n{destino}")


if __name__ == "__main__":
    app = QApplication(sys.argv)
    janela = OrganizadorSprites()
    janela.show()
    sys.exit(app.exec_())
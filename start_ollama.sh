#!/usr/bin/env bash
# Nesta maquina, o backend CUDA do Ollama trava com a RTX 3050 Laptop
# ("CUDA error: device kernel image is invalid" - incompatibilidade entre o
# driver 535 instalado e os kernels CUDA v12 que o Ollama usa). Ate isso ser
# corrigido (atualizando o driver da NVIDIA, por exemplo), rodamos em CPU.
export CUDA_VISIBLE_DEVICES=""
export OLLAMA_VULKAN=0
exec ollama serve

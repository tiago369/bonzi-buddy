#!/usr/bin/env bash
# On this machine, Ollama's CUDA backend crashes with the RTX 3050 Laptop
# ("CUDA error: device kernel image is invalid" - incompatibility between
# the installed 535 driver and the CUDA v12 kernels Ollama uses). Until
# that's fixed (e.g. by updating the NVIDIA driver), we run on CPU.
export CUDA_VISIBLE_DEVICES=""
export OLLAMA_VULKAN=0
exec ollama serve

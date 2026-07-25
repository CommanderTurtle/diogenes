# Ulysses golden production runtime profile

Captured read-only from the active Odysseus production runtime on 2026-07-25.
This is a compatibility oracle, not a lockfile and not permission to mutate the
production environment.

## Host and accelerator layers

| Layer | Observed value |
| --- | --- |
| WSL kernel | `6.18.35.2-microsoft-standard-WSL2` |
| NVIDIA KMD | `610.74` |
| NVIDIA UMD | CUDA `13.3` |
| `/usr/local/cuda` | `/usr/local/cuda-13.3` |
| `nvcc` | CUDA `13.3` build |
| GPU | NVIDIA GeForce RTX 5090 |
| VRAM | 34,190,458,880 bytes reported by Torch |
| Compute capability | `12.0` (`sm_120`) |

The driver/UMD capability, host toolkit, and Python wheel ABI are independent
compatibility dimensions. The working Python stack below is CUDA 13.0-built
despite the currently observed CUDA 13.3 host toolkit.

## Imported Python stack

| Component | Observed value |
| --- | --- |
| Environment | `/home/alienl/Odysseus/odysseus/.venv` |
| Python | `3.13.12` |
| vLLM | `0.23.0` |
| Torch | `2.11.0+cu130` |
| Torch CUDA build | `13.0` |
| Transformers | `5.12.1` |
| Triton | `3.6.0` |
| cuDNN wheel | `9.19.0.56` |
| cuDNN runtime API | `91900` |
| CUDA available | `true` |

Runtime imports are authoritative because this environment contains duplicate
distribution metadata. Package metadata alone is insufficient.

## Known-good live workload

- Model source: cached `cyankiwi/Agents-A1-AWQ-NVFP4` snapshot
  `e70647d3ecdd16e27614376ab6cbb23a683edb49`.
- Served model name: `compute1/Agents-A1-GPTQ-INT4-Sym`.
- Host/port: `0.0.0.0:8000`.
- MoE backend: `marlin`.
- Tensor parallel size: `1`.
- Maximum model length: `172032`.
- GPU memory utilization: `0.89`.
- KV cache dtype: `fp8`.
- Maximum sequences: `2`.
- Tool parser: `qwen3_coder`.
- Reasoning parser: `qwen3`.
- Automatic tool choice and remote model code are enabled.
- vLLM swap space is forced to zero by Odysseus's existing guarded runner
  patch in `routes/cookbook_routes.py`.

The exact cached model path is machine state; Ulysses should store a model ID,
resolved revision, and constrained model root rather than hard-code that path.

## Candidate acceptance gates

A candidate environment cannot replace or retarget production unless it:

1. imports the recorded Python/CUDA stack without loader or ABI errors;
2. detects the RTX 5090 as `sm_120`;
3. starts the same pinned model revision with equivalent launch semantics;
4. passes model discovery, non-streaming and streaming generation;
5. exercises reasoning content and Qwen tool calls;
6. passes representative long-context and MoE generation;
7. records peak VRAM/RAM, TTFT, throughput, and output correctness;
8. meets an explicitly approved regression budget;
9. leaves the current `.venv` and service definition untouched;
10. retains a tested rollback path.

“Newer” vLLM, Torch, Transformers, Triton, CUDA, or cuDNN versions do not waive
these gates.

## ONNX Runtime CUDA loader finding

The production ONNX Runtime CUDA provider is not missing cuDNN. Its requested
`libcudnn.so.9` is present inside the production environment under the NVIDIA
wheel library tree. With that environment's
`site-packages/nvidia/*/lib` directories prepended to a new child process's
`LD_LIBRARY_PATH`, `ldd` resolves every provider dependency.

This is a process-start linker-path problem. It does not justify creating
versionless or cross-version `.so` symlinks, changing `/usr/lib`, modifying a
login shell, or normalizing the production environment.

Ulysses provides `scripts/with-wsl-cuda-libs.sh` as the scoped candidate
launcher. It:

1. resolves `ULYSSES_VENV` when explicitly supplied, otherwise the candidate's
   own `.venv` (an inherited `VIRTUAL_ENV` is deliberately ignored);
2. discovers its NVIDIA wheel library directories;
3. adds the host CUDA and WSL driver library roots when present;
4. validates the ONNX CUDA provider with `ldd`;
5. executes the requested command, defaulting to the candidate Uvicorn server.

The launcher has been syntax- and contract-tested only. An actual CUDA provider
session remains a post-download, GPU-release validation gate.

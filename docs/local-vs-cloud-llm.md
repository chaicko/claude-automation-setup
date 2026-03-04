# Local LLM vs Cloud API

## Default: Ollama (local)

```
MODEL_PROVIDER=ollama
OLLAMA_MODEL=qwen2.5:7b
```

**Why Ollama:**
- Zero API cost — runs entirely on your GTX 1060 6GB
- `qwen2.5:7b` at Q4_K_M quantization: ~4.5GB VRAM, ~15-25 tok/s
- Strong function-calling support (required for MCP tool use)
- Privacy: email/calendar content never leaves your home server
- Works offline

**Hardware fit:**
- GTX 1060 6GB VRAM → `qwen2.5:7b` fits with ~1.5GB headroom
- If you have less VRAM, try `qwen2.5:3b` (~2.2GB)
- 32GB RAM: plenty for model overhead + MCP subprocesses

## Fallback: Anthropic API

```
MODEL_PROVIDER=anthropic
ANTHROPIC_API_KEY=sk-ant-...
ANTHROPIC_MODEL=claude-sonnet-4-6
```

**When to use Anthropic:**
- Testing on a dev laptop (no GPU)
- Tasks requiring stronger reasoning (complex multi-step analysis)
- Debugging: verify a behavior is the LLM vs your code

**Cost note:** Each agent cycle processes up to 5 emails + calendar. At ~2K tokens/email with claude-sonnet-4-6 pricing, expect ~$0.01-0.05 per cycle. With 96 cycles/day, budget ~$1-5/day if running Anthropic continuously.

## Switching providers

Edit `.env` and restart the agent:

```bash
# Switch to Anthropic
echo "MODEL_PROVIDER=anthropic" >> .env
systemctl --user restart claude-agent.timer

# Switch back to Ollama
sed -i 's/MODEL_PROVIDER=anthropic/MODEL_PROVIDER=ollama/' .env
systemctl --user restart claude-agent.timer
```

## Model quality comparison

| Task | Qwen 2.5 7B | Claude Sonnet |
|------|------------|---------------|
| Email triage | Good | Excellent |
| Draft short reply | Good | Excellent |
| Multi-step reasoning | Adequate | Excellent |
| Tool calling | Good | Excellent |
| Speed (local) | 15-25 tok/s | ~100 tok/s (API) |
| Cost | Free | ~$0.003/1K tok |

For async email/calendar processing with 15-minute cycles, Qwen 2.5 7B quality is sufficient in practice.

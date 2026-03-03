#!/usr/bin/env python3
"""
═══════════════════════════════════════════════════════════════════════════════
FORTRESS PRIME — PERSONA TEMPLATE SYSTEM
═══════════════════════════════════════════════════════════════════════════════
Foundation for the Council of Giants multi-persona alpha generation system.

Each persona has:
- Worldview (philosophy/thesis)
- Bias (long/short preferences)
- Data sources (where to hunt intelligence)
- Trigger events (what makes them act)
- Vector collection (Qdrant storage)
- Godhead prompt (system prompt defining personality)

Usage:
    # Create persona
    jordi = Persona.load("jordi")
    
    # Query on event
    opinion = jordi.analyze_event("Fed cuts rates 50bps")
    
    # Debate between personas
    debate = jordi.debate_with(raoul, "Is Bitcoin bullish?")
    
    # Council consensus
    council = Council([jordi, raoul, lyn, vol_trader, ...])
    consensus = council.vote_on("Fed rate cut")

Author: Fortress Prime Architect
Version: 1.0.0
═══════════════════════════════════════════════════════════════════════════════
"""

import os
import json
import requests
from typing import List, Dict, Optional, Any
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from concurrent.futures import ThreadPoolExecutor, as_completed
from collections import defaultdict
import threading
import time
import logging

log = logging.getLogger("council")

# =============================================================================
# Configuration
# =============================================================================

QDRANT_URL = os.getenv("QDRANT_URL", "http://localhost:6333")
QDRANT_API_KEY = os.getenv("QDRANT_API_KEY", "")
QDRANT_HEADERS = {"api-key": QDRANT_API_KEY} if QDRANT_API_KEY else {}

# Embeddings go through Nginx LB (distributes across all 4 nodes)
EMBED_URL = os.getenv("EMBED_URL", "http://192.168.0.100/api/embeddings")
# Fallback: direct Ollama on Captain
OLLAMA_URL = os.getenv("OLLAMA_URL", "http://localhost:11434")
EMBED_MODEL = "nomic-embed-text"

# Reasoning: use Nginx LB to spread across 4 Hydra heads
NGINX_LB = os.getenv("NGINX_LB_URL", "http://192.168.0.100")
REASON_MODEL = os.getenv("HYDRA_MODEL", "deepseek-r1:70b")

# OpenAI God Head (cloud reasoning — non-sensitive only, per Constitution Art I §1.1)
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "")
OPENAI_MODEL = os.getenv("OPENAI_MODEL", "gpt-4o")

_OPENAI_PREFIXES = ("gpt-", "o1-", "o3-", "o4-", "chatgpt-")


def _is_openai_model(model: str) -> bool:
    return any(model.lower().startswith(p) for p in _OPENAI_PREFIXES)

# Direct Hydra head endpoints for parallel fan-out (bypasses LB for max throughput)
_HYDRA_CANDIDATES = [
    os.getenv("HYDRA_HEAD_1", "http://192.168.0.100:11434"),
    os.getenv("HYDRA_HEAD_2", "http://192.168.0.104:11434"),
    os.getenv("HYDRA_HEAD_3", "http://192.168.0.105:11434"),
    os.getenv("HYDRA_HEAD_4", "http://192.168.0.106:11434"),
]


def _probe_hydra_heads() -> list:
    """Return only reachable Hydra heads, falling back to LB if none respond."""
    live = []
    for url in _HYDRA_CANDIDATES:
        try:
            r = requests.get(f"{url}/api/tags", timeout=2)
            if r.status_code == 200:
                live.append(url)
        except Exception:
            pass
    if not live:
        live = [NGINX_LB]
    return live


HYDRA_HEADS = _probe_hydra_heads()

PERSONAS_DIR = "/home/admin/Fortress-Prime/personas"
os.makedirs(PERSONAS_DIR, exist_ok=True)


# =============================================================================
# Enums
# =============================================================================

class Signal(Enum):
    """Trading signal from persona."""
    STRONG_BUY = "STRONG_BUY"
    BUY = "BUY"
    NEUTRAL = "NEUTRAL"
    SELL = "SELL"
    STRONG_SELL = "STRONG_SELL"


class Archetype(Enum):
    """Persona archetype classification."""
    TECH_BULL = "Tech Bull"
    MACRO_CYCLES = "Macro Cycles"
    SOUND_MONEY = "Sound Money"
    VOL_TRADER = "Vol Trader"
    FED_WATCHER = "Fed Watcher"
    REAL_ESTATE = "Real Estate"
    PERMABEAR = "Permabear"
    BLACK_SWAN = "Black Swan Hunter"
    OPERATOR = "Operator"


# =============================================================================
# Data Classes
# =============================================================================

@dataclass
class Opinion:
    """Structured opinion from a persona on an event."""
    persona_name: str
    event: str
    signal: Signal
    conviction: float  # 0.0 to 1.0
    reasoning: str
    assets: List[str]  # Affected assets (BTC, SPX, GOLD, etc.)
    timestamp: str
    risk_factors: List[str] = field(default_factory=list)
    catalysts: List[str] = field(default_factory=list)
    
    def to_dict(self) -> Dict:
        return {
            "persona": self.persona_name,
            "event": self.event,
            "signal": self.signal.value,
            "conviction": self.conviction,
            "reasoning": self.reasoning,
            "assets": self.assets,
            "timestamp": self.timestamp,
            "risk_factors": self.risk_factors,
            "catalysts": self.catalysts,
        }


@dataclass
class Debate:
    """Dialectic between two personas."""
    topic: str
    persona_a: str
    persona_b: str
    opinion_a: Opinion
    opinion_b: Opinion
    synthesis: Optional[str] = None  # Synthesized view
    timestamp: str = field(default_factory=lambda: datetime.now().isoformat())
    
    def agreement_score(self) -> float:
        """Calculate agreement between personas (0.0 = opposite, 1.0 = identical)."""
        # Signal alignment
        signal_map = {
            Signal.STRONG_BUY: 2,
            Signal.BUY: 1,
            Signal.NEUTRAL: 0,
            Signal.SELL: -1,
            Signal.STRONG_SELL: -2,
        }
        
        diff = abs(signal_map[self.opinion_a.signal] - signal_map[self.opinion_b.signal])
        signal_score = 1.0 - (diff / 4.0)  # Normalize to 0-1
        
        # Conviction alignment
        conv_diff = abs(self.opinion_a.conviction - self.opinion_b.conviction)
        conv_score = 1.0 - conv_diff
        
        return (signal_score + conv_score) / 2.0


# =============================================================================
# Persona Class
# =============================================================================

@dataclass
class Persona:
    """
    Individual market persona with unique worldview and bias.
    
    Attributes:
        name: Display name (e.g., "The Jordi")
        slug: URL-safe identifier (e.g., "jordi")
        archetype: Persona type (Tech Bull, Permabear, etc.)
        worldview: Core philosophy/thesis
        bias: Long/short preferences
        data_sources: Where persona hunts intelligence
        trigger_events: Events that make persona act
        vector_collection: Qdrant collection name
        godhead_prompt: System prompt defining personality
    """
    name: str
    slug: str
    archetype: Archetype
    worldview: str
    bias: List[str]
    data_sources: List[str]
    trigger_events: List[str]
    vector_collection: str
    godhead_prompt: str
    god_head_domain: Optional[str] = None
    
    # Metadata
    created_at: str = field(default_factory=lambda: datetime.now().isoformat())
    vectors_count: int = 0
    last_updated: Optional[str] = None
    
    def save(self):
        """Save persona config to disk."""
        filepath = os.path.join(PERSONAS_DIR, f"{self.slug}.json")
        data = self.__dict__.copy()
        # Convert enum to value for JSON serialization
        if isinstance(data.get('archetype'), Archetype):
            data['archetype'] = data['archetype'].value
        with open(filepath, 'w') as f:
            json.dump(data, f, indent=2)
    
    @classmethod
    def load(cls, slug: str) -> 'Persona':
        """Load persona from disk."""
        filepath = os.path.join(PERSONAS_DIR, f"{slug}.json")
        with open(filepath, 'r') as f:
            data = json.load(f)
        
        # Convert archetype string back to enum
        if isinstance(data['archetype'], str):
            data['archetype'] = Archetype(data['archetype'])
        
        if 'god_head_domain' not in data:
            data['god_head_domain'] = None
        
        return cls(**data)
    
    @classmethod
    def list_all(cls) -> List[str]:
        """List all available persona slugs."""
        if not os.path.exists(PERSONAS_DIR):
            return []
        return [f.replace('.json', '') for f in os.listdir(PERSONAS_DIR) if f.endswith('.json')]
    
    def get_embedding(self, text: str) -> Optional[List[float]]:
        """Generate embedding via Nginx LB (distributes across cluster)."""
        try:
            resp = requests.post(
                EMBED_URL,
                json={"model": EMBED_MODEL, "prompt": text},
                timeout=30,
            )
            resp.raise_for_status()
            return resp.json().get("embedding")
        except Exception:
            # Fallback to direct Ollama on Captain
            try:
                resp = requests.post(
                    f"{OLLAMA_URL}/api/embeddings",
                    json={"model": EMBED_MODEL, "prompt": text},
                    timeout=30,
                )
                resp.raise_for_status()
                return resp.json().get("embedding")
            except Exception as e:
                log.error("Embedding failed on both LB and local: %s", e)
                return None
    
    def search_knowledge(self, query: str, top_k: int = 5) -> List[Dict]:
        """
        Two-pass retrieval:
          1. Qdrant ANN search — fast approximate top-20
          2. NVIDIA reranker — cosine rerank to precise top-k
        Falls back to ANN-only if reranker is unavailable.
        """
        query_embedding = self.get_embedding(query)
        if not query_embedding:
            return []
        
        try:
            # Pass 1: ANN search with 4x over-fetch for reranking headroom
            ann_limit = max(top_k * 4, 20)
            resp = requests.post(
                f"{QDRANT_URL}/collections/{self.vector_collection}/points/search",
                headers=QDRANT_HEADERS,
                json={
                    "vector": query_embedding,
                    "limit": ann_limit,
                    "with_payload": True,
                },
                timeout=30,
            )
            
            if resp.status_code != 200:
                return []
            
            ann_results = resp.json().get("result", [])
            if not ann_results:
                return []
            
            # Pass 2: Rerank via NVIDIA reranker for precise top-k
            try:
                from nvidia_reranker import rerank_documents
                docs_for_rerank = [
                    {"text": hit.get("payload", {}).get("text", ""), "_hit": hit}
                    for hit in ann_results
                    if hit.get("payload", {}).get("text")
                ]
                if docs_for_rerank:
                    reranked = rerank_documents(query, docs_for_rerank, top_k=top_k)
                    return [d["_hit"] for d in reranked if "_hit" in d]
            except Exception as rerank_err:
                log.debug("Reranker unavailable, using ANN results: %s", rerank_err)
            
            return ann_results[:top_k]
        
        except Exception as e:
            print(f"Search error: {e}")
            return []
    
    def analyze_event(
        self,
        event: str,
        context: Optional[str] = None,
        hydra_url: Optional[str] = None,
        model_override: Optional[str] = None,
    ) -> Opinion:
        """
        Analyze market event through persona's lens.
        
        Args:
            event: Market event description (e.g., "Fed cuts rates 50bps")
            context: Additional context (optional)
            hydra_url: Direct Ollama URL for this request (for parallel fan-out).
                       If None, uses Nginx LB to auto-distribute.
        
        Returns:
            Opinion object with signal, conviction, reasoning
        """
        # Search persona's knowledge base
        knowledge = self.search_knowledge(event, top_k=3)
        
        # Build context from knowledge
        knowledge_context = "\n\n".join([
            f"[Source {i+1}]: {hit['payload'].get('text', '')[:500]}"
            for i, hit in enumerate(knowledge)
        ])
        
        if self.slug == "jordi":
            try:
                from src.covariance_engine import get_correlation_context
                corr_ctx = get_correlation_context()
                if corr_ctx:
                    knowledge_context += "\n\n" + corr_ctx
            except Exception as _corr_exc:
                log.debug(f"Covariance engine unavailable for Jordi: {_corr_exc}")
        
        # Build prompt for reasoning model
        system_prompt = f"""{self.godhead_prompt}

You are analyzing a market event. Based on your worldview and the provided context,
generate a structured opinion.

Your worldview:
{self.worldview}

Your biases:
{', '.join(self.bias)}

Relevant knowledge from your database:
{knowledge_context}
"""
        
        user_prompt = f"""Event: {event}

{f"Additional Context: {context}" if context else ""}

Analyze this event and provide:
1. Signal: STRONG_BUY, BUY, NEUTRAL, SELL, or STRONG_SELL
2. Conviction: 0.0 to 1.0 (how confident are you?)
3. Reasoning: Why this is your view (2-3 sentences)
4. Affected Assets: List of assets (BTC, SPX, GOLD, DXY, etc.)
5. Risk Factors: What could prove you wrong?
6. Catalysts: What would confirm your thesis?

Format as JSON:
{{
  "signal": "BUY",
  "conviction": 0.85,
  "reasoning": "...",
  "assets": ["BTC", "QQQ"],
  "risk_factors": ["..."],
  "catalysts": ["..."]
}}
"""
        
        # Pick the inference URL: explicit hydra head > LB > local fallback
        infer_url = hydra_url or NGINX_LB or OLLAMA_URL
        use_model = model_override or REASON_MODEL

        try:
            result_text = None

            if self.god_head_domain and not model_override:
                try:
                    try:
                        from src.god_head_router import route as god_head_route
                    except ImportError:
                        from god_head_router import route as god_head_route
                    gh_result = god_head_route(
                        domain=self.god_head_domain,
                        prompt=f"{system_prompt}\n\n{user_prompt}",
                        context=knowledge_context,
                        temperature=0.3,
                    )
                    result_text = gh_result.get("response", "")
                    log.info(
                        f"{self.name}: God-Head {gh_result.get('provider','?')} "
                        f"(fallback={gh_result.get('fallback_used', False)})"
                    )
                except Exception as gh_exc:
                    log.warning(f"{self.name}: God-Head routing failed, using local: {gh_exc}")

            if not result_text:
                if _is_openai_model(use_model):
                    result_text = self._call_openai(system_prompt, user_prompt, use_model)
                else:
                    result_text = self._call_ollama(
                        infer_url, system_prompt, user_prompt, use_model)

            if not result_text:
                return self._fallback_opinion(event)

            import re
            json_match = re.search(r'\{.*\}', result_text, re.DOTALL)
            if json_match:
                result_json = json.loads(json_match.group(0))
            else:
                return self._fallback_opinion(event)

            signal_str = result_json.get("signal", "NEUTRAL")
            signal = Signal[signal_str] if signal_str in Signal.__members__ else Signal.NEUTRAL

            return Opinion(
                persona_name=self.name,
                event=event,
                signal=signal,
                conviction=min(max(float(result_json.get("conviction", 0.5)), 0.0), 1.0),
                reasoning=result_json.get("reasoning", "No reasoning provided"),
                assets=result_json.get("assets", []),
                timestamp=datetime.now().isoformat(),
                risk_factors=result_json.get("risk_factors", []),
                catalysts=result_json.get("catalysts", []),
            )

        except Exception as e:
            print(f"Analysis error: {e}")
            return self._fallback_opinion(event)

    # ── OpenAI God Head inference (cloud, non-sensitive) ──

    @staticmethod
    def _call_openai(system_prompt: str, user_prompt: str,
                     model: str) -> Optional[str]:
        """Call OpenAI chat completions API. Key from env (never hardcoded)."""
        if not OPENAI_API_KEY:
            log.error("OPENAI_API_KEY not set — cannot use God Head model %s", model)
            return None
        try:
            resp = requests.post(
                "https://api.openai.com/v1/chat/completions",
                headers={
                    "Authorization": f"Bearer {OPENAI_API_KEY}",
                    "Content-Type": "application/json",
                },
                json={
                    "model": model,
                    "messages": [
                        {"role": "system", "content": system_prompt},
                        {"role": "user", "content": user_prompt},
                    ],
                    "temperature": 0.7,
                    "max_tokens": 800,
                },
                timeout=120,
            )
            if resp.status_code != 200:
                log.error("OpenAI %s returned %d: %s",
                          model, resp.status_code, resp.text[:200])
                return None
            return resp.json()["choices"][0]["message"]["content"]
        except Exception as e:
            log.error("OpenAI call failed: %s", e)
            return None

    # ── Ollama inference (local cluster) ──

    @staticmethod
    def _call_ollama(infer_url: str, system_prompt: str, user_prompt: str,
                     model: str) -> Optional[str]:
        """Call Ollama /api/generate on local cluster."""
        timeout = 300 if "70b" in model.lower() else 90
        try:
            resp = requests.post(
                f"{infer_url}/api/generate",
                json={
                    "model": model,
                    "prompt": f"{system_prompt}\n\n{user_prompt}",
                    "stream": False,
                    "options": {
                        "temperature": 0.7,
                        "num_predict": 500,
                    },
                },
                timeout=timeout,
            )
            if resp.status_code != 200:
                return None
            return resp.json().get("response", "{}")
        except Exception as e:
            log.error("Ollama call failed on %s: %s", infer_url, e)
            return None
    
    def _fallback_opinion(self, event: str) -> Opinion:
        """Fallback neutral opinion when analysis fails."""
        return Opinion(
            persona_name=self.name,
            event=event,
            signal=Signal.NEUTRAL,
            conviction=0.5,
            reasoning="Unable to analyze event - insufficient data or model error",
            assets=[],
            timestamp=datetime.now().isoformat(),
        )
    
    def debate_with(self, other: 'Persona', topic: str) -> Debate:
        """
        Debate a topic with another persona.
        
        Returns:
            Debate object with both opinions and optional synthesis
        """
        # Both personas analyze the same topic
        opinion_self = self.analyze_event(topic)
        opinion_other = other.analyze_event(topic)
        
        debate = Debate(
            topic=topic,
            persona_a=self.name,
            persona_b=other.name,
            opinion_a=opinion_self,
            opinion_b=opinion_other,
        )
        
        # Optional: Generate synthesis (thesis vs antithesis → synthesis)
        # This could call a "meta-agent" to reconcile the two views
        
        return debate


# =============================================================================
# Council Class (Multi-Persona Consensus)
# =============================================================================

class Council:
    """
    Collection of personas that vote on market events to generate consensus.
    
    Implements "wisdom of crowds" by aggregating diverse opinions.
    Uses Hydra fan-out: 9 personas distributed across 4 DGX Spark nodes
    via ThreadPoolExecutor for ~4x speedup over sequential execution.
    """
    
    def __init__(self, personas: List[Persona]):
        self.personas = personas
    
    def vote_on(self, event: str, context: Optional[str] = None,
                parallel: bool = True, model: Optional[str] = None) -> Dict[str, Any]:
        """
        All personas vote on an event — in parallel across the Hydra cluster.
        
        Args:
            event: Market event to analyze
            context: Additional context
            parallel: If True (default), fan out across 4 Hydra heads
                      using ThreadPoolExecutor. If False, run sequentially.
            model: Override reasoning model (e.g. "qwen2.5:7b" for fast,
                   "deepseek-r1:70b" for deep). Defaults to REASON_MODEL.
        
        Returns:
            Consensus dict with signals, conviction, breakdown, opinions.
        """
        use_model = model or REASON_MODEL
        is_cloud = _is_openai_model(use_model)
        num_heads = len(HYDRA_HEADS)

        if is_cloud:
            mode = f"GODHEAD ({use_model})"
        elif parallel:
            mode = f"HYDRA x{num_heads} parallel"
        else:
            mode = "sequential"

        print(f"🏛️  Council voting on: {event}")
        print(f"   Mode: {mode} | Personas: {len(self.personas)} | Model: {use_model}")

        opinions = []
        t0 = time.time()

        if is_cloud:
            opinions = self._vote_cloud_parallel(event, context, use_model)
        elif parallel and num_heads > 1:
            opinions = self._vote_parallel(event, context, use_model)
        else:
            opinions = self._vote_sequential(event, context, use_model)
        
        elapsed = time.time() - t0
        print(f"   All {len(opinions)} votes received in {elapsed:.1f}s")
        
        # Conviction-weighted consensus algorithm
        signal_counts = {signal: 0 for signal in Signal}
        signal_weights = {
            Signal.STRONG_BUY: 1.0, Signal.BUY: 0.5,
            Signal.NEUTRAL: 0.0,
            Signal.SELL: -0.5, Signal.STRONG_SELL: -1.0,
        }
        total_conviction = 0.0
        weighted_score = 0.0

        for op in opinions:
            signal_counts[op.signal] += 1
            total_conviction += op.conviction
            weighted_score += signal_weights.get(op.signal, 0) * op.conviction

        n = len(opinions)
        avg_conviction = total_conviction / n

        # Net score: conviction-weighted directional strength (-1.0 to +1.0)
        net_score = weighted_score / n
        if net_score >= 0.4:
            consensus_signal = Signal.STRONG_BUY
        elif net_score >= 0.15:
            consensus_signal = Signal.BUY
        elif net_score > -0.15:
            consensus_signal = Signal.NEUTRAL
        elif net_score > -0.4:
            consensus_signal = Signal.SELL
        else:
            consensus_signal = Signal.STRONG_SELL

        bullish = signal_counts[Signal.STRONG_BUY] + signal_counts[Signal.BUY]
        bearish = signal_counts[Signal.STRONG_SELL] + signal_counts[Signal.SELL]
        majority_signal = max(signal_counts, key=signal_counts.get)
        agreement_rate = signal_counts[majority_signal] / n
        dissenters = [op for op in opinions if op.signal != consensus_signal]

        return {
            "event": event,
            "timestamp": datetime.now().isoformat(),
            "consensus_signal": consensus_signal.value,
            "consensus_conviction": round(avg_conviction, 4),
            "net_score": round(net_score, 4),
            "bullish_count": bullish,
            "bearish_count": bearish,
            "neutral_count": signal_counts[Signal.NEUTRAL],
            "total_voters": n,
            "agreement_rate": round(agreement_rate, 4),
            "opinions": [op.to_dict() for op in opinions],
            "dissenters": [op.to_dict() for op in dissenters],
            "signal_breakdown": {s.value: c for s, c in signal_counts.items()},
            "mode": mode,
            "elapsed_seconds": round(elapsed, 1),
        }
    
    def _vote_parallel(self, event: str, context: Optional[str],
                       model: str) -> List[Opinion]:
        """
        Task-stealing parallel fan-out across Hydra heads.

        Instead of rigid waves that wait for the slowest node, this uses a
        shared work queue. Each node pulls the next persona as soon as it
        finishes. Fast nodes (Captain, Muscle ~5s) naturally handle more
        personas than slower nodes (Ocular, Sovereign ~40s).
        """
        import queue
        num_heads = len(HYDRA_HEADS)
        work_q: queue.Queue = queue.Queue()
        for persona in self.personas:
            work_q.put(persona)

        opinions: list = []
        lock = threading.Lock()

        def _worker(head_url: str):
            head_name = head_url.split("//")[1].split(":")[0]
            count = 0
            while True:
                try:
                    persona = work_q.get_nowait()
                except queue.Empty:
                    break
                t0 = time.time()
                print(f"   ⚡ {persona.name} → {head_name}")
                try:
                    opinion = persona.analyze_event(
                        event, context=context, hydra_url=head_url,
                        model_override=None if persona.god_head_domain else model)
                    elapsed = time.time() - t0
                    print(f"   ✓ {persona.name} ({opinion.signal.value}, "
                          f"{elapsed:.1f}s) ← {head_name}")
                except Exception as e:
                    elapsed = time.time() - t0
                    log.error("   ✗ %s failed on %s: %s", persona.name,
                              head_name, e)
                    opinion = Opinion(
                        persona_name=persona.name, event=event,
                        signal=Signal.NEUTRAL, conviction=0.5,
                        reasoning=f"Hydra inference error: {str(e)[:60]}",
                        assets=[], timestamp=datetime.now().isoformat(),
                    )
                with lock:
                    opinions.append(opinion)
                count += 1
            print(f"   🏁 {head_name} completed {count} personas")

        print(f"   Task-steal mode: {len(self.personas)} personas → "
              f"{num_heads} heads")
        threads = []
        for head_url in HYDRA_HEADS:
            t = threading.Thread(target=_worker, args=(head_url,),
                                 daemon=True)
            t.start()
            threads.append(t)
        for t in threads:
            t.join()

        return opinions
    
    def _vote_cloud_parallel(self, event: str, context: Optional[str],
                             model: str) -> List[Opinion]:
        """
        Parallel fan-out against a cloud API (OpenAI God Head).
        Uses ThreadPoolExecutor with 4 concurrent threads to stay within
        rate limits while still getting ~4x speedup vs sequential.
        """
        opinions: list = []
        lock = threading.Lock()

        def _query_persona(persona: Persona) -> None:
            t0 = time.time()
            print(f"   ⚡ {persona.name} → {model}")
            try:
                effective_model = None if persona.god_head_domain else model
                opinion = persona.analyze_event(
                    event, context=context, model_override=effective_model)
                elapsed = time.time() - t0
                print(f"   ✓ {persona.name} ({opinion.signal.value}, "
                      f"{elapsed:.1f}s) ← {persona.god_head_domain or model}")
            except Exception as e:
                log.error("   ✗ %s failed on %s: %s", persona.name, model, e)
                opinion = Opinion(
                    persona_name=persona.name, event=event,
                    signal=Signal.NEUTRAL, conviction=0.5,
                    reasoning=f"God Head inference error: {str(e)[:60]}",
                    assets=[], timestamp=datetime.now().isoformat(),
                )
            with lock:
                opinions.append(opinion)

        with ThreadPoolExecutor(max_workers=4) as pool:
            pool.map(_query_persona, self.personas)

        return opinions

    def _vote_sequential(self, event: str, context: Optional[str],
                         model: str) -> List[Opinion]:
        """Sequential voting through Nginx LB (auto-distributes)."""
        opinions = []
        for persona in self.personas:
            print(f"   - Querying {persona.name}...")
            effective_model = None if persona.god_head_domain else model
            opinion = persona.analyze_event(
                event, context=context, model_override=effective_model)
            opinions.append(opinion)
        return opinions
    
    def get_consensus_score(self, asset: str, opinions: List[Opinion]) -> float:
        """
        Calculate consensus score for a specific asset (0.0 = bearish, 1.0 = bullish).
        """
        signal_weights = {
            Signal.STRONG_SELL: -1.0,
            Signal.SELL: -0.5,
            Signal.NEUTRAL: 0.0,
            Signal.BUY: 0.5,
            Signal.STRONG_BUY: 1.0,
        }
        
        relevant_opinions = [op for op in opinions if asset in op.assets]
        if not relevant_opinions:
            return 0.5  # Neutral if no opinions on asset
        
        weighted_sum = sum(
            signal_weights[op.signal] * op.conviction
            for op in relevant_opinions
        )
        
        return (weighted_sum / len(relevant_opinions) + 1.0) / 2.0  # Normalize to 0-1


# =============================================================================
# Example Usage
# =============================================================================

if __name__ == "__main__":
    print("="*70)
    print("  FORTRESS PRIME — PERSONA TEMPLATE SYSTEM")
    print("="*70)
    print()
    
    # Example: Load existing Jordi persona
    try:
        jordi = Persona.load("jordi")
        print(f"✅ Loaded persona: {jordi.name}")
        print(f"   Archetype: {jordi.archetype.value}")
        print(f"   Vector collection: {jordi.vector_collection}")
        print(f"   Vectors: {jordi.vectors_count}")
    except FileNotFoundError:
        print("⚠️  Jordi persona not found. Create it first.")
        print("   See: src/create_personas.py")
    
    print()
    print("="*70)
    print("  Next steps:")
    print("  1. Create persona configs: python src/create_personas.py")
    print("  2. Test single persona: python src/persona_template.py")
    print("  3. Test council vote: python src/test_council.py")
    print("="*70)

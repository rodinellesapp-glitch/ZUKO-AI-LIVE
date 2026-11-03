"""LiteLLM transport for ZUKO text generation; no tools or fallback phrases."""
from __future__ import annotations

import asyncio
import inspect
import json
import os
import re
import threading
from pathlib import Path
import sys
import time
from urllib.parse import urlparse
from live_platform_adapter import safe_name

GEMINI_MAX_OUTPUT_TOKENS = 512
GEMINI_3_REASONING_EFFORT = "low"


class GenerationCancelled(RuntimeError):
    pass


class ProviderDiagnosticError(RuntimeError):
    """Safe, structured failure raised when a provider response cannot be used."""
    def __init__(self, code, category, stage, *, response_metadata=None):
        super().__init__(code)
        self.diagnostic_code = code
        self.diagnostic_category = category
        self.diagnostic_stage = stage
        self.response_metadata = dict(response_metadata or {})


def generation_error_diagnostics(error, *, stage='provider_request', elapsed_ms=0.0):
    """Return allowlisted error metadata only; never include exception text."""
    error_type = type(error).__name__
    error_module = type(error).__module__
    diagnostic_stage = getattr(error, 'diagnostic_stage', stage)
    code_value = getattr(error, 'diagnostic_code', None)
    http_status = None
    response = getattr(error, 'response', None)
    status_values = (getattr(error, 'status_code', None),
                     getattr(response, 'status_code', None),
                     getattr(error, 'code', None))
    for value in status_values:
        if isinstance(value, int) and 100 <= value <= 599:
            http_status = value
            break
    if code_value is None:
        allowed_codes={'UNAUTHENTICATED','PERMISSION_DENIED','RESOURCE_EXHAUSTED',
                       'INVALID_ARGUMENT','DEADLINE_EXCEEDED','NOT_FOUND','UNAVAILABLE',
                       'INTERNAL','FAILED_PRECONDITION','CANCELLED'}
        for value in (getattr(error, 'error_code', None), getattr(error, 'code', None)):
            candidate=value if isinstance(value,str) else getattr(value,'name',None)
            if isinstance(candidate,str) and candidate.upper() in allowed_codes:
                code_value = candidate.upper()
                break
    if code_value is None and isinstance(error, ValueError):
        # Presenter/parser errors use stable codes; never persist arbitrary
        # exception text because it may contain generated or user content.
        for candidate in getattr(error, 'args', ())[:1]:
            if isinstance(candidate, str) and re.fullmatch(
                    r'(?:V3|CONTENT|EMPTY|FORMATTED|LOCAL_AI)_[A-Z0-9_]{1,64}', candidate):
                code_value = candidate
                break
    type_key = (error_module + '.' + error_type).lower()
    if getattr(error, 'diagnostic_category', None):
        category = error.diagnostic_category
    elif (error_type in {'TimeoutError', 'Timeout', 'ReadTimeout', 'ConnectTimeout'}
          or 'timeout' in type_key or code_value == 'DEADLINE_EXCEEDED' or http_status == 408):
        category = 'TIMEOUT'
    elif (http_status in {401, 403} or code_value in {'UNAUTHENTICATED','PERMISSION_DENIED'}
          or 'authentication' in type_key or 'credentials' in type_key or 'google.auth' in type_key):
        category = 'AUTHENTICATION'
    elif (http_status is not None and (http_status == 429 or http_status >= 500 or 400 <= http_status < 500)
          or code_value in {'RESOURCE_EXHAUSTED','INVALID_ARGUMENT','NOT_FOUND','UNAVAILABLE','INTERNAL','FAILED_PRECONDITION'}):
        category = 'SERVICE'
    elif any(token in type_key for token in ('ssl.', 'socket.', 'httpx.', 'httpcore.', 'aiohttp.', 'urllib3.', 'requests.', 'transport')):
        category = 'TRANSPORT'
    else:
        category = 'INTERNAL'
    return {'error_module': error_module, 'error_type': error_type,
            'error_code': code_value, 'http_status': http_status,
            'error_category': category, 'stage': diagnostic_stage,
            'elapsed_ms': round(max(0.0, float(elapsed_ms)), 2)}


class LiteLLMTransport:
    """One-attempt LiteLLM calls for Vertex Gemini Text and local Ollama."""

    def __init__(self, local_config, *, completion=None, async_completion=None,
                 gemini_model="gemini-2.5-flash-lite", vertex_project="jarvis-web-edee3",
                 vertex_location="global", gemini_provider="vertex_ai", local_timeout=14.0):
        self.local_config = dict(local_config)
        self.gemini_model = gemini_model
        self.vertex_project = vertex_project
        self.vertex_location = vertex_location
        if gemini_provider not in {"vertex_ai", "gemini"}:
            raise ValueError("GEMINI_PROVIDER_UNSUPPORTED")
        self.gemini_provider = gemini_provider
        self.local_timeout = float(local_timeout)
        self._completion = completion
        self._litellm_completion = None
        self._async_completion = async_completion
        self._warmup_thread = None
        self._ready_lock = threading.RLock()
        self._ready_state = 'INICIALIZANDO'
        self._ready_started = time.monotonic()
        self._ready_finished = None
        self._ready_error = None
        self.preparation_timings = {}
        self.last_response_metadata = {}

    @staticmethod
    def _field(value, name, default=None):
        if isinstance(value, dict):
            return value.get(name, default)
        return getattr(value, name, default)

    @classmethod
    def _response_metadata(cls, response, choice, elapsed_ms):
        usage = cls._field(response, "usage")
        completion_details = cls._field(usage, "completion_tokens_details")
        provider_fields = cls._field(choice, "provider_specific_fields", {}) or {}
        finish_reason = cls._field(choice, "finish_reason")
        native_finish_reason = cls._field(provider_fields, "native_finish_reason")
        reasoning_tokens = cls._field(usage, "reasoning_tokens")
        if reasoning_tokens is None:
            reasoning_tokens = cls._field(completion_details, "reasoning_tokens")
        return {
            "model": cls._field(response, "model"),
            "finish_reason": str(finish_reason) if finish_reason is not None else None,
            "native_finish_reason": (str(native_finish_reason)
                                     if native_finish_reason is not None else None),
            "prompt_tokens": cls._field(usage, "prompt_tokens"),
            "completion_tokens": cls._field(usage, "completion_tokens"),
            "total_tokens": cls._field(usage, "total_tokens"),
            "reasoning_tokens": reasoning_tokens,
            "elapsed_ms": round(max(0.0, float(elapsed_ms)), 2),
        }

    def _get_async_completion(self):
        if self._async_completion is None:
            isolated = Path(__file__).with_name("vendor") / "litellm_runtime"
            if isolated.is_dir() and str(isolated) not in sys.path:
                sys.path.insert(0, str(isolated))
            # Use the bundled cost map so importing LiteLLM never starts its
            # own background network retries.
            os.environ["LITELLM_LOCAL_MODEL_COST_MAP"] = "True"
            from litellm import acompletion
            self._async_completion = acompletion
        return self._async_completion

    def _get_completion(self):
        """Load the bundled synchronous LiteLLM entry point on demand.

        Ollama requests run inside the presenter's bounded generation worker.
        Using LiteLLM's synchronous entry point here avoids the vendored
        acompletion -> run_in_executor -> coroutine handoff that can abandon
        BaseLLMHTTPHandler.async_completion when its asyncio task is cancelled.
        """
        if self._completion is not None:
            return self._completion
        if self._litellm_completion is None:
            isolated = Path(__file__).with_name("vendor") / "litellm_runtime"
            if isolated.is_dir() and str(isolated) not in sys.path:
                sys.path.insert(0, str(isolated))
            os.environ["LITELLM_LOCAL_MODEL_COST_MAP"] = "True"
            from litellm import completion
            self._litellm_completion = completion
        return self._litellm_completion

    @staticmethod
    def _reject_awaitable(response):
        if inspect.isawaitable(response):
            close = getattr(response, "close", None)
            if callable(close):
                close()
            raise ProviderDiagnosticError(
                'ASYNC_RESULT_FROM_SYNC_PROVIDER', 'PROVIDER_PROTOCOL', 'provider_request')
        return response

    async def _run_one(self, kwargs, timeout, cancelled):
        completion = self._get_async_completion()
        deadline = time.monotonic() + timeout
        if cancelled and cancelled():
            raise GenerationCancelled("generation cancelled")
        if cancelled and cancelled():
            raise GenerationCancelled("generation cancelled")
        if time.monotonic() >= deadline:
            raise TimeoutError("LiteLLM initialization exceeded request deadline")
        task = asyncio.create_task(completion(**kwargs))
        try:
            while not task.done():
                if cancelled and cancelled():
                    task.cancel()
                    raise GenerationCancelled("generation cancelled")
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    task.cancel()
                    raise TimeoutError("LiteLLM request deadline exceeded")
                try:
                    await asyncio.wait_for(asyncio.shield(task), min(0.05, remaining))
                except asyncio.TimeoutError:
                    continue
            if cancelled and cancelled():
                raise GenerationCancelled("generation cancelled")
            return await task
        finally:
            if not task.done():
                task.cancel()
            # Drain cancellation so provider coroutine finalizers run before
            # asyncio.run tears down this request's event loop.
            await asyncio.gather(task, return_exceptions=True)

    def readiness_snapshot(self):
        with self._ready_lock:
            if self._ready_state == 'INICIALIZANDO' and time.monotonic()-self._ready_started >= 45:
                self._ready_state='INDISPONÍVEL'
                self._ready_error='PREPARATION_TIMEOUT'
                self._ready_finished=self._ready_started+45
            return {'state':self._ready_state,'finished':self._ready_finished,
                    'error_type':self._ready_error,'stages_ms':dict(self.preparation_timings),'elapsed_ms':round(((self._ready_finished or time.monotonic())-self._ready_started)*1000,2)}

    def warmup(self):
        with self._ready_lock:
            if self._warmup_thread is not None:return
            def load():
                error=None
                try:
                    if self._completion is None:
                        started=time.perf_counter()
                        self._get_async_completion()
                        self.preparation_timings['sdk_import']=round((time.perf_counter()-started)*1000,2)
                        # Load the synchronous Ollama route during the same
                        # preparation window so its first import cost is not
                        # charged to a live comment's generation deadline.
                        started=time.perf_counter()
                        self._get_completion()
                        self.preparation_timings['sdk_sync_import']=round((time.perf_counter()-started)*1000,2)
                        if self.gemini_provider == "vertex_ai":
                            # Vertex AI uses ADC; Google AI Studio uses its
                            # API key and must not probe or change a Cloud project.
                            started=time.perf_counter()
                            from litellm.main import vertex_chat_completion
                            vertex_chat_completion.get_access_token(credentials=None,project_id=self.vertex_project)
                            self.preparation_timings['sdk_adc']=round((time.perf_counter()-started)*1000,2)
                        else:
                            # No credentials are read, logged, or copied here;
                            # LiteLLM resolves the key from the process environment
                            # only when a separately authorized request is made.
                            pass
                except Exception as exc:error=type(exc).__name__
                with self._ready_lock:
                    if self._ready_state=='INICIALIZANDO':
                        self._ready_finished=time.monotonic()
                        self._ready_error=error
                        self._ready_state='INDISPONÍVEL' if error else 'PRONTO'
            self._warmup_thread=threading.Thread(target=load,name='zuko-provider-preparation',daemon=True)
            self._warmup_thread.start()

    def _call(self, kwargs, timeout, cancelled=None, *, synchronous=False):
        if cancelled and cancelled():
            raise GenerationCancelled("generation cancelled")
        started = time.perf_counter()
        if synchronous:
            response = self._reject_awaitable(self._get_completion()(**kwargs))
            if cancelled and cancelled():
                raise GenerationCancelled("generation cancelled")
        elif self._async_completion is not None or self._completion is None:
            response = asyncio.run(self._run_one(kwargs, timeout, cancelled))
        else:
            # Synchronous injection is used only by isolated deterministic tests.
            response = self._completion(**kwargs)
            if cancelled and cancelled():
                raise GenerationCancelled("generation cancelled")
        try:
            choices = getattr(response, "choices", None)
            if not choices:
                self.last_response_metadata = {}
                raise ProviderDiagnosticError('EMPTY_CHOICES', 'EMPTY_RESPONSE', 'response_extraction')
            metadata = self._response_metadata(
                response, choices[0], (time.perf_counter() - started) * 1000)
            self.last_response_metadata = metadata
            finish_reason = (metadata.get("finish_reason") or "").strip().lower()
            native_finish_reason = (metadata.get("native_finish_reason") or "").strip().upper()
            if finish_reason in {"length", "max_tokens"} or native_finish_reason == "MAX_TOKENS":
                requested_model = str(kwargs.get("model", ""))
                code = ('GEMINI_OUTPUT_TRUNCATED'
                        if requested_model.startswith(("gemini/", "vertex_ai/"))
                        else 'LOCAL_AI_OUTPUT_TRUNCATED')
                raise ProviderDiagnosticError(
                    code, 'TRUNCATED', 'provider_response',
                    response_metadata=metadata)
            text = getattr(getattr(choices[0], "message", None), "content", None)
            if text is None or (isinstance(text, str) and not text.strip()):
                raise ProviderDiagnosticError('EMPTY_CONTENT', 'EMPTY_RESPONSE', 'response_extraction')
            if not isinstance(text, str):
                raise ProviderDiagnosticError('CONTENT_NOT_TEXT', 'RESPONSE_EXTRACTION', 'response_extraction')
            return text.strip()
        except ProviderDiagnosticError:
            raise
        except Exception as error:
            raise ProviderDiagnosticError('RESPONSE_SHAPE_INVALID', 'RESPONSE_EXTRACTION',
                                         'response_extraction') from error

    @staticmethod
    def _timeout(timeout, fallback):
        try:
            value = float(timeout if timeout is not None else fallback)
        except (TypeError, ValueError):
            value = fallback
        return max(0.1, min(value, fallback))

    def local_response(self, data, system, *, timeout=None, cancelled=None,
                       correlation_id=""):
        options = self.local_config
        endpoint = str(options.get("url", "http://127.0.0.1:11435/api/generate"))
        parsed = urlparse(endpoint)
        if parsed.scheme != "http" or parsed.hostname != "127.0.0.1":
            raise ValueError("Ollama de ZUKO deve permanecer em loopback HTTP.")
        api_base = endpoint.split("/api/", 1)[0]
        deadline = self._timeout(timeout, min(self.local_timeout, float(options.get("timeout", 12))))
        kwargs = {
            "model": "ollama_chat/" + str(options["model"]),
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": json.dumps(data, ensure_ascii=False)},
            ],
            "api_base": api_base,
            "timeout": deadline,
            "num_retries": 0,
            "max_retries": 0,
            "stream": False,
            "temperature": 0.85,
            "max_tokens": int(options["num_predict"]),
            "think": bool(options.get("think", False)),
            "metadata": {"correlation_id": str(correlation_id), "component": "zuko",
                         "model": str(options["model"])},
        }
        # LiteLLM's Ollama chat adapter maps this to the top-level Ollama
        # /api/chat field. Keep the model resident for the configured interval.
        if options.get("keep_alive") is not None:
            kwargs["keep_alive"] = options["keep_alive"]
        # Presenter already isolates local generation in its bounded worker
        # thread. Calling LiteLLM's synchronous Ollama API avoids the bundled
        # acompletion executor coroutine leak on cancellation.
        return self._call(kwargs, deadline, cancelled, synchronous=True)

    def gemini_response(self, viewer_text, author, social_context, informal, returning,
                        global_context, system_instruction, *, timeout=8.0,
                        cancelled=None, correlation_id=""):
        turns = tuple(social_context or ())[-5:]
        context = " ".join(
            "Espectador: " + str(getattr(turn, "viewer_text", ""))[:720]
            + " ZUKO: " + str(getattr(turn, "jarvis_text", ""))[:180]
            for turn in turns
        )
        name = safe_name(author or "")[:48]
        payload = {
            "participante": name,
            "comentario_atual": str(viewer_text or "")[:1200],
            "contexto_deste_participante": context,
            "contexto_publico_live": str(global_context or "")[:3500],
            "informalidade": bool(informal),
            "retorno_apos_pausa": bool(returning),
        }
        model_id = self.gemini_model.removeprefix("vertex_ai/").removeprefix("gemini/")
        model = ("vertex_ai/" if self.gemini_provider == "vertex_ai" else "gemini/") + model_id
        deadline = self._timeout(timeout, 8.0)
        kwargs = {
            "model": model,
            "messages": [
                {"role": "system", "content": str(system_instruction or "")},
                {"role": "user", "content": json.dumps(payload, ensure_ascii=False)},
            ],
            "timeout": deadline,
            "num_retries": 0,
            "max_retries": 0,
            "stream": False,
            "max_tokens": GEMINI_MAX_OUTPUT_TOKENS,
            "metadata": {"correlation_id": str(correlation_id), "component": "zuko"},
        }
        if self.gemini_provider == "vertex_ai":
            kwargs["vertex_project"] = self.vertex_project
            kwargs["vertex_location"] = self.vertex_location
        # Google documents custom sampling parameters as unsupported from
        # Gemini 3.x. Omit temperature for those models instead of
        # relying on provider-side ignoring or receiving an API error.
        if not model_id.startswith("gemini-3."):
            kwargs["temperature"] = 0.3
        else:
            # Gemini 3.8 defaults to medium thinking; low is intended for
            # latency-sensitive conversational answers and frees output tokens.
            kwargs["reasoning_effort"] = GEMINI_3_REASONING_EFFORT
        return self._call(kwargs, deadline, cancelled)

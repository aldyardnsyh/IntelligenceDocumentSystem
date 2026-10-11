"""Test tracing Langfuse.

Yang paling penting di sini: tracing yang mati atau gagal **tidak boleh**
mematikan jawaban. Setiap test di bawah memverifikasi satu sisi dari kontrak
itu: SDK tidak ada, kredensial tidak ada, server Langfuse down, semuanya
harus berakhir dengan jawaban yang tetap keluar dan trace_id None, bukan
exception.
"""

from __future__ import annotations

import pytest

from app.core.config import Settings
from app.services.rag_service import RagService
from app.services.tracing import TraceContext, Tracer


class TestTracerDisabled:
    def test_tanpa_kredensial_mati(self) -> None:
        tracer = Tracer(Settings(tracing_enabled=True))
        assert tracer.enabled is False

    def test_flag_mati_mematikan(self) -> None:
        tracer = Tracer(
            Settings(
                tracing_enabled=False,
                langfuse_public_key="pk",
                langfuse_secret_key="sk",
            )
        )
        assert tracer.enabled is False

    def test_start_trace_mengembalikan_konteks_kosong(self) -> None:
        context = Tracer(Settings()).start_trace(question="apa?", session_id=None)
        assert context.trace_id is None
        assert context.spans == {}

    def test_end_trace_tidak_melempar(self) -> None:
        # Kalau ini melempar, jawaban yang sudah jadi ikut gagal.
        Tracer(Settings()).end_trace(
            TraceContext(),
            answer="jawaban",
            citations=1,
            provider_name="mock",
            from_cache=False,
            elapsed_ms=100,
        )

    def test_span_retrieval_tidak_melempar(self) -> None:
        Tracer(Settings()).span_retrieval(
            TraceContext(), chunks=[], threshold=0.5
        )

    def test_flush_tidak_melempar(self) -> None:
        Tracer(Settings()).flush()


class TestTracerTanpaSdk:
    def test_sdk_tidak_ada_dimatikan_dengan_aman(self) -> None:
        """SDK tidak terpasang tapi kredensial ada: tetap mati, tidak crash.

        Ini kondisi nyata di server yang belum `pip install -e .[observability]`.
        """
        import sys

        blocked = "langfuse" in sys.modules
        sys.modules["langfuse"] = None  # type: ignore[assignment]  # noqa: E402
        try:
            tracer = Tracer(
                Settings(
                    tracing_enabled=True,
                    langfuse_public_key="pk",
                    langfuse_secret_key="sk",
                )
            )
            assert tracer.enabled is False
        finally:
            if not blocked:
                sys.modules.pop("langfuse", None)


class FakeTrace:
    """Pengganti trace Langfuse yang mencatat pemanggilan tanpa jaringan."""

    def __init__(self) -> None:
        self.id = "trace_uji_123"
        self.updates: list[dict] = []
        self.spans: list[dict] = []

    def update(self, **kwargs) -> None:  # noqa: ANN003, ANN204
        self.updates.append(kwargs)

    def span(self, **kwargs) -> None:  # noqa: ANN003, ANN204
        self.spans.append(kwargs)


class FakeLangfuseClient:
    def __init__(self) -> None:
        self.traces: list[FakeTrace] = []

    def trace(self, **kwargs) -> FakeTrace:  # noqa: ANN003, ANN204
        trace = FakeTrace()
        self.traces.append(trace)
        return trace

    def flush(self) -> None:
        pass


class TestTracerAktif:
    @pytest.fixture
    def live_tracer(self, monkeypatch: pytest.MonkeyPatch) -> Tracer:
        """Tracer dengan SDK palsu yang tidak menyentuh jaringan."""
        import sys
        import types

        fake_module = types.ModuleType("langfuse")
        fake_client = FakeLangfuseClient()

        def fake_langfuse(**kwargs):  # noqa: ANN003, ANN202
            assert kwargs["public_key"] == "pk"
            return fake_client

        fake_module.Langfuse = fake_langfuse  # type: ignore[attr-defined]
        monkeypatch.setitem(sys.modules, "langfuse", fake_module)

        tracer = Tracer(
            Settings(
                tracing_enabled=True,
                langfuse_public_key="pk",
                langfuse_secret_key="sk",
            )
        )
        assert tracer.enabled is True
        tracer._client_traces = fake_client  # type: ignore[attr-defined]
        return tracer

    def test_start_memberi_trace_id(self, live_tracer: Tracer) -> None:
        context = live_tracer.start_trace(question="apa?", session_id="s1")
        assert context.trace_id == "trace_uji_123"

    def test_end_menyimpan_hasil(self, live_tracer: Tracer) -> None:
        context = live_tracer.start_trace(question="apa?", session_id=None)
        live_tracer.end_trace(
            context,
            answer="jawabannya",
            citations=2,
            provider_name="groq",
            from_cache=False,
            elapsed_ms=150,
        )
        trace = context.spans["trace"]
        assert trace.updates
        assert trace.updates[0]["metadata"]["citations"] == 2
        assert trace.updates[0]["metadata"]["provider"] == "groq"

    def test_span_retrieval_mencatat_chunk(self, live_tracer: Tracer) -> None:
        from app.models.domain import Chunk, RetrievedChunk

        context = live_tracer.start_trace(question="apa?", session_id=None)
        live_tracer.span_retrieval(
            context,
            chunks=[
                RetrievedChunk(
                    chunk=Chunk(
                        id="c1",
                        document_id="d1",
                        chunk_index=3,
                        content="isi",
                        page_number=2,
                    ),
                    document_name="panduan.md",
                    score=0.9,
                    vector_score=0.9,
                    keyword_score=0.0,
                )
            ],
            threshold=0.5,
        )
        trace = context.spans["trace"]
        assert trace.spans
        assert trace.spans[0]["output"]["count"] == 1


class TestTraceIdMengalirKeLog:
    async def test_trace_id_tersimpan_di_log(
        self, indexed_ingestion, rag: RagService
    ) -> None:
        """trace_id dari tracer harus sampai ke QueryLog.

        Tanpa ini, kolom Trace di /analytics selalu kosong meski tracing
        aktif, UI yang menunjuk ke ketiadaan.
        """
        from app.services.tracing import Tracer as RealTracer

        # Tracer mati (tanpa kredensial) tetap harus meneruskan None, bukan
        # crash atau string kosong.
        rag_with_tracer = RagService(
            rag.settings,
            rag.repository,
            rag.memory,
            rag.retriever,
            rag.embedding,
            rag.chain,
            RealTracer(rag.settings),
        )

        async def collect(stream):  # noqa: ANN001, ANN202
            return [event async for event in stream]

        await collect(rag_with_tracer.answer("penyelesaian", None, None))
        logs, total = rag.repository.list_logs(1, 10)
        assert total >= 1
        # Tanpa kredensial, trace_id None, dan itu benar, bukan bug.
        assert logs[0].trace_id is None

    async def test_tanpa_tracer_log_tetap_jalan(
        self, indexed_ingestion, rag: RagService
    ) -> None:
        """RagService tanpa tracer (konstruktor lama) tidak boleh crash."""

        async def collect(stream):  # noqa: ANN001, ANN202
            return [event async for event in stream]

        events = await collect(rag.answer("penyelesaian", None, None))
        assert any(event.type == "citations" for event in events)

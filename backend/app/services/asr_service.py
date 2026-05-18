from app.schemas import VoiceTextCommandRequest


class ASRService:
    """Placeholder ASR seam for Phase 4A. It deliberately does not load an ASR engine."""

    def transcribe_text_mock(self, request: VoiceTextCommandRequest) -> VoiceTextCommandRequest:
        return VoiceTextCommandRequest(
            text=request.text,
            source=request.source or "asr-text-mock",
            requested_by=request.requested_by,
        )


asr_service = ASRService()

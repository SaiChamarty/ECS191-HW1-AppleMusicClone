"""HTTP API. Run with: uvicorn similarity.api:app --port 8765"""

from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field, model_validator

from .service import SimilarityService, SongNotFound


class SimilarRequest(BaseModel):
    track_id: int | None = Field(default=None, description="iTunes trackId, if known")
    title: str | None = None
    artist: str | None = None
    country: str = Field(default="us", pattern=r"^[A-Za-z]{2}$", description="iTunes storefront, e.g. us, in, jp")
    limit: int = Field(default=10, ge=1, le=25)
    explain: bool = False

    @model_validator(mode="after")
    def _needs_song(self) -> "SimilarRequest":
        if self.track_id is None and not (self.title and self.title.strip()):
            raise ValueError("Provide track_id, or title (plus artist).")
        return self


state: dict[str, SimilarityService] = {}


@asynccontextmanager
async def lifespan(_: FastAPI):
    # The server grows the index in the background around each query.
    state["service"] = SimilarityService.load(expand=True)
    yield
    state.clear()


app = FastAPI(title="Sound-alike similarity service", version="1.0", lifespan=lifespan)


@app.get("/health")
def health() -> dict:
    return {"status": "ok", "tracks": len(state["service"].index)}


@app.get("/v1/tracks/{track_id}")
def get_track(track_id: int) -> dict:
    track = state["service"].index.by_id(track_id)
    if track is None:
        raise HTTPException(status_code=404, detail="Track is not indexed.")
    return track.to_api()


# Sync endpoint: FastAPI runs it in a worker thread, so on-demand analysis
# (download + librosa) doesn't block other requests.
@app.post("/v1/similar")
def similar(request: SimilarRequest) -> dict:
    try:
        return state["service"].similar(
            track_id=request.track_id,
            title=request.title,
            artist=request.artist,
            limit=request.limit,
            explain=request.explain,
            country=request.country.lower(),
        )
    except SongNotFound as error:
        raise HTTPException(status_code=404, detail=str(error)) from error

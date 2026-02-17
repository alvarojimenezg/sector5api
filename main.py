import json
import os
from typing import Annotated, Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlparse, urlunparse
from urllib.request import Request, urlopen

from fastapi import Depends, FastAPI, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from database import SessionLocal, metadata

app = FastAPI()

HTTP_TIMEOUT_SECONDS = float(os.getenv("FIVEM_HTTP_TIMEOUT", "5"))
DEFAULT_FIVEM_SERVER_URL = os.getenv("FIVEM_SERVER_URL", "http://localhost:30120")


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


db_dependency = Annotated[Session, Depends(get_db)]


def normalize_base_url(url: str) -> str:
    clean_url = (url or "").strip().rstrip("/")
    if not clean_url:
        raise ValueError("FIVEM_SERVER_URL no puede estar vacio.")

    parsed = urlparse(clean_url)
    if parsed.scheme not in {"http", "https"}:
        raise ValueError("FIVEM_SERVER_URL debe usar http o https.")
    if not parsed.netloc:
        raise ValueError("FIVEM_SERVER_URL no es valido.")

    return urlunparse((parsed.scheme, parsed.netloc, "", "", "", "")).rstrip("/")


def build_fivem_candidates(base_url: str) -> list[str]:
    normalized = normalize_base_url(base_url)
    parsed = urlparse(normalized)
    candidates = [normalized]

    if parsed.port and parsed.port >= 40000:
        alt_port = parsed.port - 10000
        if alt_port > 0 and parsed.hostname:
            alt_netloc = f"{parsed.hostname}:{alt_port}"
            alt_url = urlunparse((parsed.scheme, alt_netloc, "", "", "", "")).rstrip("/")
            if alt_url not in candidates:
                candidates.append(alt_url)

    return candidates


def parse_int(value: Any) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def fetch_json_from_candidate(candidate: str, path: str) -> Any:
    request = Request(
        f"{candidate}{path}",
        headers={"Accept": "application/json", "User-Agent": "sector5api/1.0"},
    )

    with urlopen(request, timeout=HTTP_TIMEOUT_SECONDS) as response:
        body = response.read().decode("utf-8", errors="replace")

    try:
        return json.loads(body)
    except json.JSONDecodeError as exc:
        raise ValueError(f"Respuesta no JSON en {candidate}{path}") from exc


def pick_hostname(dynamic_data: dict[str, Any], info_data: dict[str, Any]) -> str | None:
    dynamic_hostname = dynamic_data.get("hostname")
    if isinstance(dynamic_hostname, str) and dynamic_hostname.strip():
        return dynamic_hostname.strip()

    info_vars = info_data.get("vars")
    if isinstance(info_vars, dict):
        project_name = info_vars.get("sv_projectName")
        if isinstance(project_name, str) and project_name.strip():
            return project_name.strip()

    return None


def map_player(player: Any, index: int) -> dict[str, Any]:
    if not isinstance(player, dict):
        return {
            "id": f"player-{index + 1}",
            "name": f"Jugador {index + 1}",
            "identifier": None,
            "ping": None,
        }

    player_id = player.get("id")
    player_name = player.get("name")
    ping = parse_int(player.get("ping"))

    identifiers = player.get("identifiers")
    identifier = None
    if isinstance(identifiers, list):
        for value in identifiers:
            if isinstance(value, str) and value.strip():
                identifier = value.strip()
                break

    return {
        "id": str(player_id) if player_id is not None else f"player-{index + 1}",
        "name": player_name.strip() if isinstance(player_name, str) and player_name.strip() else f"Jugador {index + 1}",
        "identifier": identifier,
        "ping": ping,
    }


def collect_fivem_overview(base_url: str) -> dict[str, Any]:
    errors: list[str] = []

    for candidate in build_fivem_candidates(base_url):
        try:
            dynamic_data = fetch_json_from_candidate(candidate, "/dynamic.json")
            players_data = fetch_json_from_candidate(candidate, "/players.json")
            info_data = fetch_json_from_candidate(candidate, "/info.json")
        except (HTTPError, URLError, TimeoutError, ValueError) as exc:
            errors.append(f"{candidate}: {exc}")
            continue

        if not isinstance(dynamic_data, dict):
            dynamic_data = {}
        if not isinstance(info_data, dict):
            info_data = {}

        raw_players = players_data if isinstance(players_data, list) else []
        players = [map_player(player, index) for index, player in enumerate(raw_players)]

        players_online = parse_int(dynamic_data.get("clients"))
        if players_online is None:
            players_online = len(players)

        players_max = parse_int(dynamic_data.get("sv_maxclients"))
        if players_max is None:
            vars_data = info_data.get("vars")
            if isinstance(vars_data, dict):
                players_max = parse_int(vars_data.get("sv_maxClients"))

        return {
            "reachable": True,
            "source_url": candidate,
            "hostname": pick_hostname(dynamic_data, info_data),
            "players_online": players_online,
            "players_max": players_max,
            "players": players[:50],
            "error": None,
        }

    return {
        "reachable": False,
        "source_url": None,
        "hostname": None,
        "players_online": 0,
        "players_max": None,
        "players": [],
        "error": errors[-1] if errors else "No se pudo conectar con FiveM.",
    }


@app.get("/users", status_code=status.HTTP_200_OK)
async def get_all_users(db: db_dependency):
    users_table = metadata.tables["users"]
    query = select(users_table)
    result = db.execute(query)
    users = result.fetchall()
    users_list = [dict(row._mapping) for row in users]
    return {"users": users_list}


@app.get("/users/by-identifier/{identifier}", status_code=status.HTTP_200_OK)
async def get_user_by_identifier(identifier: str, db: db_dependency):
    users_table = metadata.tables["users"]
    query = select(users_table).where(users_table.c.identifier == identifier)
    result = db.execute(query)
    user = result.fetchone()

    if user is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")

    return {"user": dict(user._mapping)}


@app.get("/server/overview", status_code=status.HTTP_200_OK)
async def get_server_overview():
    try:
        return collect_fivem_overview(DEFAULT_FIVEM_SERVER_URL)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
